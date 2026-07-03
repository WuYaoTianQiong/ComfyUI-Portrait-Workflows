"""组合创作 API —— 碎片解析 + 碎片跑图"""
import re
import json
import traceback
import random
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from models import Prompt, Fragment, Category, Tag, PromptCategory, PromptTag, db
from services.workflow_parser import load_workflow, inject_prompt
from services.comfyui_client import push_prompt
from routers.jobs import create_job, update_job_items
from config import settings
from shared import FRAGMENT_TYPES, parse_prompt_fragments

router = APIRouter(tags=["组合创作"])


def _get_fragment_data(search="", category_id=None, tag_ids=None):
    """获取碎片数据，按类型分组，供随机组合使用"""
    query = Prompt.select()

    if search:
        query = query.where(
            Prompt.prompt.contains(search)
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
            query = query.join(PromptTag).where(PromptTag.tag.in_(tag_id_list))

    rows = list(query.order_by(Prompt.id.desc()))

    grouped = {t: [] for t in FRAGMENT_TYPES}
    seen_content = {}

    def content_key(ftype, content):
        return f"{ftype}||{content}"

    for r in rows:
        fragments = parse_prompt_fragments(r.prompt)
        for f in fragments:
            ftype = f["type"]
            if ftype not in grouped:
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

    # 合并碎片库的独立碎片
    try:
        if not db.table_exists("fragments"):
            db.create_tables([Fragment], safe=True)
        for r in Fragment.select().order_by(Fragment.id.desc()):
            ft = r.fragment_type
            if ft not in grouped:
                continue
            ck = content_key(ft, r.content)
            if ck in seen_content:
                continue
            seen_content[ck] = True
            grouped[ft].append({
                "fragment_id": r.id,
                "prompt_id": None,
                "prompt_name": r.name or "",
                "type": ft,
                "content": r.content,
                "tags": r.tags or "",
                "source_preview": "",
                "source": "library",
                "dup_count": 1,
            })
    except Exception as e:
        traceback.print_exc()
        print(f"[composer] 碎片库查询失败: {type(e).__name__}: {e}")

    return grouped


@router.get("/composer/fragments")
def get_fragments(
    search: str = Query(""),
    category_id: Optional[int] = Query(None),
    tag_ids: Optional[str] = Query(None),
):
    """获取当前筛选提示词范围内的碎片列表，按类型分组"""
    grouped = _get_fragment_data(search, category_id, tag_ids)
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


@router.post("/composer/run")
def composer_run(req: ComposerRunRequest):
    """组合提示词直接跑图（不保存到提示词库）"""
    workflow_path = req.workflow_path or ""
    if not workflow_path:
        raise HTTPException(400, "缺少工作流路径")

    try:
        api_wf = load_workflow(workflow_path, req.workflow_content)
        prompt_data = {
            "prompt": req.prompt,
            "negative_prompt": req.negative_prompt,
            "seed": 0,
            "seed_override": 0,
            "orientation": req.orientation,
            "quality": req.quality,
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
                "source": "composer",
            }, ensure_ascii=False),
        }]
        job_id = create_job(
            "single", "组合创作", items, workflow_path,
            req.orientation, req.quality,
        )

        result = push_prompt(api_wf)
        comfy_pid = result.get("prompt_id", "")
        items[0]["comfyui_prompt_id"] = comfy_pid
        items[0]["status"] = "pending"
        update_job_items(job_id, items, status="running")

        return {"success": True, "job_id": job_id, "result": result}
    except FileNotFoundError as e:
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
    negative_prompt: str = ""
    search: str = ""  # 碎片筛选条件
    category_id: int | None = None
    tag_ids: str | None = None
    fixed_fragments: dict | None = None  # {类型名: 碎片内容, ...} 固定碎片，不参与随机


@router.post("/composer/batch_random_run")
def composer_batch_random_run(req: BatchRandomRunRequest):
    """批量随机组合碎片并跑图"""
    workflow_path = req.workflow_path or ""
    if not workflow_path:
        raise HTTPException(400, "缺少工作流路径")
    count = max(1, min(req.count, 10))  # 限制 1~10

    try:
        # 获取碎片数据
        grouped = _get_fragment_data(req.search, req.category_id, req.tag_ids)

        # 检查每个类型是否有碎片
        for ft in FRAGMENT_TYPES:
            frags = grouped.get(ft, [])
            if not frags:
                raise HTTPException(400, f"碎片类型「{ft}」没有可用碎片，请先添加")

        # 生成随机组合
        fixed = req.fixed_fragments or {}
        job_items = []
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

        # 创建任务
        job_id = create_job(
            "batch" if count > 1 else "single",
            f"批量随机组合 ({count} 组)",
            job_items,
            workflow_path,
            req.orientation,
            req.quality,
        )

        # 逐组跑图
        results = []
        for idx, item in enumerate(job_items):
            try:
                api_wf = load_workflow(workflow_path, req.workflow_content)
                # 使用每个任务独立的种子
                task_seed = item.get("seed") or random.randint(0, 2**32 - 1)
                prompt_data = {
                    "prompt": json.loads(item["prompt_params"])["prompt"],
                    "negative_prompt": req.negative_prompt,
                    "seed": task_seed,
                    "seed_override": task_seed,
                    "orientation": req.orientation,
                    "quality": req.quality,
                }
                inject_prompt(api_wf, prompt_data)
                result = push_prompt(api_wf)
                comfy_pid = result.get("prompt_id", "")
                item["comfyui_prompt_id"] = comfy_pid
                item["status"] = "pending"
                results.append({"index": idx, "comfy_pid": comfy_pid, "success": True})
            except Exception as e:
                item["status"] = "error"
                item["error"] = str(e)
                results.append({"index": idx, "success": False, "error": str(e)})

        update_job_items(job_id, job_items, status="running")

        return {"success": True, "job_id": job_id, "results": results}
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"{type(e).__name__}: {e}")
