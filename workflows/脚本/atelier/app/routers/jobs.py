"""任务管理 —— 创建 / 查询 / 取消 / 事件流。

B2 之后本文件只做"薄路由"：
- GET 一律只读，不再访问 ComfyUI、不再写库（旧实现每次 GET 都会反推状态并落库）；
- 状态推进由 `services.job_state.writer_loop` 单写者负责；
- 取消只影响本任务（旧实现 interrupt + clear_queue 会误伤别的任务）。
"""

import json
import queue

from fastapi import APIRouter, Header, HTTPException, Query
from app.schemas import JobListResponse
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services import job_state

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

def _sse(event: str, payload: dict, event_id: int | None = None) -> str:
    head = f"id: {event_id}\n" if event_id is not None else ""
    return f"{head}event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/jobs/events")
def job_events(
    ids: str = Query("", description="逗号分隔的 job id；为空则订阅全部"),
    since: int | None = Query(None, description="只补发序号大于 since 的事件"),
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
):
    wanted = {int(x) for x in ids.split(",") if x.strip().lstrip("-").isdigit()}
    resume_from = since
    if last_event_id and last_event_id.strip().lstrip("-").isdigit():
        resume_from = int(last_event_id)

    def stream():
        q = job_state.subscribe(since=resume_from)
        try:
            # 首帧：把当前状态补齐，避免前端连上后还要等下一次刷新。
            # 断线重连（带 since / Last-Event-ID）时只补事件，避免“最新快照 → 旧事件”
            # 把客户端状态倒退回去。
            if wanted and resume_from is None:
                terminal_snapshot = False
                for job_id in sorted(wanted):
                    snapshot = job_state.read_snapshot(job_id)
                    if snapshot:
                        yield _sse("snapshot", snapshot)
                        terminal_snapshot = terminal_snapshot or _is_terminal(snapshot)
                if len(wanted) == 1 and terminal_snapshot:
                    return
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
                yield _sse("job", job, event.get("seq"))
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
    snapshot = job_state.read_snapshot(job_id)
    if snapshot is None:
        raise HTTPException(404, "任务不存在")
    if snapshot.get("status") in job_state.TERMINAL:
        raise HTTPException(409, "任务已结束，无法取消")
    if not job_state.cancel_job(job_id):
        raise HTTPException(404, "任务不存在")
    return {"success": True, "job_id": job_id}


class RetryRequest(BaseModel):
    indexes: list[int] | None = None


@router.post("/jobs/{job_id}/retry")
def retry_job(
    job_id: int,
    data: RetryRequest | None = None,
    x_idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
):
    """把失败/取消的条目重提成一个新任务；indexes 为空时自动挑失败项。"""
    from app.services.job_retry import RetryError, retry_job as run_retry

    try:
        return run_retry(job_id, data.indexes if data else None, x_idempotency_key or "")
    except KeyError:
        raise HTTPException(404, "任务不存在")
    except RetryError as e:
        raise HTTPException(400, str(e))


@router.post("/jobs/stop_all")
def stop_all_jobs():
    """停止所有进行中的任务（定向取消，不再 clear 整个队列）。"""
    stopped = job_state.stop_all()
    return {"success": True, "stopped": stopped}
