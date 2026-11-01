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
from app.services.comfyui_client import push_prompt
from app.services.fragment_syntax import strip_headers
from app.services.image_inputs import compose_masked_target, dest_name
from app.services.output_location import (
    OutputLocationError,
    apply_output_subfolder,
    expand_subfolder,
    with_subfolder,
)
from app.services.paths import resolve_image_path
from app.services.workflow_parser import (
    inject_input_image,
    inject_prompt,
    load_workflow,
    set_output_prefix,
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
    api_wf = load_workflow(job.get("workflow_path", ""), extra.get("workflow_content"))
    pp = _prompt_params(item)

    injected = pp.get("injected_prompt")
    prompt_text = injected if injected is not None else pp.get("prompt")
    negative = pp.get("negative_prompt", "")
    steps = pp.get("steps")
    cfg_scale = pp.get("cfg_scale")
    sampler = pp.get("sampler")
    seed = int(item.get("seed") or pp.get("seed") or 0)

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
        seed = seed or int(prompt.seed or 0)

    prompt_text = prompt_text or ""
    if injected is None:
        injected = strip_headers(prompt_text)

    inject_prompt(api_wf, {
        "prompt": injected,
        "negative_prompt": negative or "",
        "seed": seed,
        "seed_override": seed,
        "steps": steps,
        "cfg_scale": cfg_scale,
        "sampler": sampler or "",
        "orientation": job.get("orientation", "portrait"),
        "quality": job.get("quality", "4K"),
    })

    input_image = pp.get("input_image")
    if input_image:
        source = settings.input_dir / str(input_image)
        if not source.is_file():
            raise RetryError(f"原始输入图已不在 input 目录: {input_image}")
        inject_input_image(api_wf, str(source), str(settings.input_dir), dest_name=source.name)

    apply_output_subfolder(api_wf, subfolder)
    return api_wf


def _build_faceswap_workflow(job: dict, item: dict, new_job_id: int, subfolder: str) -> dict:
    extra = _extra(job)
    api_wf = load_workflow(job.get("workflow_path", ""), extra.get("workflow_content"))
    pp = _prompt_params(item)
    seed = int(item.get("seed") or pp.get("seed") or 0)

    inject_prompt(api_wf, {
        "prompt": pp.get("prompt", ""),
        "negative_prompt": pp.get("negative_prompt", ""),
        "seed": seed,
        "seed_override": seed,
        "orientation": job.get("orientation", "portrait"),
        "quality": job.get("quality", "4K"),
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
    return api_wf


def retry_job(job_id: int, indexes: list[int] | None = None) -> dict:
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
    key = f"retry:{job_id}:{idx_token}:{job.get('updated_at', '')}"
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
            quality=job.get("quality", "4K"), orientation=job.get("orientation", "portrait"),
        )
    except OutputLocationError as e:
        raise RetryError(str(e))

    new_items: list[dict] = []
    for _, old in candidates:
        item = dict(old)
        item["status"] = "pending"
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
    new_job_id = job_state.create_job(
        job.get("job_type", "batch"),
        f"重试: {job.get('title', '')}",
        new_items,
        workflow_path,
        job.get("orientation", "portrait"),
        job.get("quality", "4K"),
        extra=new_extra,
    )
    subfolder = expand_subfolder(
        subfolder_template, workflow_path=workflow_path, job_id=new_job_id,
        quality=job.get("quality", "4K"), orientation=job.get("orientation", "portrait"),
    )

    ok = 0
    errors: list[dict] = []
    for n, (old_idx, old_item) in enumerate(candidates):
        try:
            if job.get("job_type") == "faceswap":
                api_wf = _build_faceswap_workflow(job, old_item, new_job_id, subfolder)
            else:
                api_wf = _build_prompt_workflow(job, old_item, new_job_id, subfolder)
            result = push_prompt(api_wf)
            new_items[n]["comfyui_prompt_id"] = result.get("prompt_id", "")
            new_items[n]["status"] = "pending"
            ok += 1
        except Exception as e:
            new_items[n]["status"] = "error"
            new_items[n]["error"] = str(e)
            errors.append({"index": old_idx, "error": str(e)})

    job_state.update_job_items(new_job_id, new_items, status="running" if ok else "error")
    return {
        "success": ok > 0,
        "job_id": new_job_id,
        "submitted": ok,
        "total": len(candidates),
        "errors": errors,
        "idempotent": False,
    }
