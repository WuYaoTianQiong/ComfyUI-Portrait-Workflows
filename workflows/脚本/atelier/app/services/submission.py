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
from app.services.comfyui_client import delete_queue_items, get_queue, interrupt, push_prompt

logger = logging.getLogger("atelier.submit")


class SubmitContractError(ValueError):
    """提交参数违反服务契约；路由层统一映射成 400，而不是 500。"""


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


def _item_cancelled(snapshot: dict | None, index: int) -> bool:
    if not snapshot:
        return True
    items = snapshot.get("items") or []
    if index < 0 or index >= len(items):
        return True
    return items[index].get("status") == "cancelled"


def _abort_prompt(pid: str) -> None:
    """取消发生在 push 期间时，把它已经从 ComfyUI 换来的任务再撤掉。

    只对确认属于该 pid 的队列项动手；interrupt 前先确认它确实在 running，
    避免误杀同一时刻的其它任务。
    """
    try:
        qdata = get_queue() or {}
        running = {
            str(e[1]) for e in qdata.get("queue_running", [])
            if isinstance(e, list) and len(e) > 1
        }
        pending = {
            str(e[1]) for e in qdata.get("queue_pending", [])
            if isinstance(e, list) and len(e) > 1
        }
        if pid in pending:
            delete_queue_items([pid])
        elif pid in running:
            interrupt()
        else:
            # 可能尚未出现在队列、也可能已经结束；删除是幂等的，不再额外 interrupt。
            delete_queue_items([pid])
    except Exception:
        logger.exception("撤掉已取消条目的 ComfyUI 任务失败: %s", pid)


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
            snapshot = job_state.update_job_item(task.job_id, index, {
                "comfyui_prompt_id": pid,
                "status": "submitted",
            })
            # 取消与 push 并发：用户可能刚好在这几毫秒里点了取消，此时 pid
            # 还没落库，cancel_job 找不到它。push 后必须再确认一次并主动撤回。
            if _item_cancelled(snapshot, index):
                _abort_prompt(pid)
                continue
        except Exception as e:
            logger.exception("提交任务 %s 第 %s 条失败", task.job_id, index)
            job_state.update_job_item(task.job_id, index, {
                "status": "error",
                "error": str(e),
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
