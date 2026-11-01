"""批量提交后台队列。

批量接口只负责建任务、把「如何构造这一条 workflow」的函数入队，立即返回 job_id；
真正的 load_workflow / 注入 / push_prompt 在这里串行执行（ComfyUI 本身也是队列）。
"""
from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from typing import Callable

from app.models import GenJob
from app.services import job_state
from app.services.comfyui_client import push_prompt

logger = logging.getLogger("atelier.submit")


@dataclass(frozen=True)
class SubmitTask:
    job_id: int
    indexes: list[int]
    prepare: Callable[[int], dict]


_queue: queue.Queue[SubmitTask | None] = queue.Queue()
_worker: threading.Thread | None = None
_start_lock = threading.Lock()


def start_submit_worker() -> None:
    global _worker
    with _start_lock:
        if _worker is not None and _worker.is_alive():
            return
        _worker = threading.Thread(target=_loop, daemon=True, name="job-submitter")
        _worker.start()
        logger.info("批量提交线程已启动")


def stop_submit_worker() -> None:
    global _worker
    with _start_lock:
        worker = _worker
        _worker = None
    if worker is None:
        return
    _queue.put(None)
    worker.join(timeout=5)


def enqueue_submission(task: SubmitTask) -> None:
    start_submit_worker()
    _queue.put(task)


def submit_task(task: SubmitTask) -> None:
    """同步处理一个 SubmitTask；测试直接调用它，生产由 worker 调用。"""
    for index in task.indexes:
        row = GenJob.get_or_none(GenJob.id == task.job_id)
        if row is None:
            break
        if row.status in ("stopped", "done", "error"):
            break
        items = job_state.parse_items(row.items)
        if index < 0 or index >= len(items):
            continue
        if items[index].get("status") in ("done", "error", "cancelled", "stopped"):
            continue
        try:
            api_wf = task.prepare(index)
            result = push_prompt(api_wf)
            pid = str(result.get("prompt_id", "") or "")
            if not pid:
                raise RuntimeError("ComfyUI 未返回 prompt_id")
            job_state.update_job_item(task.job_id, index, {
                "comfyui_prompt_id": pid,
                "status": "pending",
                "submit_state": "submitted",
            })
        except Exception as e:
            logger.exception("提交任务 %s 第 %s 条失败", task.job_id, index)
            job_state.update_job_item(task.job_id, index, {
                "status": "error",
                "error": str(e),
                "submit_state": "failed",
            })
    job_state.finish_submission(task.job_id)


def _loop() -> None:
    while True:
        task = _queue.get()
        try:
            if task is None:
                return
            submit_task(task)
        except Exception:
            logger.exception("后台提交任务失败")
            if task is not None:
                job_state.finish_submission(task.job_id)
        finally:
            _queue.task_done()
