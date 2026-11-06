"""任务状态机与唯一写入口。

背景（审计 05）：
- 旧实现里 `GET /api/jobs/{id}` 每次调用都会访问 ComfyUI、写数据库、插图片，
  前端 1 Hz 轮询 + 后台 5 s 监控 + 第二个 tab 一起读，就变成多个写者在做
  read-modify-write，日志里同一个 prompt_id 的 `[JOB] item done` 出现过 12 次。
- 这里把职责拆开：
    read_snapshot()  纯读（只查 DB，不访问 ComfyUI，不写库）
    refresh_job()    唯一的推进函数，只由 writer_loop 线程调用
    cancel_job()     请求线程只做一次带锁状态写入，不反推、不回写
- `unknown` 不再落库：无法判定时保留原状态，等下一轮。

这条约束是 SSE、多任务并行、以及后续一切"任务可见性"改动的前提。
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from peewee import fn

from app.config import settings
from app.models import Image, GenJob, db, inherit_prompt_taxonomy
from app.services.image_store import upsert_image
from app.services.quality_keys import normalize_quality
from app.services.comfyui_client import (
    delete_queue_items,
    get_history,
    get_progress,
    get_queue,
    interrupt,
)
from app.services.image_meta import (
    captured_at_for_image,
    compute_orientation,
    extract_model_name,
    extract_run_params,
    extract_run_times,
    get_image_metadata,
)
from app.services.paths import build_view_url, resolve_image_path
from app.services.thumbnail import prewarm_thumbnail

logger = logging.getLogger("atelier.jobs")

TERMINAL = {"done", "error", "cancelled", "stopped"}

# 提交宽限期：任务创建后，条目的 prompt_id 要等 push 完才写回 DB。
# 批量 160 张的提交循环可能持续几分钟，这期间不能让写者把"还没有 pid"当成失败。
_SUBMIT_GRACE_SECONDS = 300


def _job_age_seconds(job: dict) -> float:
    """任务创建至今的秒数。created_at 由 SQLite CURRENT_TIMESTAMP 写成 UTC，
    必须用 UTC 比较，否则会凭空多出 8 小时（东八区），宽限期直接失效。"""
    raw = job.get("created_at") or ""
    try:
        created = datetime.fromisoformat(str(raw).replace("Z", ""))
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        return max(0.0, (now_utc - created).total_seconds())
    except (TypeError, ValueError):
        return 0.0


def _utcnow() -> datetime:
    """与 SQLite CURRENT_TIMESTAMP 一致的 UTC 无时区时间。

    历史事故：created_at 由 CURRENT_TIMESTAMP 写 UTC，updated_at 却用
    datetime.now() 写本地时间，任务页于是恒定多出 8 小时。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc_iso(value, anchor: datetime | None = None) -> str:
    """把库里的时间统一成带时区的 ISO 字符串，前端 `new Date()` 才不会按本地解析。

    旧数据里 updated_at 可能是本地时间（datetime.now()），而 created_at 始终由
    SQLite CURRENT_TIMESTAMP 写 UTC。仅凭 updated_at 无法区分（过了 8 小时后就
    不在"未来"了），所以用 created_at 当锚：差值与本地时区偏移相近时按旧格式纠正。
    """
    if not value:
        return ""
    if isinstance(value, str):
        text = value.strip().replace("Z", "")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return value
    elif isinstance(value, datetime):
        dt = value
    else:
        return str(value)

    if dt.tzinfo is None:
        offset = datetime.now().astimezone().utcoffset() or timedelta(0)
        shifted = dt - offset if offset else dt
        looks_legacy = False
        if anchor is not None:
            diff = dt - anchor
            # 真实耗时通常几分钟；差值落在「时区偏移 -10min ~ +6h」只可能是旧格式
            looks_legacy = (offset - timedelta(minutes=10)) <= diff <= (offset + timedelta(hours=6))
        if looks_legacy and shifted >= anchor:
            dt = shifted
        elif dt > _utcnow() + timedelta(minutes=5):
            # 兜底：比当前 UTC 还超前，只能是本地时间
            dt = shifted
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")

