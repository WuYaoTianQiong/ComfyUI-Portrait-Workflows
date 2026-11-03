"""组合创作 API —— 碎片解析 + 碎片跑图"""
import json
import traceback
import random
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from app.models import Prompt, Category, Tag, PromptCategory, EntityTag, db
from app.services.workflow_parser import load_workflow, inject_prompt
from app.services.comfyui_client import push_prompt
from app.services.output_location import (
    OutputLocationError,
    apply_output_subfolder,
    expand_subfolder,
)
from app.services.submission import SubmitTask, enqueue_submission
from app.routers.jobs import (
    build_job_extra,
    create_job,
    find_job_by_idempotency,
    update_job_items,
)
from app.config import settings
from app.services.fragment_syntax import FRAGMENT_TYPES, parse, strip_headers

router = APIRouter(tags=["组合创作"])


def _get_fragment_data(search="", category_id=None, tag_ids=None, fragment_type=""):
    """获取碎片数据，按类型分组，供随机组合 / 批量替换使用。

    α 之后碎片统一从 prompts 解析（单块 prompt 就是碎片），不再读 fragments 表。
    """
    query = Prompt.select()

    if search:
        query = query.where(
            Prompt.prompt.contains(search)
            | Prompt.name.contains(search)
            | Prompt.tags.contains(search)
            | Prompt.note.contains(search)
        )

    if category_id is not None:
        query = query.join(PromptCategory).where(
            PromptCategory.category == category_id
        )

    if tag_ids:
        tag_id_list = [int(t.strip()) for t in tag_ids.split(",") if t.strip()]
        if tag_id_list:
            query = query.where(
                Prompt.id
                << EntityTag.select(EntityTag.entity_id).where(
                    (EntityTag.entity_type == "prompt")
                    & (EntityTag.tag.in_(tag_id_list))
                )
            )

    rows = list(query.order_by(Prompt.id.desc()))
    keyword = (search or "").strip().lower()

    only = fragment_type if fragment_type in FRAGMENT_TYPES else ""
    grouped = {only: []} if only else {t: [] for t in FRAGMENT_TYPES}
    seen_content = {}

    def content_key(ftype, content):
        return f"{ftype}||{content}"

    for r in rows:
        fragments = parse(r.prompt)
        for f in fragments:
            ftype = f["type"]
            if ftype not in grouped:
                continue
            if keyword and keyword not in (f["content"] or "").lower():
                continue
            ck = content_key(ftype, f["content"])
            if ck in seen_content:
                entry = seen_content[ck]
                entry["dup_count"] = (entry.get("dup_count") or 1) + 1
                src = f"{r.name or ''} (ID:{r.id})"
                if src not in entry.get("source_names", []):
                    entry.setdefault("source_names", []).append(src)
            else:
                entry = {
                    "prompt_id": r.id,
                    "prompt_name": r.name or "",
                    "type": ftype,
                    "content": f["content"],
                    "tags": r.tags or "",
                    "source_preview": (r.prompt or "")[:60],
                    "source": "prompt",
                    "dup_count": 1,
                    "source_names": [f"{r.name or ''} (ID:{r.id})"],
                }
                seen_content[ck] = entry
                grouped[ftype].append(entry)

    return grouped


@router.get("/composer/fragments")
def get_fragments(
    search: str = Query(""),
    category_id: Optional[int] = Query(None),
    tag_ids: Optional[str] = Query(None),
    fragment_type: str = Query(""),
):
    """获取当前筛选提示词范围内的碎片列表，按类型分组"""
    grouped = _get_fragment_data(search, category_id, tag_ids, fragment_type)
    total_fragments = sum(len(v) for v in grouped.values())
    return {
        "grouped": grouped,
        "total_prompts": 0,  # 不再需要，保留兼容
        "fragment_count": total_fragments,
    }


class ComposerRunRequest(BaseModel):
    prompt: str
    negative_prompt: str = ""
    workflow_path: str = ""
    workflow_content: str | None = None
    orientation: str = "portrait"
    quality: str = "4K"
    aspect_ratio: str = ""
    output_subfolder: str = ""


