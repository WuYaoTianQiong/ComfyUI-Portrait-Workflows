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
from datetime import datetime

from peewee import SQL

from config import settings
from models import GenHistory, GenJob, inherit_prompt_taxonomy
from services.comfyui_client import (
    delete_queue_items,
    get_history,
    get_progress,
    get_queue,
    interrupt,
)
from services.helpers import (
    build_view_url,
    compute_orientation,
    extract_model_name,
    get_image_metadata,
)

logger = logging.getLogger("prompt_browser.jobs")

TERMINAL = {"done", "error", "cancelled", "stopped"}

# 部分唯一索引的冲突条件必须是 SQL 字面量：写成 (is_deleted == False) 会生成
# 带引号的 "is_deleted" = 0，SQLite 不认，ON CONFLICT 会报"不匹配任何唯一约束"。
_IS_DELETED_ZERO = SQL("is_deleted=0")

# 所有 gen_jobs / gen_history 的任务相关写入都在这把锁内完成
_lock = threading.RLock()

# SSE 订阅者：每个连接一个 Queue；满了就丢旧事件，绝不阻塞写者
_subscribers: list[queue.Queue] = []
_sub_lock = threading.Lock()


# ---------------------------------------------------------------------------
# 基础转换
# ---------------------------------------------------------------------------

def row_to_dict(r) -> dict:
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
        "extra": r.extra,
        "created_at": str(r.created_at) if r.created_at else "",
        "updated_at": str(r.updated_at) if r.updated_at else "",
    }


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
            quality=quality,
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
            updated_at=datetime.now(),
        ).where(GenJob.id == job_id).execute()
    snap = read_snapshot(job_id)
    if snap:
        publish(snap)


# ---------------------------------------------------------------------------
# 写：状态推进（唯一写者）
# ---------------------------------------------------------------------------

def _compute(job: dict) -> tuple[dict, list[dict]]:
    """根据 ComfyUI 队列/历史计算一次状态。纯计算，不写库。"""
    items = job["items"]

    qdata = get_queue() or {}
    running: set[str] = set()
    pending: set[str] = set()
    for entry in qdata.get("queue_running", []):
        if isinstance(entry, list) and len(entry) > 1:
            running.add(str(entry[1]))
    for entry in qdata.get("queue_pending", []):
        if isinstance(entry, list) and len(entry) > 1:
            pending.add(str(entry[1]))

    hist = get_history(max_items=500) or {}

    all_pids = {item.get("comfyui_prompt_id") for item in items if item.get("comfyui_prompt_id")}
    miss_pids = {pid for pid in all_pids if pid and pid not in hist}
    if miss_pids and len(miss_pids) <= 10:
        # 未命中的（例如刚提交）逐条精确补查；数量大时放弃，避免拖垮轮询
        from services.comfyui_client import get_history_for_prompt

        for pid in miss_pids:
            single = get_history_for_prompt(pid)
            if single and pid in single:
                hist[pid] = single[pid]

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

    newly_done: list[dict] = []
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
                base = settings.comfyui_root / (img.get("type", "output"))
                path = base / (img.get("subfolder", "") or "") / img["filename"]
                if path.exists():
                    valid.append(img)
                else:
                    logger.debug("跳过已删除的图片: %s", img["filename"])
            item["images"] = valid
            done_count += 1
            if prev_status != "done":
                newly_done.append(item)
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
            # 提交阶段就没拿到 prompt_id：这是真错误，可以直接判失败
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
    return job, newly_done