# 所有 gen_jobs / gen_history 的任务相关写入都在这把锁内完成
_lock = threading.RLock()

# SSE 订阅者：每个连接一个 Queue；满了就丢旧事件，绝不阻塞写者
_subscribers: list[queue.Queue] = []
_sub_lock = threading.Lock()


# ---------------------------------------------------------------------------
# 基础转换
# ---------------------------------------------------------------------------

def row_to_dict(r) -> dict:
    created_iso = to_utc_iso(r.created_at)
    anchor = None
    if created_iso:
        try:
            anchor = datetime.fromisoformat(created_iso.replace("Z", ""))
        except ValueError:
            anchor = None
    return {
        "id": r.id,
        "job_type": r.job_type,
        "status": r.status,
        "title": r.title,
        "total": r.total,
        "done_count": r.done_count,
        "error_count": r.error_count,
        "items": r.items,
        "workflow_path": r.workflow_path,
        "orientation": r.orientation,
        "quality": r.quality,
        # extra 存的是 JSON 字符串，对外给对象 —— 前端要直接取字段（节点映射等）
        "extra": _parse_extra(r.extra),
        "created_at": created_iso,
        "updated_at": to_utc_iso(r.updated_at, anchor=anchor),
    }




def _parse_extra(raw):
    """extra 列存的是 JSON 字符串，对外还原成对象。

    之前直接返回字符串，前端拿到后只能自己再 parse 一次；加了响应模型之后
    更会直接校验失败（模型声明的是 dict）。
    """
    if isinstance(raw, str) and raw:
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return None
    return raw
def _parse_items(raw) -> list[dict]:
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        value = json.loads(raw)
        return value if isinstance(value, list) else []
    except (TypeError, ValueError):
        return []


def parse_items(raw) -> list[dict]:
    """公开只读解析：后台提交线程需要检查条目状态。"""
    return _parse_items(raw)


def normalize(job: dict) -> dict:
    """把 DB 行变成 API 形状：items 一定是数组，每条都有 status/progress。"""
    items = _parse_items(job.get("items"))
    for item in items:
        item.setdefault("status", "pending")
        item.setdefault("progress", None)
    job["items"] = items
    job["total"] = job.get("total") or len(items)
    job["done_count"] = job.get("done_count") or 0
    job["error_count"] = job.get("error_count") or 0
    job["extra"] = _parse_items(job.get("extra")) or job.get("extra")
    return job


# ---------------------------------------------------------------------------
# 事件发布（SSE）
# ---------------------------------------------------------------------------

def subscribe() -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=200)
    with _sub_lock:
        _subscribers.append(q)
    return q


def unsubscribe(q: queue.Queue) -> None:
    with _sub_lock:
        if q in _subscribers:
            _subscribers.remove(q)


def publish(job: dict) -> None:
    event = {"type": "job", "seq": time.time_ns(), "job": job}
    with _sub_lock:
        targets = list(_subscribers)
    for q in targets:
        try:
            q.put_nowait(event)
        except queue.Full:
            # 慢客户端：丢掉最旧的一条，保持流继续
            try:
                q.get_nowait()
                q.put_nowait(event)
            except Exception:
                pass


def subscriber_count() -> int:
    with _sub_lock:
        return len(_subscribers)


# ---------------------------------------------------------------------------
# 读
# ---------------------------------------------------------------------------

def read_snapshot(job_id: int) -> dict | None:
    row = GenJob.get_or_none(GenJob.id == job_id)
    if row is None:
        return None
    return normalize(row_to_dict(row))


def list_snapshots(active: bool = False, limit: int = 50) -> list[dict]:
    query = GenJob.select()
    if active:
        query = query.where(GenJob.status.in_(["pending", "running"]))
    return [normalize(row_to_dict(r)) for r in query.order_by(GenJob.id.desc()).limit(limit)]


# ---------------------------------------------------------------------------
# 写：创建 / 提交阶段更新
# ---------------------------------------------------------------------------