@router.post("/composer/run")
def composer_run(req: ComposerRunRequest):
    """组合提示词直接跑图（不保存到提示词库）"""
    workflow_path = req.workflow_path or ""
    if not workflow_path:
        raise HTTPException(400, "缺少工作流路径")

    try:
        expand_subfolder(
            req.output_subfolder, workflow_path=workflow_path, job_id=0,
            quality=req.quality, orientation=req.orientation,
        )
        api_wf = load_workflow(workflow_path, req.workflow_content)
        # 与 comfyui.py 的各出图入口保持一致：【类型】标题只用于组合器里给人看，
        # 不能作为正文注入 CLIP（否则会多出 8 段中文标签文本）。
        prompt_data = {
            "prompt": strip_headers(req.prompt),
            "negative_prompt": req.negative_prompt,
            "seed": 0,
            "seed_override": 0,
            "orientation": req.orientation,
            "quality": req.quality,
            "aspect_ratio": req.aspect_ratio,
        }
        inject_prompt(api_wf, prompt_data)

        import json
        items = [{
            "prompt_id": 0,
            "seed": 0,
            "prompt_preview": (req.prompt or "")[:120],
            "prompt_params": json.dumps({
                "prompt": req.prompt,
                "negative_prompt": req.negative_prompt,
                "aspect_ratio": req.aspect_ratio,
                "source": "composer",
            }, ensure_ascii=False),
        }]
        job_id = create_job(
            "single", "组合创作", items, workflow_path,
            req.orientation, req.quality,
            extra=build_job_extra(workflow_path, req.workflow_content, req.output_subfolder,
                            aspect_ratio=req.aspect_ratio),
        )

        subfolder = expand_subfolder(
            req.output_subfolder, workflow_path=workflow_path, job_id=job_id,
            quality=req.quality, orientation=req.orientation,
        )
        apply_output_subfolder(api_wf, subfolder)
        result = push_prompt(api_wf)
        comfy_pid = result.get("prompt_id", "")
        items[0]["comfyui_prompt_id"] = comfy_pid
        items[0]["status"] = "pending"
        update_job_items(job_id, items, status="running")

        return {"success": True, "job_id": job_id, "result": result}
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))
    except OutputLocationError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"{type(e).__name__}: {e}")


class BatchRandomRunRequest(BaseModel):
    count: int = 1  # 随机组数（1~10）
    workflow_path: str = ""
    workflow_content: str | None = None
    orientation: str = "portrait"
    quality: str = "4K"
    aspect_ratio: str = ""
    negative_prompt: str = ""
    search: str = ""  # 碎片筛选条件
    category_id: int | None = None
    tag_ids: str | None = None
    fixed_fragments: dict | None = None  # {类型名: 碎片内容, ...} 固定碎片，不参与随机
    composed_prompts: list[str] | None = None  # 前端预览确认后的组合文本；有则按原样提交
    output_subfolder: str = ""
    idempotency_key: str = ""


