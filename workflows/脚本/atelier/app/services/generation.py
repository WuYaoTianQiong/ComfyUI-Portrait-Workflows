"""统一出图提交入口：建 job → 展开输出子目录 → 同步推送或入队。

各路由只负责「这条任务要提交什么」（提示词、图片、参数），
「怎么建任务、怎么命名目录、什么时候推送/入队」全部收敛到这里。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from peewee import IntegrityError

from app.routers.jobs import (
    build_job_extra,
    create_job,
    find_job_by_idempotency,
    update_job_items,
)
from app.services.comfyui_client import push_prompt
from app.services.output_location import apply_output_subfolder, expand_subfolder
from app.services.submission import SubmitContractError, SubmitTask, enqueue_submission


@dataclass(frozen=True)
class SubmitContext:
    """prepare 回调可读的上下文；同步模式下 job_id/subfolder 尚未生成，统一为空。

    item 级字段（workflow/quality/orientation/...）优先于 job 级默认值，
    这样同一个 job 可以包含不同工作流的条目。
    """

    job_id: int = 0
    subfolder: str = ""
    index: int = 0
    item: dict = field(default_factory=dict)
    workflow_path: str = ""
    workflow_content: str | None = None
    quality: str = ""
    orientation: str = ""
    aspect_ratio: str = ""
    output_subfolder: str = ""


Prepare = Callable[[int, SubmitContext], dict]


def _context(
    index: int, job_id: int, subfolder: str, items: list[dict], *,
    workflow_path: str, workflow_content: str | None,
    quality: str, orientation: str, aspect_ratio: str, output_subfolder: str,
) -> SubmitContext:
    item = items[index] if 0 <= index < len(items) else {}
    item_content = item.get("workflow_content")
    return SubmitContext(
        job_id=job_id,
        subfolder=subfolder,
        index=index,
        item=item,
        workflow_path=str(item.get("workflow_path") or workflow_path or ""),
        workflow_content=item_content if item_content is not None else workflow_content,
        quality=str(item.get("quality") or quality or ""),
        orientation=str(item.get("orientation") or orientation or ""),
        aspect_ratio=str(item.get("aspect_ratio") or aspect_ratio or ""),
        output_subfolder=str(item.get("output_subfolder") or output_subfolder or ""),
    )


def _existing_idempotent(extra: dict | None) -> dict | None:
    """唯一索引冲突时找回已存在的任务；没有键或查不到就返回 None。"""
    key = (extra or {}).get("idempotency_key")
    scope = (extra or {}).get("idempotency_scope")
    if not key or not scope:
        return None
    return find_job_by_idempotency(str(key), str(scope))


@dataclass(frozen=True)
class SubmitSpec:
    """一次提交的不可变规格；路由只负责把请求映射成它。

    - `prepare(index, ctx)` 返回「已注入、待推送」的工作流；可以在这里加图片/遮罩/前缀。
    - `mode="sync"`：先 prepare 再建 job（注入失败不会留下空任务），随后 push 并回写 item。
    - `mode="queue"`：先建 job 再入队，prepare 在后台线程执行；此时 ctx 带真实 job_id/子目录。
    - `apply_output=False`：由 prepare 自己决定保存前缀/子目录（编辑器链路）。
    """

    job_type: str
    title: str
    items: list[dict]
    workflow_path: str
    prepare: Prepare
    workflow_content: str | None = None
    orientation: str = "portrait"
    quality: str = "1.0x"
    aspect_ratio: str = ""
    output_subfolder: str = ""
    mode: str = "sync"
    indexes: tuple[int, ...] | None = None
    extra: dict | None = None
    apply_output: bool = True


def submit_spec(spec: SubmitSpec) -> dict:
    """执行 SubmitSpec；这是所有出图入口的唯一服务实现。"""
    if not spec.items:
        raise SubmitContractError("items 不能为空")
    if spec.mode not in ("sync", "queue"):
        raise ValueError(f"未知提交模式: {spec.mode}")
    indexes = list(spec.indexes if spec.indexes is not None else (0,))
    if spec.mode == "sync" and len(indexes) != 1:
        # sync 的返回契约只有一条 result；多条目必须走 queue，否则后续条目会被静默丢弃。
        raise SubmitContractError("sync 模式一次只能提交一个条目；多条目请使用 queue 模式")

    workflow_path = spec.workflow_path
    workflow_content = spec.workflow_content
    output_subfolder = spec.output_subfolder
    quality = spec.quality
    orientation = spec.orientation
    aspect_ratio = spec.aspect_ratio
    extra = spec.extra if spec.extra is not None else build_job_extra(
        workflow_path, workflow_content, output_subfolder, aspect_ratio=aspect_ratio,
    )

    if spec.mode == "sync":
        index = indexes[0]
        api_wf = spec.prepare(index, _context(
            index, 0, "", spec.items,
            workflow_path=workflow_path, workflow_content=workflow_content,
            quality=quality, orientation=orientation,
            aspect_ratio=aspect_ratio, output_subfolder=output_subfolder,
        ))
        try:
            job_id = create_job(
                spec.job_type, spec.title, spec.items, workflow_path,
                orientation, quality, extra=extra,
            )
        except IntegrityError:
            existing = _existing_idempotent(extra)
            if existing is None:
                raise
            return {
                "job_id": existing["id"], "subfolder": "", "result": {},
                "idempotent": True,
            }
        subfolder = expand_subfolder(
            output_subfolder, workflow_path=workflow_path, job_id=job_id,
            quality=quality, orientation=orientation,
        )
        if spec.apply_output:
            apply_output_subfolder(api_wf, subfolder)
        try:
            result = push_prompt(api_wf)
        except Exception as exc:
            for item in spec.items:
                item["status"] = "error"
                item["error"] = item.get("error") or str(exc) or "提交失败"
            update_job_items(job_id, spec.items, status="error")
            raise
        spec.items[0]["comfyui_prompt_id"] = result.get("prompt_id", "")
        spec.items[0]["status"] = "submitted"
        update_job_items(job_id, spec.items, status="running")
        return {"job_id": job_id, "subfolder": subfolder, "result": result}

    try:
        job_id = create_job(
            spec.job_type, spec.title, spec.items, workflow_path,
            orientation, quality, extra=extra,
        )
    except IntegrityError:
        existing = _existing_idempotent(extra)
        if existing is None:
            raise
        return {
            "job_id": existing["id"], "subfolder": "", "queued": 0,
            "idempotent": True,
        }
    subfolder = expand_subfolder(
        output_subfolder, workflow_path=workflow_path, job_id=job_id,
        quality=quality, orientation=orientation,
    )

    def run(index: int) -> dict:
        api_wf = spec.prepare(index, _context(
            index, job_id, subfolder, spec.items,
            workflow_path=workflow_path, workflow_content=workflow_content,
            quality=quality, orientation=orientation,
            aspect_ratio=aspect_ratio, output_subfolder=output_subfolder,
        ))
        if spec.apply_output:
            apply_output_subfolder(api_wf, subfolder)
        return api_wf

    update_job_items(job_id, spec.items, status="running" if indexes else "error")
    if indexes:
        enqueue_submission(SubmitTask(job_id, indexes, run))
    return {"job_id": job_id, "subfolder": subfolder, "queued": len(indexes)}


def submit_generation(
    *,
    job_type: str,
    title: str,
    items: list[dict],
    workflow_path: str,
    prepare: Prepare,
    workflow_content: str | None = None,
    orientation: str = "portrait",
    quality: str = "1.0x",
    aspect_ratio: str = "",
    output_subfolder: str = "",
    mode: str = "sync",
    indexes: list[int] | None = None,
    extra: dict | None = None,
    apply_output: bool = True,
) -> dict:
    """兼容旧调用的薄包装；新代码直接构造 SubmitSpec 并调用 submit_spec。"""
    return submit_spec(SubmitSpec(
        job_type=job_type, title=title, items=items,
        workflow_path=workflow_path, prepare=prepare,
        workflow_content=workflow_content, orientation=orientation,
        quality=quality, aspect_ratio=aspect_ratio,
        output_subfolder=output_subfolder, mode=mode,
        indexes=tuple(indexes) if indexes is not None else None,
        extra=extra, apply_output=apply_output,
    ))