def create_job(
    job_type: str, title: str, items: list[dict],
    workflow_path: str, orientation: str,
    quality: str, extra: dict | None = None,
) -> int:
    with _lock:
        r = GenJob.create(
            job_type=job_type,
            status="pending",
            title=title,
            total=len(items),
            items=json.dumps(items, ensure_ascii=False),
            workflow_path=workflow_path,
            orientation=orientation,
            quality=normalize_quality(quality),
            extra=json.dumps(extra) if extra else None,
        )
    publish(read_snapshot(r.id))
    return r.id


def update_job_items(job_id: int, items: list[dict], status: str | None = None):
    """提交阶段（push 完一批 prompt 后）由请求线程调用。"""
    done = sum(1 for i in items if i.get("status") == "done")
    errors = sum(1 for i in items if i.get("status") in ("error", "cancelled"))
    with _lock:
        GenJob.update(
            status=status or "running",
            done_count=done,
            error_count=errors,
            items=json.dumps(items, ensure_ascii=False),
            updated_at=_utcnow(),
        ).where(GenJob.id == job_id).execute()
    snap = read_snapshot(job_id)
    if snap:
        publish(snap)


def _overall_status(items: list[dict], fallback: str = "running") -> str:
    """按条目状态推进总状态；仍存在 pending/running 时保持 running。"""
    if not items:
        return fallback
    statuses = [str(i.get("status") or "pending") for i in items]
    if not all(s in TERMINAL for s in statuses):
        return "running"
    if all(s == "done" for s in statuses):
        return "done"
    if all(s in ("cancelled", "stopped") for s in statuses):
        return "stopped"
    return "error"


def update_job_item(
    job_id: int, index: int, fields: dict, status: str | None = None,
) -> dict | None:
    """只更新一条 item（后台提交线程用），避免整批读改写覆盖其它条目的并发变化。"""
    with _lock:
        row = GenJob.get_or_none(GenJob.id == job_id)
        if row is None:
            return None
        items = _parse_items(row.items)
        if index < 0 or index >= len(items):
            return None
        item = items[index]
        # 取消/终态优先：提交线程不能把用户刚取消的条目标回 pending
        if item.get("status") in TERMINAL:
            return normalize(row_to_dict(row))
        item.update(fields)
        done = sum(1 for i in items if i.get("status") == "done")
        errors = sum(1 for i in items if i.get("status") in ("error", "cancelled"))
        overall = status or _overall_status(items, row.status)
        GenJob.update(
            status=overall,
            done_count=done,
            error_count=errors,
            items=json.dumps(items, ensure_ascii=False),
            updated_at=_utcnow(),
        ).where(GenJob.id == job_id).execute()
    snap = read_snapshot(job_id)
    if snap:
        publish(snap)
    return snap


def finish_submission(job_id: int, reason: str = "提交队列中断，请重试") -> dict | None:
    """后台提交线程结束（或重启恢复）时，把仍未提交的 queued 条目标成错误。"""
    with _lock:
        row = GenJob.get_or_none(GenJob.id == job_id)
        if row is None:
            return None
        items = _parse_items(row.items)
        changed = False
        for item in items:
            if item.get("submit_state") == "queued" and item.get("status") not in TERMINAL:
                item["status"] = "error"
                item["error"] = reason
                item["submit_state"] = "failed"
                changed = True
        done = sum(1 for i in items if i.get("status") == "done")
        errors = sum(1 for i in items if i.get("status") in ("error", "cancelled"))
        overall = _overall_status(items, row.status)
        if changed or row.status in ("pending", "running"):
            GenJob.update(
                status=overall,
                done_count=done,
                error_count=errors,
                items=json.dumps(items, ensure_ascii=False),
                updated_at=_utcnow(),
            ).where(GenJob.id == job_id).execute()
    snap = read_snapshot(job_id)
    if snap:
        publish(snap)
    return snap