@router.post("/composer/batch_random_run")
def composer_batch_random_run(req: BatchRandomRunRequest):
    """批量随机组合碎片并跑图"""
    workflow_path = req.workflow_path or ""
    if not workflow_path:
        raise HTTPException(400, "缺少工作流路径")
    count = max(1, min(req.count, 10))  # 限制 1~10

    try:
        expand_subfolder(
            req.output_subfolder, workflow_path=workflow_path, job_id=0,
            quality=req.quality, orientation=req.orientation,
        )
        existing = find_job_by_idempotency(req.idempotency_key, "composer_batch")
        if existing is not None:
            return {
                "success": True, "job_id": existing["id"], "results": [],
                "idempotent": True, "async": True, "queued": 0, "total": existing["total"],
            }
        # 获取碎片数据
        grouped = _get_fragment_data(req.search, req.category_id, req.tag_ids)

        # 检查每个类型是否有碎片（仅后端随机时需要；前端已给组合文本则跳过）
        provided = [p.strip() for p in (req.composed_prompts or []) if p and p.strip()][:count]
        if not provided:
            for ft in FRAGMENT_TYPES:
                frags = grouped.get(ft, [])
                if not frags:
                    raise HTTPException(400, f"碎片类型「{ft}」没有可用碎片，请先添加")

        # 生成组合：前端预览确认过的直接按原样提交；否则后端随机
        fixed = req.fixed_fragments or {}
        job_items = []
        if provided:
            for composed_prompt in provided:
                task_seed = random.randint(0, 2**32 - 1)
                job_items.append({
                    "prompt_id": 0,
                    "seed": task_seed,
                    "prompt_preview": composed_prompt[:120],
                    "prompt_params": json.dumps({
                        "prompt": composed_prompt,
                        "negative_prompt": req.negative_prompt,
                        "source": "composer_random",
                        "selection": {},
                        "seed": task_seed,
                        "fixed_types": list(fixed.keys()),
                    }, ensure_ascii=False),
                })
        else:
            for i in range(count):
                # 从每个类型中随机选一个（固定类型直接用固定内容）
                selection = {}
                composed_parts = []
                for ft in FRAGMENT_TYPES:
                    if ft in fixed and fixed[ft]:
                        # 固定类型：直接使用固定内容
                        selection[ft] = fixed[ft]
                        composed_parts.append(f"【{ft}】\n{fixed[ft]}")
                    else:
                        # 随机类型：从碎片池中随机选
                        frags = grouped[ft]
                        pick = frags[random.randint(0, len(frags) - 1)]
                        selection[ft] = pick["content"]
                        composed_parts.append(f"【{ft}】\n{pick['content']}")

                composed_prompt = "\n\n".join(composed_parts)
                # 每个任务独立随机种子，避免批量时所有图用同一个种子
                task_seed = random.randint(0, 2**32 - 1)

                job_items.append({
                    "prompt_id": 0,
                    "seed": task_seed,
                    "prompt_preview": composed_prompt[:120],
                    "prompt_params": json.dumps({
                        "prompt": composed_prompt,
                        "negative_prompt": req.negative_prompt,
                        "source": "composer_random",
                        "selection": selection,
                        "seed": task_seed,
                        "fixed_types": list(fixed.keys()),
                    }, ensure_ascii=False),
                })

        # 创建任务；真正的 push 交给后台提交线程
        try:
            load_workflow(workflow_path, req.workflow_content)
        except Exception as e:
            raise HTTPException(400, f"工作流加载失败: {e}")
        for item in job_items:
            item["status"] = "pending"
            item["submit_state"] = "queued"

        extra = build_job_extra(workflow_path, req.workflow_content, req.output_subfolder)
        if req.idempotency_key.strip():
            extra["idempotency_key"] = req.idempotency_key.strip()
            extra["idempotency_scope"] = "composer_batch"
        job_id = create_job(
            "batch" if len(job_items) > 1 else "single",
            f"批量随机组合 ({len(job_items)} 组)",
            job_items,
            workflow_path,
            req.orientation,
            req.quality,
            extra=extra,
        )
        subfolder = expand_subfolder(
            req.output_subfolder, workflow_path=workflow_path, job_id=job_id,
            quality=req.quality, orientation=req.orientation,
        )

        def prepare(index: int) -> dict:
            item = job_items[index]
            api_wf = load_workflow(workflow_path, req.workflow_content)
            task_seed = item.get("seed") or random.randint(0, 2**32 - 1)
            prompt_data = {
                # 同一入口同样去掉【类型】标题；prompt_params 里仍保留原文
                "prompt": strip_headers(json.loads(item["prompt_params"])["prompt"]),
                "negative_prompt": req.negative_prompt,
                "seed": task_seed,
                "seed_override": task_seed,
                "orientation": req.orientation,
                "quality": req.quality,
                "aspect_ratio": req.aspect_ratio,
            }
            inject_prompt(api_wf, prompt_data)
            apply_output_subfolder(api_wf, subfolder)
            return api_wf

        update_job_items(job_id, job_items, status="running")
        enqueue_submission(SubmitTask(job_id, list(range(len(job_items))), prepare))

        return {
            "success": True, "job_id": job_id, "results": [],
            "total": len(job_items), "submitted": 0, "queued": len(job_items),
            "async": True,
        }
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))
    except OutputLocationError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"{type(e).__name__}: {e}")
