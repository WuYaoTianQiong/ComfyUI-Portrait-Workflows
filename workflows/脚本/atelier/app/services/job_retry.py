"""失败 / 取消条目的重试。

不重新调用原路由，而是从 `gen_jobs.items` + `gen_jobs.extra` 复原提交参数：
- 提示词类任务：优先用 item.prompt_params（新任务已完整落盘），旧任务回退提示词库；
- 换脸/编辑：用 item.inputs 里的节点 id 与素材 meta 重新注入 LoadImage（含遮罩合成）；
- 图片处理：用 prompt_params.input_image 从 input 目录重新取图。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.config import settings
from app.models import GenJob, Prompt
from app.services import job_state
from app.services.generation import SubmitSpec, submit_spec
from app.services.image_inputs import clean_dest_name, compose_masked_target, dest_name
from app.services.output_location import (
    OutputLocationError,
    expand_subfolder,
    with_subfolder,
)
from app.services.paths import resolve_image_path
from app.services.workflow_parser import (
    inject_input_image,
    inject_prompt,
    load_workflow,
    resolve_seed,
    set_output_prefix,
    set_save_subfolder,
)

RETRY_STATUSES = {"error", "cancelled", "stopped"}


class RetryError(ValueError):
    """任务当前状态无法重试（没有失败项、参数缺失等）。"""


def _extra(job: dict) -> dict:
    extra = job.get("extra")
    if isinstance(extra, dict):
        return extra
    if isinstance(extra, str) and extra:
        try:
            return json.loads(extra)
        except (TypeError, ValueError):
            return {}
    return {}


def _prompt_params(item: dict) -> dict:
    raw = item.get("prompt_params")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return {}
    return {}


def _safe_part(text: str, max_len: int = 24) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text or "").strip(" .")
    return cleaned[:max_len] or "retry"


def _resolve_meta_path(meta: dict) -> Path | None:
    if meta.get("source") == "history":
        return resolve_image_path(
            meta.get("filename", ""),
            meta.get("subfolder", "") or "",
            meta.get("img_type", "output"),
        )
    raw = meta.get("path")
    if raw:
        path = Path(raw)
        try:
            return path if path.is_file() else None
        except OSError:
            return None
    return None


def _build_prompt_workflow(job: dict, item: dict, new_job_id: int, subfolder: str) -> dict:
    extra = _extra(job)
    workflow_path = item.get("workflow_path") or job.get("workflow_path", "")
    item_content = item.get("workflow_content")
    workflow_content = item_content if item_content is not None else extra.get("workflow_content")
    api_wf = load_workflow(workflow_path, workflow_content)
    pp = _prompt_params(item)

    injected = pp.get("injected_prompt")
    raw_prompt = pp.get("prompt")
    # 优先用原文重编译：批次记录里的 injected_prompt 是剥离标题后的快照，
    # 用它重试会丢掉【避免】段；原文不在时再退回快照。
    prompt_text = (
        raw_prompt
        if isinstance(raw_prompt, str) and raw_prompt
        else injected
    )
    negative = pp.get("negative_prompt", "")
    steps = pp.get("steps")
    cfg_scale = pp.get("cfg_scale")
    sampler = pp.get("sampler")
    raw_seed = item.get("seed") or pp.get("seed")

    if prompt_text is None:
        prompt_id = item.get("prompt_id")
        prompt = Prompt.get_or_none(Prompt.id == prompt_id) if prompt_id else None
        if prompt is None:
            raise RetryError("该条目没有可复用的提示词（原提示词已删除，且未保存 prompt_params）")
        prompt_text = prompt.prompt or ""
        negative = negative or prompt.negative_prompt or ""
        steps = prompt.steps if steps is None else steps
        cfg_scale = prompt.cfg_scale if cfg_scale is None else cfg_scale
        sampler = sampler or prompt.sampler
        raw_seed = raw_seed or prompt.seed

    prompt_text = prompt_text or ""
    seed = resolve_seed(raw_seed)

    inject_prompt(api_wf, {
        "prompt": prompt_text,
        "strip_fragment_headers": True,
        "negative_prompt": negative or "",
        "seed": seed,
        "steps": steps,
        "cfg_scale": cfg_scale,
        "sampler": sampler or "",
        "orientation": item.get("orientation") or job.get("orientation", "portrait"),
        "quality": item.get("quality") or job.get("quality", "1.0x"),
        "aspect_ratio": item.get("aspect_ratio") or extra.get("aspect_ratio", ""),
    })

    input_image = pp.get("input_image")
    if input_image:
        source = settings.input_dir / str(input_image)
        if not source.is_file():
            raise RetryError(f"原始输入图已不在 input 目录: {input_image}")
        inject_input_image(api_wf, str(source), str(settings.input_dir), dest_name=source.name)

    return api_wf


def _build_faceswap_workflow(job: dict, item: dict, new_job_id: int, subfolder: str) -> dict:
    extra = _extra(job)
    workflow_path = item.get("workflow_path") or job.get("workflow_path", "")
    item_content = item.get("workflow_content")
    workflow_content = item_content if item_content is not None else extra.get("workflow_content")
    api_wf = load_workflow(workflow_path, workflow_content)
    pp = _prompt_params(item)
    seed = resolve_seed(item.get("seed"), pp.get("seed"))

    inject_prompt(api_wf, {
        "prompt": pp.get("prompt", ""),
        "negative_prompt": pp.get("negative_prompt", ""),
        "seed": seed,
        "orientation": item.get("orientation") or job.get("orientation", "portrait"),
        "quality": item.get("quality") or job.get("quality", "1.0x"),
        "aspect_ratio": item.get("aspect_ratio") or extra.get("aspect_ratio", ""),
    })

    inputs = item.get("inputs") or []
    if not inputs:
        raise RetryError("换脸任务缺少节点映射，无法重试")
    for inp in inputs:
        meta = inp.get("meta") or {}
        source = _resolve_meta_path(meta)
        if source is None:
            raise RetryError(f"素材文件不存在: {meta.get('filename') or meta.get('path') or '未知'}")
        dest = dest_name({"path": str(source), "name": source.name})
        # 批量超分任务保留原文件名；重试沿用同一份 input 子目录，成品名不变
        if meta.get("keep_source_name"):
            dest = clean_dest_name({"path": str(source), "name": source.name})
        mask = meta.get("mask")
        if mask:
            mask_path = Path(mask)
            if not mask_path.is_file():
                raise RetryError(f"遮罩文件不存在: {mask}")
            source = compose_masked_target(source, mask_path, settings.input_dir)
            dest = dest_name({"path": str(source), "name": source.name})
        inject_input_image(
            api_wf, str(source), str(settings.input_dir),
            node_id=str(inp.get("node")) if inp.get("node") else None,
            dest_name=dest,
        )

    prefix = with_subfolder(
        subfolder, f"retry{new_job_id}_{_safe_part(item.get('prompt_preview', ''))}"
    )
    set_output_prefix(api_wf, prefix)
    set_save_subfolder(api_wf, subfolder)
    return api_wf


def retry_job(
    job_id: int,
    indexes: list[int] | None = None,
    idempotency_key: str = "",
) -> dict:
    """把失败 / 取消的条目提交成一个新任务，返回新 job_id。"""
    row = GenJob.get_or_none(GenJob.id == job_id)
    if row is None:
        raise KeyError(job_id)
    job = job_state.normalize(job_state.row_to_dict(row))
    extra = _extra(job)
    workflow_path = job.get("workflow_path", "")

    if str(workflow_path).startswith("custom://") and not extra.get("workflow_content"):
        raise RetryError("自定义工作流内容未保存，无法自动重试")

    items = job.get("items") or []
    if indexes:
        candidates = [(i, items[i]) for i in indexes if 0 <= i < len(items)]
    else:
        candidates = [
            (i, item) for i, item in enumerate(items)
            if item.get("status") in RETRY_STATUSES
        ]
    if not candidates:
        raise RetryError("没有失败或取消的条目")

    idx_token = ",".join(str(i) for i, _ in candidates)
    # 稳定键：同一批失败条目重复点击只建一个任务。
    # 想再次重试同一批时，调用方传新的 X-Idempotency-Key 即可（见 routers/jobs.py）。
    key = idempotency_key.strip() or f"retry:{job_id}:{idx_token}"
    existing = job_state.find_job_by_idempotency(key, "retry")
    if existing is not None:
        return {
            "success": True, "job_id": existing["id"], "submitted": 0,
            "total": existing["total"], "errors": [], "idempotent": True,
        }

    subfolder_template = extra.get("output_subfolder", "")
    try:
        expand_subfolder(
            subfolder_template, workflow_path=workflow_path, job_id=0,
            quality=job.get("quality", "1.0x"), orientation=job.get("orientation", "portrait"),
        )
    except OutputLocationError as e:
        raise RetryError(str(e))

    new_items: list[dict] = []
    for _, old in candidates:
        item = dict(old)
        item["status"] = "queued"
        item["comfyui_prompt_id"] = ""
        item.pop("error", None)
        item.pop("progress", None)
        item["images"] = []
        new_items.append(item)

    new_extra = dict(extra)
    new_extra.update({
        "retry_of": job_id,
        "idempotency_key": key,
        "idempotency_scope": "retry",
    })
    is_faceswap = job.get("job_type") == "faceswap"

    def prepare(n: int, ctx) -> dict:
        old_item = candidates[n][1]
        if is_faceswap:
            return _build_faceswap_workflow(job, old_item, ctx.job_id, ctx.subfolder)
        return _build_prompt_workflow(job, old_item, ctx.job_id, ctx.subfolder)

    outcome = submit_spec(SubmitSpec(
        job_type=job.get("job_type", "batch"),
        title=f"重试: {job.get('title', '')}",
        items=new_items,
        workflow_path=workflow_path,
        workflow_content=new_extra.get("workflow_content"),
        orientation=job.get("orientation", "portrait"),
        quality=job.get("quality", "1.0x"),
        aspect_ratio=new_extra.get("aspect_ratio", ""),
        output_subfolder=subfolder_template,
        prepare=prepare,
        mode="queue",
        indexes=tuple(range(len(candidates))),
        extra=new_extra,
        apply_output=not is_faceswap,
    ))
    return {
        "success": True,
        "job_id": outcome["job_id"],
        "submitted": 0,
        "queued": outcome["queued"],
        "total": len(candidates),
        "errors": [],
        "idempotent": False,
        "async": True,
    }