def recover_queued_submissions(reason: str = "服务重启，提交中断，请重试") -> int:
    """启动时清理上次进程遗留的 queued 条目（任务队列在内存里，重启即丢）。"""
    recovered = 0
    rows = (
        GenJob.select()
        .where(GenJob.status.in_(["pending", "running"]))
    )
    for row in rows:
        items = _parse_items(row.items)
        if any(i.get("submit_state") == "queued" for i in items):
            finish_submission(row.id, reason)
            recovered += 1
    return recovered


def build_job_extra(
    workflow_path: str,
    workflow_content: str | None,
    output_subfolder: str = "",
    **extra,
) -> dict:
    """统一的 gen_jobs.extra：记录出图子目录 / 自定义工作流内容，供重试复用。"""
    data = {"output_subfolder": output_subfolder or ""}
    if str(workflow_path or "").startswith("custom://") and workflow_content:
        data["workflow_content"] = workflow_content
    data.update(extra)
    return data


def find_job_by_idempotency(key: str, scope: str) -> dict | None:
    """按「幂等键 + 入口范围」找已经创建过的任务；空键直接返回 None。

    键存在 `gen_jobs.extra` JSON 里，不额外加列；任务量很小，json_extract 足够。
    """
    clean = (key or "").strip()
    if not clean:
        return None
    try:
        row = (
            GenJob.select()
            .where(
                (fn.json_extract(GenJob.extra, "$.idempotency_key") == clean)
                & (fn.json_extract(GenJob.extra, "$.idempotency_scope") == scope)
            )
            .order_by(GenJob.id.desc())
            .first()
        )
    except Exception:
        logger.exception("幂等键查询失败: %s", clean)
        return None
    return normalize(row_to_dict(row)) if row else None


# ---------------------------------------------------------------------------
# 写：状态推进（唯一写者）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ComfySnapshot:
    """一次 writer 周期内共享的 ComfyUI 视图。"""

    queue: dict
    history: dict
    running: set[str]
    pending: set[str]
    progress: dict | None
    current_pid: str | None


def fetch_comfy_snapshot() -> ComfySnapshot:
    """采集一次 ComfyUI 队列/历史/进度。

    旧实现每个活跃任务各拉一遍 queue/history/progress；20 个任务就是 40-60 req/s。
    writer 每轮只取一次，再分发给所有任务。
    """
    qdata = get_queue() or {}
    running: set[str] = set()
    pending: set[str] = set()
    for entry in qdata.get("queue_running", []):
        if isinstance(entry, list) and len(entry) > 1:
            running.add(str(entry[1]))
    for entry in qdata.get("queue_pending", []):
        if isinstance(entry, list) and len(entry) > 1:
            pending.add(str(entry[1]))

    progress_data = None
    current_pid = None
    if qdata.get("queue_running"):
        first = qdata["queue_running"][0]
        if isinstance(first, list) and len(first) > 1:
            current_pid = str(first[1])
            prog = get_progress()
            if prog:
                progress_data = {
                    "progress": prog.get("progress", 0),
                    "max": prog.get("max", 0),
                    "current_node": prog.get("current_node", ""),
                }

    return ComfySnapshot(
        queue=qdata,
        history=get_history(max_items=500) or {},
        running=running,
        pending=pending,
        progress=progress_data,
        current_pid=current_pid,
    )


