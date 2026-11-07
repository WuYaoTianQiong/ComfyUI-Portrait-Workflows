"""统一出图提交入口：建 job → 展开输出子目录 → 同步推送或入队。

各路由只负责「这条任务要提交什么」（提示词、图片、参数），
「怎么建任务、怎么命名目录、什么时候推送/入队」全部收敛到这里。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.routers.jobs import build_job_extra, create_job, update_job_items
from app.services.comfyui_client import push_prompt
from app.services.output_location import apply_output_subfolder, expand_subfolder
from app.services.submission import SubmitTask, enqueue_submission


@dataclass(frozen=True)
class SubmitContext:
    """prepare 回调可读的上下文；同步模式下 job_id/subfolder 尚未生成，统一为空。"""

    job_id: int
    subfolder: str


Prepare = Callable[[int, SubmitContext], dict]


def submit_generation(
    *,
    job_type: str,
    title: str,
    items: list[dict],
    workflow_path: str,
    workflow_content: str | None = None,
    orientation: str = "portrait",
    quality: str = "4K",
    aspect_ratio: str = "",
    output_subfolder: str = "",
    prepare: Prepare,
    mode: str = "sync",
    indexes: list[int] | None = None,
    extra: dict | None = None,
    apply_output: bool = True,
) -> dict:
    """提交一批出图条目。

    - `prepare(index, ctx)` 返回「已注入、待推送」的工作流；可以在这里加图片/遮罩/前缀。
    - `mode="sync"`：先 prepare 再建 job（注入失败不会留下空任务），随后 push 并回写 item。
    - `mode="queue"`：先建 job 再入队，prepare 在后台线程执行；此时 ctx 带真实 job_id/子目录。
    - `apply_output=False`：由 prepare 自己决定保存前缀/子目录（编辑器链路）。
    """
    indexes = list(indexes if indexes is not None else [0])
    extra = extra if extra is not None else build_job_extra(
        workflow_path, workflow_content, output_subfolder, aspect_ratio=aspect_ratio,
    )

    if mode == "sync":
        api_wf = prepare(indexes[0], SubmitContext(0, ""))
        job_id = create_job(
            job_type, title, items, workflow_path, orientation, quality, extra=extra,
        )
        subfolder = expand_subfolder(
            output_subfolder, workflow_path=workflow_path, job_id=job_id,
            quality=quality, orientation=orientation,
        )
        if apply_output:
            apply_output_subfolder(api_wf, subfolder)
        try:
            result = push_prompt(api_wf)
        except Exception:
            update_job_items(job_id, items, status="error")
            raise
        items[0]["comfyui_prompt_id"] = result.get("prompt_id", "")
        items[0]["status"] = "pending"
        update_job_items(job_id, items, status="running")
        return {"job_id": job_id, "subfolder": subfolder, "result": result}

    if mode != "queue":
        raise ValueError(f"未知提交模式: {mode}")

    job_id = create_job(
        job_type, title, items, workflow_path, orientation, quality, extra=extra,
    )
    subfolder = expand_subfolder(
        output_subfolder, workflow_path=workflow_path, job_id=job_id,
        quality=quality, orientation=orientation,
    )

    def run(index: int) -> dict:
        api_wf = prepare(index, SubmitContext(job_id, subfolder))
        if apply_output:
            apply_output_subfolder(api_wf, subfolder)
        return api_wf

    update_job_items(job_id, items, status="running" if indexes else "error")
    if indexes:
        enqueue_submission(SubmitTask(job_id, indexes, run))
    return {"job_id": job_id, "subfolder": subfolder, "queued": len(indexes)}
