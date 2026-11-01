"""任务管理 —— 创建 / 查询 / 取消 / 事件流。

B2 之后本文件只做"薄路由"：
- GET 一律只读，不再访问 ComfyUI、不再写库（旧实现每次 GET 都会反推状态并落库）；
- 状态推进由 `services.job_state.writer_loop` 单写者负责；
- 取消只影响本任务（旧实现 interrupt + clear_queue 会误伤别的任务）。
"""

import json
import queue

from fastapi import APIRouter, HTTPException, Query
from app.schemas import JobListResponse
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services import job_state
from app.services.comfyui_client import get_history_for_prompt

router = APIRouter(tags=["任务"])

# 兼容旧引用：comfyui.py / composer.py / editor.py / images.py 都从本模块导入
create_job = job_state.create_job
update_job_items = job_state.update_job_items
find_job_by_idempotency = job_state.find_job_by_idempotency
build_job_extra = job_state.build_job_extra
_row_to_dict = job_state.row_to_dict


def _is_terminal(job: dict) -> bool:
    return job.get("status") in job_state.TERMINAL


# ---------------------------------------------------------------------------
# 事件流（SSE）—— 必须注册在 /jobs/{job_id} 之前，否则 "events" 会被当成 job_id
# ---------------------------------------------------------------------------

def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/jobs/events")
def job_events(ids: str = Query("", description="逗号分隔的 job id；为空则订阅全部")):
    wanted = {int(x) for x in ids.split(",") if x.strip().lstrip("-").isdigit()}

    def stream():
        q = job_state.subscribe()
        try:
            # 首帧：把当前状态补齐，避免前端连上后还要等下一次刷新
            if wanted:
                for job_id in sorted(wanted):
                    snapshot = job_state.read_snapshot(job_id)
                    if snapshot:
                        yield _sse("snapshot", snapshot)
            yield ": connected\n\n"

            while True:
                try:
                    event = q.get(timeout=15)
                except queue.Empty:
                    yield ": ping\n\n"   # 心跳，防中间层掐连接
                    continue
                job = event.get("job") or {}
                if wanted and job.get("id") not in wanted:
                    continue
                yield _sse("job", job)
                if _is_terminal(job):
                    # 单任务订阅：发完终态就结束；多任务订阅由前端按 id 关闭
                    if len(wanted) == 1:
                        return
        finally:
            job_state.unsubscribe(q)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# 查询（纯读）
# ---------------------------------------------------------------------------

@router.get("/jobs", response_model=JobListResponse)
def list_jobs(active: bool = Query(False), limit: int = Query(50)):
    return {"jobs": job_state.list_snapshots(active=active, limit=limit)}


# ---------------------------------------------------------------------------
# 单条进度查询（保留给旧调用方）
# 必须注册在 /jobs/{job_id} 之前，否则 "progress" 会被当成 job_id 并报 422
# ---------------------------------------------------------------------------

@router.get("/jobs/progress")
def check_progress(prompt_id: str = Query("")):
    if not prompt_id:
        raise HTTPException(400, "缺少 prompt_id")
    try:
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


@router.get("/jobs/{job_id}")
def get_job_detail(job_id: int):
    snapshot = job_state.read_snapshot(job_id)
    if snapshot is None:
        raise HTTPException(404, "任务不存在")
    return snapshot


# ---------------------------------------------------------------------------
# 取消
# ---------------------------------------------------------------------------

@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int):
    if not job_state.cancel_job(job_id):
        raise HTTPException(404, "任务不存在")
    return {"success": True, "job_id": job_id}


class RetryRequest(BaseModel):
    indexes: list[int] | None = None


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: int, data: RetryRequest | None = None):
    """把失败/取消的条目重提成一个新任务；indexes 为空时自动挑失败项。"""
    from app.services.job_retry import RetryError, retry_job as run_retry

    try:
        return run_retry(job_id, data.indexes if data else None)
    except KeyError:
        raise HTTPException(404, "任务不存在")
    except RetryError as e:
        raise HTTPException(400, str(e))


@router.post("/jobs/stop_all")
def stop_all_jobs():
    """停止所有进行中的任务（定向取消，不再 clear 整个队列）。"""
    stopped = job_state.stop_all()
    return {"success": True, "stopped": stopped}