def _compute(job: dict, snapshot: ComfySnapshot | None = None) -> tuple[dict, list[dict]]:
    """根据 ComfyUI 队列/历史计算一次状态。纯计算，不写库。"""
    items = job["items"]
    snap = snapshot or fetch_comfy_snapshot()
    running = snap.running
    pending = snap.pending
    # 每个任务可能补查自己的 miss pid，复制一份避免污染共享快照
    hist = dict(snap.history)

    all_pids = {item.get("comfyui_prompt_id") for item in items if item.get("comfyui_prompt_id")}
    miss_pids = {pid for pid in all_pids if pid and pid not in hist}
    if miss_pids and len(miss_pids) <= 10:
        # 未命中的（例如刚提交）逐条精确补查；数量大时放弃，避免拖垮轮询
        from app.services.comfyui_client import get_history_for_prompt

        for pid in miss_pids:
            single = get_history_for_prompt(pid)
            if single and pid in single:
                hist[pid] = single[pid]

    progress_data = snap.progress
    current_pid = snap.current_pid

    newly_done: list[dict] = []
    # 完成瞬间把 ComfyUI history 里的实际参数与耗时留下来，
    # 之后画廊的「出图参数」不依赖 history 是否还留着这条
    run_meta_by_pid: dict[str, dict] = {}
    done_count = 0
    error_count = 0

    for item in items:
        pid = item.get("comfyui_prompt_id")
        prev_status = item.get("status", "pending")
        status = prev_status
        iprogress = None

        if pid and pid in hist:
            status = "done"
            images = []
            for node_out in hist[pid].get("outputs", {}).values():
                for img in node_out.get("images", []):
                    images.append(img)
            # 过滤掉磁盘上已不存在的图片（ComfyUI 会长期保留已删文件的 history 条目）
            valid = []
            for img in images:
                path = resolve_image_path(
                    img.get("filename", ""),
                    img.get("subfolder", "") or "",
                    img.get("type", "output"),
                )
                if path is not None:
                    valid.append(img)
                else:
                    logger.debug("跳过已删除的图片: %s", img.get("filename", ""))
            item["images"] = valid
            done_count += 1
            if prev_status != "done":
                newly_done.append(item)
                run_meta_by_pid[pid] = {
                    **extract_run_params(hist[pid].get("prompt")),
                    **extract_run_times(hist[pid]),
                }
        elif pid and pid in running:
            status = "running"
            if pid == current_pid and progress_data:
                iprogress = progress_data
        elif pid and pid in pending:
            status = "pending"
        elif prev_status in ("done", "error", "cancelled"):
            status = prev_status
            if prev_status == "done":
                done_count += 1
            else:
                error_count += 1
        elif not pid:
            if item.get("submit_state") == "queued":
                # 后台提交队列还没轮到这条：不要用宽限期判失败
                status = "pending"
            elif _job_age_seconds(job) < _SUBMIT_GRACE_SECONDS:
                # 还在提交窗口里：create_job 之后、update_job_items 之前，pid 还没写回
                status = "pending"
            else:
                # 超过宽限期仍没有 pid：提交阶段就失败了
                status = "error"
                item["error"] = item.get("error") or "任务提交到 ComfyUI 失败（无 prompt_id），请检查 ComfyUI 连接"
                error_count += 1
                logger.warning("任务 %s 有条目缺少 prompt_id: %s", job["id"], (item.get("prompt_preview") or "")[:60])
        else:
            # 有 pid 但队列和历史都没命中：ComfyUI 忙/慢，保留原状态，下一轮再查。
            # 这里绝不写 unknown —— 它一旦落库就再没有任何代码会重新选中它。
            status = prev_status
            if status == "done":
                done_count += 1
            elif status in ("error", "cancelled"):
                error_count += 1
            else:
                logger.debug("pid=%s 暂不可判定，保留状态 %s", pid, status)

        item["status"] = status
        item["progress"] = iprogress

    if done_count + error_count == len(items):
        overall = "done" if error_count == 0 else "error"
    elif any(i.get("status") == "running" for i in items):
        overall = "running"
    elif any(i.get("status") == "pending" for i in items):
        overall = "pending"
    else:
        # 兜底：保持可推进状态，不落 unknown
        overall = job["status"] if job["status"] in ("pending", "running") else "error"

    job.update(
        status=overall,
        done_count=done_count,
        error_count=error_count,
        items=items,
    )
    # 内部传递用，不落库、不进 API 响应（row_to_dict 每次都是新 dict）
    job["_run_meta"] = run_meta_by_pid
    return job, newly_done


