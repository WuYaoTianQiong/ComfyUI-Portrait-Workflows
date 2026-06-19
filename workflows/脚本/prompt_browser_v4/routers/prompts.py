"""提示词 CRUD + 标签"""
import traceback
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

from models import Prompt, GenHistory, db
from services.helpers import get_image_metadata

router = APIRouter(tags=["提示词"])


# ---------- Pydantic schemas ----------

class PromptCreate(BaseModel):
    name: str = ""
    prompt: str = ""
    negative_prompt: str = ""
    steps: Optional[int] = None
    cfg_scale: Optional[float] = None
    sampler: str = ""
    seed: Optional[int] = None
    model: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    tags: str = ""
    note: str = ""


class PromptUpdate(BaseModel):
    name: Optional[str] = None
    prompt: Optional[str] = None
    negative_prompt: Optional[str] = None
    steps: Optional[int] = None
    cfg_scale: Optional[float] = None
    sampler: Optional[str] = None
    seed: Optional[int] = None
    model: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    tags: Optional[str] = None
    note: Optional[str] = None


class PromptPreview(BaseModel):
    id: int
    prompt_preview: str
    tags: str = ""
    steps: Optional[int] = None
    sampler: str = ""
    model: str = ""
    name: str = ""
    created_at: str = ""


class PromptDetail(BaseModel):
    id: int
    name: str
    prompt: str
    negative_prompt: str
    steps: Optional[int] = None
    cfg_scale: Optional[float] = None
    sampler: str
    seed: Optional[int] = None
    model: str
    width: Optional[int] = None
    height: Optional[int] = None
    tags: str
    note: str
    created_at: str
    updated_at: str


# ---------- Routes ----------

@router.get("/prompts", response_model=dict)
def list_prompts(
    search: str = Query(""),
    tag: str = Query(""),
    sort: str = Query("newest"),
    page: int = Query(1),
    page_size: int = Query(50),
):
    """搜索提示词列表，支持排序和分页"""
    query = Prompt.select()
    if search:
        like = f"%{search}%"
        query = query.where(
            (Prompt.prompt.contains(search))
            | (Prompt.tags.contains(search))
            | (Prompt.note.contains(search))
        )
    if tag:
        query = query.where(Prompt.tags.contains(tag))

    total = query.count()

    _SORT_MAP = {
        "newest":      Prompt.id.desc(),
        "oldest":       Prompt.id.asc(),
        "name_asc":    Prompt.name.asc(),
        "name_desc":   Prompt.name.desc(),
        "updated":      Prompt.updated_at.desc(),
    }
    order = _SORT_MAP.get(sort, Prompt.id.desc())
    offset = (page - 1) * page_size
    rows = query.order_by(order).offset(offset).limit(page_size)

    prompts = []
    for r in rows:
        prompts.append({
            "id": r.id,
            "prompt_preview": (r.prompt or "")[:60],
            "tags": r.tags or "",
            "steps": r.steps,
            "sampler": r.sampler or "",
            "model": r.model or "",
            "name": r.name or "",
            "created_at": str(r.created_at) if r.created_at else "",
        })
    return {"prompts": prompts, "total": total, "page": page, "page_size": page_size}


@router.get("/prompts/{prompt_id}", response_model=dict)
def get_prompt(prompt_id: int):
    """获取单条提示词详情"""
    r = Prompt.get_or_none(Prompt.id == prompt_id)
    if r is None:
        raise HTTPException(404, "提示词不存在")
    return {
        "id": r.id,
        "name": r.name or "",
        "prompt": r.prompt or "",
        "negative_prompt": r.negative_prompt or "",
        "steps": r.steps,
        "cfg_scale": r.cfg_scale,
        "sampler": r.sampler or "",
        "seed": r.seed,
        "model": r.model or "",
        "width": r.width,
        "height": r.height,
        "tags": r.tags or "",
        "note": r.note or "",
        "created_at": str(r.created_at) if r.created_at else "",
        "updated_at": str(r.updated_at) if r.updated_at else "",
    }


@router.post("/prompts", status_code=201)
def create_prompt(data: PromptCreate):
    """新建提示词"""
    r = Prompt.create(**data.model_dump())
    return {"success": True, "id": r.id}


@router.put("/prompts/{prompt_id}")
def update_prompt(prompt_id: int, data: PromptUpdate):
    """更新提示词（仅更新提供值的字段）"""
    r = Prompt.get_or_none(Prompt.id == prompt_id)
    if r is None:
        raise HTTPException(404, "提示词不存在")

    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, "没有需要更新的字段")

    updates["updated_at"] = datetime.now()
    Prompt.update(**updates).where(Prompt.id == prompt_id).execute()
    return {"success": True}


@router.delete("/prompts/{prompt_id}")
def delete_prompt(prompt_id: int):
    """删除提示词"""
    r = Prompt.get_or_none(Prompt.id == prompt_id)
    if r is None:
        raise HTTPException(404, "提示词不存在")
    r.delete_instance()
    return {"success": True}


@router.get("/prompts/{prompt_id}/history", response_model=dict)
def get_prompt_history(prompt_id: int, limit: int = Query(20)):
    """获取某条提示词的生成历史图片"""
    p = Prompt.get_or_none(Prompt.id == prompt_id)
    if p is None:
        raise HTTPException(404, "提示词不存在")

    rows = (
        GenHistory
        .select()
        .where(GenHistory.prompt_id == prompt_id)
        .order_by(GenHistory.id.desc())
        .limit(limit)
    )
    items = []
    for r in rows:
        meta = get_image_metadata(r.filename, r.subfolder or "", r.img_type or "output")
        items.append({
            "id": r.id,
            "filename": r.filename,
            "subfolder": r.subfolder,
            "img_type": r.img_type,
            "view_url": r.view_url,
            "created_at": str(r.created_at) if r.created_at else "",
            **meta,
        })
    return {"items": items}


@router.get("/tags", response_model=dict)
def list_tags():
    """获取所有标签"""
    rows = Prompt.select(Prompt.tags).where(
        Prompt.tags.is_null(False) & (Prompt.tags != "")
    )
    all_tags: set[str] = set()
    for r in rows:
        for t in (r.tags or "").split(","):
            t = t.strip()
            if t:
                all_tags.add(t)
    return {"tags": sorted(all_tags)}