def _insert_history_for_item(
    job_id: int, prompt_id, comfy_pid: str, images: list[dict],
    preview: str = "", prompt_params=None,
):
    """把新完成的出图写入 gen_history（upsert 到部分唯一索引）。"""
    if isinstance(prompt_params, str):
        try:
            pp = json.loads(prompt_params) if prompt_params else {}
        except ValueError:
            pp = {}
    else:
        pp = prompt_params or {}

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
            GenHistory.insert(
                job_id=job_id, prompt_id=prompt_id,
                comfyui_prompt_id=comfy_pid,
                filename=img["filename"],
                subfolder=img.get("subfolder", ""),
                img_type=img.get("type", "output"),
                view_url=build_view_url(
                    img["filename"], img.get("subfolder", ""), img.get("type", "output")
                ),
                preview=preview,
                prompt_params=prompt_params_json,
                source="local",
            ).on_conflict(
                # 必须与 v4.2 迁移后的部分唯一索引一致：(filename, subfolder, img_type) WHERE is_deleted=0
                conflict_target=[GenHistory.filename, GenHistory.subfolder, GenHistory.img_type],
                conflict_where=_IS_DELETED_ZERO,
                update={
                    GenHistory.comfyui_prompt_id: comfy_pid,
                    GenHistory.job_id: job_id,
                    GenHistory.prompt_id: prompt_id,
                    GenHistory.view_url: build_view_url(
                        img["filename"], img.get("subfolder", ""), img.get("type", "output")
                    ),
                    GenHistory.prompt_params: prompt_params_json,
                    GenHistory.source: "local",
                    GenHistory.is_deleted: False,
                },
            ).execute()
            try:
                nh = GenHistory.get_or_none(
                    (GenHistory.comfyui_prompt_id == comfy_pid)
                    & (GenHistory.filename == img["filename"])
                    & (GenHistory.subfolder == img.get("subfolder", ""))
                    & (GenHistory.img_type == img.get("type", "output"))
                )
                if nh:
                    inherit_prompt_taxonomy(nh.id)
            except Exception:
                logger.exception("继承分类失败: %s", img.get("filename"))
        except Exception:
            logger.exception("写入历史失败: %s", img.get("filename"))


def refresh_job(job_id: int) -> dict | None:
    """推进一个任务。只允许 writer_loop 调用（测试可直接调用）。"""
    row = GenJob.get_or_none(GenJob.id == job_id)
    if row is None:
        return None
    job = normalize(row_to_dict(row))
    if job["status"] in TERMINAL:
        return job

    # 网络查询放在锁外，避免阻塞 cancel / 其它 job 的短写入
    snapshot, newly_done = _compute(job)

    with _lock:
        current = GenJob.get_or_none(GenJob.id == job_id)
        if current is None:
            return None
        if current.status in TERMINAL:
            # 计算期间被取消/完成：尊重已落库的终态，绝不"复活"
            return normalize(row_to_dict(current))

        for item in newly_done:
            logger.info("任务 %s 完成一张：pid=%s images=%d",
                        job_id, item.get("comfyui_prompt_id"), len(item.get("images") or []))
            _insert_history_for_item(
                job_id, item.get("prompt_id"), item.get("comfyui_prompt_id"),
                item.get("images") or [], item.get("prompt_preview", ""),
                item.get("prompt_params"),
            )

        GenJob.update(
            status=snapshot["status"],
            done_count=snapshot["done_count"],
            error_count=snapshot["error_count"],
            items=json.dumps(snapshot["items"], ensure_ascii=False),
            updated_at=datetime.now(),
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
            updated_at=datetime.now(),
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
    """兼容旧 /api/batch_stop：取消所有进行中的任务。"""
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
    for job_id in ids:
        try:
            refresh_job(job_id)
        except Exception:
            logger.exception("刷新任务 %s 失败", job_id)
    return len(ids)


def writer_loop(stop_event: threading.Event, interval: float = 1.0,
                sync_interval: float = 30.0) -> None:
    """后台唯一写者：推进活跃任务 + 定期同步 ComfyUI 历史。

    这是一个普通线程，不是 async task —— 旧的 job_monitor_loop 在事件循环里
    跑同步 HTTP/DB，ComfyUI 一慢就会阻塞所有请求。
    """
    logger.info("任务写者线程已启动（interval=%.1fs, sync=%.0fs）", interval, sync_interval)
    last_sync = 0.0
    while not stop_event.is_set():
        try:
            refresh_active_jobs()
        except Exception:
            logger.exception("刷新活跃任务失败")

        now = time.monotonic()
        if now - last_sync >= sync_interval:
            last_sync = now
            try:
                from routers.history import _sync_comfyui_history, _sync_disk_orphans

                _sync_comfyui_history()
                _sync_disk_orphans()
            except Exception:
                logger.exception("同步 ComfyUI 历史失败")

        stop_event.wait(interval)
    logger.info("任务写者线程已停止")