def _merge_items(computed: list[dict], fresh: list[dict]) -> list[dict]:
    """把 _compute 的结果与库里最新的 items 按位置合并。

    _compute 用的是锁外读到的 items，而提交阶段的请求线程（update_job_items）
    可能在此期间刚把 comfyui_prompt_id 和逐条提交错误写回。旧实现直接整体覆盖，
    于是那些 pid 被抹掉，宽限期一过整批被判成「提交失败」——图其实已经出来了。
    合并规则：库里已有的 pid / 错误 / 已落定的终态优先，计算出的进度信息其次。
    """
    if not fresh:
        return computed

    merged: list[dict] = []
    for idx, item in enumerate(computed):
        base = dict(item)
        old = fresh[idx] if idx < len(fresh) else None
        if isinstance(old, dict):
            if not base.get("comfyui_prompt_id") and old.get("comfyui_prompt_id"):
                base["comfyui_prompt_id"] = old["comfyui_prompt_id"]
            if not base.get("error") and old.get("error"):
                base["error"] = old["error"]
            if old.get("submit_state"):
                base["submit_state"] = old["submit_state"]
            if not base.get("images") and old.get("images"):
                base["images"] = old["images"]
            # 提交阶段写回的终态（done/error/cancelled）比基于陈旧队列的推断可信
            if (old.get("status") in ("done", "error", "cancelled")
                    and base.get("status") not in ("done", "error", "cancelled")):
                base["status"] = old["status"]
        merged.append(base)

    # 计算期间新增的条目（理论上不会发生）原样保留，避免丢数据
    merged.extend(fresh[len(computed):])
    return merged


def _counts_and_status(items: list[dict], fallback: str, db_status: str) -> tuple[int, int, str]:
    """按合并后的 items 重新统计 counts 与总状态。"""
    done = sum(1 for i in items if i.get("status") == "done")
    errors = sum(1 for i in items if i.get("status") in ("error", "cancelled"))

    if items and done + errors == len(items):
        overall = "done" if errors == 0 else "error"
    elif any(i.get("status") == "running" for i in items):
        overall = "running"
    elif any(i.get("status") == "pending" for i in items):
        overall = "pending"
    else:
        overall = fallback

    # 提交阶段刚把任务置成 running，不能被更早算出的 pending 覆盖回去
    if overall == "pending" and db_status == "running":
        overall = "running"
    return done, errors, overall


def _insert_history_for_item(
    job_id: int, prompt_id, comfy_pid: str, images: list[dict],
    preview: str = "", prompt_params=None, run_meta: dict | None = None,
):
    """把新完成的出图写入 gen_history（upsert 到部分唯一索引）。"""
    if isinstance(prompt_params, str):
        try:
            pp = json.loads(prompt_params) if prompt_params else {}
        except ValueError:
            pp = {}
    else:
        pp = dict(prompt_params or {})

    # history 里是工作流真正执行时的参数；提示词记录可能没填 steps/sampler，
    # 这里补上实际值，出图参数面板才能看到完整信息
    for key, value in (run_meta or {}).items():
        if value not in (None, ""):
            pp[key] = value

    if not pp.get("model") and images:
        first = images[0]
        model = extract_model_name(
            first["filename"], first.get("subfolder", ""), first.get("type", "output")
        )
        if model:
            pp["model"] = model

    if (not pp.get("width") or not pp.get("height") or not pp.get("orientation")) and images:
        first = images[0]
        meta = get_image_metadata(
            first["filename"], first.get("subfolder", ""), first.get("type", "output")
        )
        width, height = meta.get("width"), meta.get("height")
        if width and height:
            pp["width"] = width
            pp["height"] = height
            orientation = compute_orientation(width, height)
            if orientation:
                pp["orientation"] = orientation

    prompt_params_json = json.dumps(pp, ensure_ascii=False)
    for img in images:
        try:
            captured = captured_at_for_image(
                img["filename"], img.get("subfolder", ""), img.get("type", "output")
            )
            update_fields = {
                Image.comfyui_prompt_id: comfy_pid,
                Image.job_id: job_id,
                Image.prompt_id: prompt_id,
                Image.view_url: build_view_url(
                    img["filename"], img.get("subfolder", ""), img.get("type", "output")
                ),
                Image.prompt_params: prompt_params_json,
                Image.source: "local",
                Image.is_deleted: False,
            }
            if captured is not None:
                update_fields[Image.captured_at] = captured

            with db.atomic():
                upsert_image(
                    {
                        "job_id": job_id,
                        "prompt_id": prompt_id,
                        "comfyui_prompt_id": comfy_pid,
                        "filename": img["filename"],
                        "subfolder": img.get("subfolder", ""),
                        "img_type": img.get("type", "output"),
                        "view_url": build_view_url(
                            img["filename"], img.get("subfolder", ""), img.get("type", "output")
                        ),
                        "preview": preview,
                        "prompt_params": prompt_params_json,
                        "captured_at": captured,
                        "source": "local",
                    },
                    update_fields,
                )

                nh = Image.get_or_none(
                    (Image.comfyui_prompt_id == comfy_pid)
                    & (Image.filename == img["filename"])
                    & (Image.subfolder == img.get("subfolder", ""))
                    & (Image.img_type == img.get("type", "output"))
                )
                if nh:
                    # 入库 + 继承分类同一事务：避免"图进了库、分类没继承"的半截状态
                    inherit_prompt_taxonomy(nh.id)
                # 出图完成即铺缩略图：用户切到画廊时直接命中缓存，不在首屏现解码
                prewarm_thumbnail(
                    img["filename"], img.get("subfolder", ""), img.get("type", "output"), 600
                )
        except Exception:
            logger.exception("写入历史失败: %s", img.get("filename"))


