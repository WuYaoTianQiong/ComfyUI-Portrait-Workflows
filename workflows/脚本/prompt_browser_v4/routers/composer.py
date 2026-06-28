"""组合创作 API —— 碎片解析 + 碎片跑图"""
import re
import json
import traceback
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from models import Prompt, Category, Tag, PromptCategory, PromptTag, db
from services.workflow_parser import load_workflow, inject_prompt
from services.comfyui_client import push_prompt
from routers.jobs import create_job, update_job_items
from config import settings

router = APIRouter(tags=["组合创作"])

FRAGMENT_TYPES = ["人物面部", "人物身材", "人物服饰", "姿态动作", "拍摄视角", "场景环境", "光影色调", "画风技术"]


def parse_prompt_fragments(prompt_text: str) -> list[dict]:
    """解析 【xx】... 格式的提示词为碎片列表"""
    if not prompt_text:
        return []
    fragments = []
    # 匹配 【xxx】后面的内容，直到遇到下一个 【 或字符串结尾
    pattern = r'【([^】]+)】\s*(.*?)(?=\n【|$)'
    for m in re.finditer(pattern, prompt_text, re.DOTALL):
        name = m.group(1).strip()
        content = m.group(2).strip()
        if content:
            fragments.append({"type": name, "content": content})
    return fragments


@router.get("/composer/fragments")
def get_fragments(
    search: str = Query(""),
    category_id: Optional[int] = Query(None),
    tag_ids: Optional[str] = Query(None),
):
    """获取当前筛选提示词范围内的碎片列表，按类型分组"""
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
        tag_id_list = [
            int(t.strip()) for t in tag_ids.split(",") if t.strip()
        ]
        if tag_id_list:
            query = query.join(PromptTag).where(PromptTag.tag.in_(tag_id_list))

    rows = list(query.order_by(Prompt.id.desc()))

    grouped: dict[str, list] = {t: [] for t in FRAGMENT_TYPES}

    for r in rows:
        fragments = parse_prompt_fragments(r.prompt)
        for f in fragments:
            ftype = f["type"]
            if ftype in grouped:
                # 避免完全重复的碎片内容（相同 prompt 下也可能有内容相同的碎片）
                key = (r.id, ftype, f["content"])
                already = any(
                    (x.get("prompt_id"), x.get("type"), x.get("content")) == key
                    for x in grouped[ftype]
                )
                if not already:
                    grouped[ftype].append({
                        "prompt_id": r.id,
                        "prompt_name": r.name or "",
                        "type": ftype,
                        "content": f["content"],
                        "tags": r.tags or "",
                        "source_preview": (r.prompt or "")[:60],
                    })

    total_fragments = sum(len(v) for v in grouped.values())
    return {
        "grouped": grouped,
        "total_prompts": len(rows),
        "fragment_count": total_fragments,
    }


class ComposerRunRequest(BaseModel):
    prompt: str
    negative_prompt: str = ""
    workflow_path: str = ""
    orientation: str = "portrait"
    quality: str = "4K"


@router.post("/composer/run")
def composer_run(req: ComposerRunRequest):
    """组合提示词直接跑图（不保存到提示词库）"""
    workflow_path = req.workflow_path or ""
    if not workflow_path:
        raise HTTPException(400, "缺少工作流路径")

    try:
        api_wf = load_workflow(workflow_path, None)
        prompt_data = {
            "prompt": req.prompt,
            "negative_prompt": req.negative_prompt,
            "seed": 0,
            "seed_override": 0,
            "orientation": req.orientation,
            "quality": req.quality,
        }
        inject_prompt(api_wf, prompt_data)

        items = [{
            "prompt_id": 0,
            "seed": 0,
            "prompt_preview": (req.prompt or "")[:40],
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
