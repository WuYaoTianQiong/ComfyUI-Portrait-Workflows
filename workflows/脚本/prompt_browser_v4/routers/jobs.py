"""任务管理 —— 创建 / 查询 / 状态快照 / 取消"""
import json
import traceback
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from models import GenJob, GenHistory
from services.comfyui_client import (
    get_queue, get_history, get_progress, interrupt, clear_queue,
)
from services.helpers import build_view_url
from state import batch_stop_flag

router = APIRouter(tags=["任务"])


# ---------- Helpers ----------

def _row_to_dict(r) -> dict:
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


def create_job(
    job_type: str, title: str, items: list[dict],
    workflow_path: str, orientation: str,
    quality: str, extra: dict | None = None,
) -> int:
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
    return r.id


def update_job_items(job_id: int, items: list[dict], status: str | None = None):
    done = sum(1 for i in items if i.get("status") == "done")
    errors = sum(1 for i in items if i.get("status") in ("error", "cancelled"))
    GenJob.update(
        status=status or "running",
        done_count=done,
        error_count=errors,
        items=json.dumps(items, ensure_ascii=False),
        updated_at=datetime.now(),
    ).where(GenJob.id == job_id).execute()


def get_job_status_snapshot(job: dict) -> dict:
    """根据 ComfyUI queue/history 计算任务实时状态"""
    items = json.loads(job.get("items") or "[]")
    if isinstance(items, str):
        items = json.loads(items)  # double parse safety

    qdata = get_queue()
    running: set[str] = set()
    pending: set[str] = set()
    if qdata:
        for item in qdata.get("queue_running", []):
            if isinstance(item, list) and len(item) > 1:
                running.add(str(item[1]))
        for item in qdata.get("queue_pending", []):
            if isinstance(item, list) and len(item) > 1:
                pending.add(str(item[1]))

    hist = get_history()
    progress_data: dict | None = None
    current_pid: str | None = None
    if qdata and qdata.get("queue_running"):
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

    per_item = []
    done_count = 0
    error_count = 0

    for item in items:
        pid = item.get("comfyui_prompt_id")
        status = item.get("status", "pending")
        iprogress = None

        if pid and pid in hist:
            status = "done"
            images = []
            for node_out in hist[pid].get("outputs", {}).values():
                for img in node_out.get("images", []):
                    images.append(img)
            item["images"] = images
            done_count += 1

            # 写入历史表
            _insert_history_for_item(job["id"], item.get("prompt_id"), pid, images, item.get("prompt_preview", ""))

        elif pid and pid in running:
            status = "running"
            if pid == current_pid and progress_data:
                iprogress = progress_data
        elif pid and pid in pending:
            status = "pending"
        elif status in ("done", "error", "cancelled"):
            if status == "done":
                done_count += 1
            elif status in ("error", "cancelled"):
                error_count += 1
        else:
            status = "unknown"

        item["status"] = status
        item["progress"] = iprogress
        per_item.append(item)

    # 回写 DB
    overall = job["status"]
    if overall not in ("stopped",):
        if done_count + error_count == len(items):
            overall = "done" if error_count == 0 else "error"
        elif any(i.get("status") == "running" for i in per_item):
            overall = "running"
        elif any(i.get("status") == "pending" for i in per_item):
            overall = "pending"
        else:
            overall = "unknown"

    GenJob.update(
        status=overall,
        done_count=done_count,
        error_count=error_count,
        items=json.dumps(per_item, ensure_ascii=False),
        updated_at=datetime.now(),
    ).where(GenJob.id == job["id"]).execute()

    return {
        "id": job["id"],
        "job_type": job["job_type"],
        "status": overall,
        "title": job["title"],
        "total": len(items),
        "done_count": done_count,
        "error_count": error_count,
        "items": per_item,
        "workflow_path": job["workflow_path"],
        "orientation": job["orientation"],
        "quality": job["quality"],
        "created_at": job["created_at"],
        "updated_at": job.get("updated_at"),
    }


def _insert_history_for_item(job_id, prompt_id, comfy_pid, images, preview=""):
    """将生成结果写入历史表"""
    for img in images:
        try:
            GenHistory.insert(
                job_id=job_id, prompt_id=prompt_id,
                comfyui_prompt_id=comfy_pid,
                filename=img["filename"],
                subfolder=img.get("subfolder", ""),
                img_type=img.get("type", "output"),
                view_url=build_view_url(
                    img["filename"],
                    img.get("subfolder", ""),
                    img.get("type", "output"),
                ),
                preview=preview,
                source="local",
            ).on_conflict_ignore().execute()
        except Exception:
            traceback.print_exc()


# ---------- Routes ----------

@router.get("/jobs")
def list_jobs(active: bool = Query(False), limit: int = Query(50)):
    query = GenJob.select()
    if active:
        query = query.where(GenJob.status.in_(["pending", "running"]))
    rows = query.order_by(GenJob.id.desc()).limit(limit)
    return {"jobs": [_row_to_dict(r) for r in rows]}


@router.get("/jobs/{job_id}")
def get_job_detail(job_id: int):
    job = GenJob.get_or_none(GenJob.id == job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    return get_job_status_snapshot(_row_to_dict(job))


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int):
    job = GenJob.get_or_none(GenJob.id == job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")

    interrupt()
    clear_queue()
    batch_stop_flag.set()

    items = json.loads(job.items or "[]")
    if isinstance(items, str):
        items = json.loads(items)
    for item in items:
        if item.get("status") not in ("done",):
            item["status"] = "cancelled"
            item["error"] = "已取消"

    update_job_items(job_id, items, status="stopped")
    return {"success": True, "job_id": job_id}


@router.post("/batch_stop")
def batch_stop():
    """兼容旧接口：停止所有进行中的批量任务"""
    batch_stop_flag.set()
    interrupt()
    clear_queue()
    return {"success": True}


@router.get("/progress")
def check_progress(prompt_id: str = Query("")):
    """查询单个 prompt 的完成状态"""
    if not prompt_id:
        raise HTTPException(400, "缺少 prompt_id")

    try:
        from services.comfyui_client import get_history_for_prompt
        hist = get_history_for_prompt(prompt_id)
        done = False
        images = []
        if hist and prompt_id in hist:
            done = True
            for node_out in hist[prompt_id].get("outputs", {}).values():
                for img in node_out.get("images", []):
                    images.append(img)
        return {"done": done, "images": images, "status": "done" if done else "unknown"}
    except Exception as e:
        raise HTTPException(500, str(e))