def refresh_job(job_id: int, snapshot: ComfySnapshot | None = None) -> dict | None:
    """推进一个任务。只允许 writer_loop 调用（测试可直接调用）。

    `snapshot` 由 `refresh_active_jobs` 每轮采集一次后共享；单独调用时自行采集。
    """
    row = GenJob.get_or_none(GenJob.id == job_id)
    if row is None:
        return None
    job = normalize(row_to_dict(row))
    if job["status"] in TERMINAL:
        return job

    # 网络查询放在锁外，避免阻塞 cancel / 其它 job 的短写入。
    # 仅在共享快照存在时传第二参：保留旧的 `_compute(job)` 单参猴子补丁兼容性。
    if snapshot is None:
        computed, newly_done = _compute(job)
    else:
        computed, newly_done = _compute(job, snapshot)
    run_meta_by_pid = computed.pop("_run_meta", {}) or {}

    with _lock:
        current = GenJob.get_or_none(GenJob.id == job_id)
        if current is None:
            return None
        if current.status in TERMINAL:
            # 计算期间被取消/完成：尊重已落库的终态，绝不"复活"
            return normalize(row_to_dict(current))

        # 提交阶段写回的 pid / 错误不能丢：_compute 基于锁外读到的陈旧 items，
        # 整体覆盖会让"已出图"的任务永远看不到 prompt_id。
        merged = _merge_items(computed["items"], _parse_items(current.items))
        done, errors, overall = _counts_and_status(merged, computed["status"], current.status)

        for item in newly_done:
            logger.info("任务 %s 完成一张：pid=%s images=%d",
                        job_id, item.get("comfyui_prompt_id"), len(item.get("images") or []))
            _insert_history_for_item(
                job_id, item.get("prompt_id"), item.get("comfyui_prompt_id"),
                item.get("images") or [], item.get("prompt_preview", ""),
                item.get("prompt_params"),
                run_meta=run_meta_by_pid.get(item.get("comfyui_prompt_id")),
            )

        GenJob.update(
            status=overall,
            done_count=done,
            error_count=errors,
            items=json.dumps(merged, ensure_ascii=False),
            updated_at=_utcnow(),
        ).where(GenJob.id == job_id).execute()

        stored = normalize(row_to_dict(GenJob.get_by_id(job_id)))

    publish(stored)
    return stored


# ---------------------------------------------------------------------------
# 取消：只影响本任务
# ---------------------------------------------------------------------------

def cancel_job(job_id: int) -> bool:
    row = GenJob.get_or_none(GenJob.id == job_id)
    if row is None:
        return False

    job = normalize(row_to_dict(row))
    pids = {str(it.get("comfyui_prompt_id")) for it in job["items"] if it.get("comfyui_prompt_id")}

    # 先看队列里哪些 pid 属于这个任务；ComfyUI 的 interrupt 没有 job 概念，
    # 旧的 cancel 直接 interrupt + clear_queue，会把别的任务正在跑的那张也杀掉。
    qdata = get_queue() or {}
    running = {
        str(e[1]) for e in qdata.get("queue_running", [])
        if isinstance(e, list) and len(e) > 1
    }
    pending = {
        str(e[1]) for e in qdata.get("queue_pending", [])
        if isinstance(e, list) and len(e) > 1
    }
    running_mine = running & pids
    pending_mine = pending & pids

    items = job["items"]
    for item in items:
        if item.get("status") != "done":
            item["status"] = "cancelled"
            item["error"] = item.get("error") or "已取消"

    with _lock:
        GenJob.update(
            status="stopped",
            items=json.dumps(items, ensure_ascii=False),
            updated_at=_utcnow(),
        ).where(GenJob.id == job_id).execute()

    if running_mine:
        interrupt()
    if pending_mine:
        delete_queue_items(sorted(pending_mine))

    snapshot = read_snapshot(job_id)
    if snapshot:
        publish(snapshot)
    logger.info("任务 %s 已取消（running=%d pending=%d）", job_id, len(running_mine), len(pending_mine))
    return True


def stop_all() -> int:
    """兼容旧 /api/jobs/stop_all：取消所有进行中的任务。"""
    ids = [r.id for r in GenJob.select(GenJob.id).where(GenJob.status.in_(["pending", "running"]))]
    for job_id in ids:
        try:
            cancel_job(job_id)
        except Exception:
            logger.exception("取消任务 %s 失败", job_id)
    return len(ids)


# ---------------------------------------------------------------------------
# 写者线程
# ---------------------------------------------------------------------------

def refresh_active_jobs(limit: int = 20) -> int:
    ids = [
        r.id for r in GenJob.select(GenJob.id)
        .where(GenJob.status.in_(["pending", "running"]))
        .order_by(GenJob.id.desc())
        .limit(limit)
    ]
    if not ids:
        return 0

    # 一轮只采集一次 ComfyUI 快照，所有活跃任务共用；无活跃任务时不外呼。
    snapshot = fetch_comfy_snapshot()
    for job_id in ids:
        try:
            refresh_job(job_id, snapshot)
        except Exception:
            logger.exception("刷新任务 %s 失败", job_id)
    return len(ids)


def writer_loop(stop_event: threading.Event, interval: float = 1.0,
                sync_interval: float = 30.0, integrity_interval: float = 600.0) -> None:
    """后台唯一写者：推进活跃任务 + 定期同步 ComfyUI 历史 + 低频文件完整性巡检。

    这是一个普通线程，不是 async task —— 旧的 job_monitor_loop 在事件循环里
    跑同步 HTTP/DB，ComfyUI 一慢就会阻塞所有请求。
    """
    logger.info(
        "任务写者线程已启动（interval=%.1fs, sync=%.0fs, integrity=%.0fs）",
        interval, sync_interval, integrity_interval,
    )
    last_sync = 0.0
    # -1e9 保证启动后立刻巡检一次，不用等满一个周期
    last_integrity = -1e9
    while not stop_event.is_set():
        try:
            refresh_active_jobs()
        except Exception:
            logger.exception("刷新活跃任务失败")

        now = time.monotonic()
        if now - last_sync >= sync_interval:
            last_sync = now
            try:
                from app.routers.images import sync_all

                sync_all()
            except Exception:
                logger.exception("同步 ComfyUI 历史失败")

        if now - last_integrity >= integrity_interval:
            last_integrity = now
            try:
                from app.services.integrity import scan_missing

                result = scan_missing()
                if result["marked"] or result["cleared"]:
                    logger.info(
                        "文件完整性巡检：检查 %s 条，新标记缺失 %s 条，恢复 %s 条",
                        result["checked"], result["marked"], result["cleared"],
                    )
            except Exception:
                logger.exception("文件完整性巡检失败")

        stop_event.wait(interval)
    logger.info("任务写者线程已停止")
