"""提示词 CRUD + 标签"""
import traceback
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

from models import Prompt, GenHistory, db, Category, Tag, PromptCategory, PromptTag
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
    # ======== Phase 1 新增 ========
    is_favorite: bool = False
    is_pinned: bool = False
    rating: Optional[int] = None
    # ================================


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
    # ======== Phase 1 新增 ========
    is_favorite: Optional[bool] = None
    is_pinned: Optional[bool] = None
    rating: Optional[int] = None
    # ================================


class PromptPreview(BaseModel):
    id: int
    prompt_preview: str
    tags: str = ""
    steps: Optional[int] = None
    sampler: str = ""
    model: str = ""
    name: str = ""
    created_at: str = ""
    # ======== Phase 1 新增 ========
    is_favorite: bool = False
    is_pinned: bool = False
    rating: Optional[int] = None
    usage_count: int = 0
    # ================================


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
    # ======== Phase 1 新增 ========
    is_favorite: bool = False
    is_pinned: bool = False
    usage_count: int = 0
    last_used_at: Optional[str] = None
    rating: Optional[int] = None
    # ================================


# ---------- Routes ----------

@router.get("/prompts", response_model=dict)
def list_prompts(
    search: str = Query(""),
    tag: str = Query(""),
    category_id: Optional[int] = Query(None),
    tag_ids: Optional[str] = Query(None),
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

    # ======== Phase 2: 添加分类和标签筛选 ========
    # 按分类筛选
    if category_id is not None:
        query = query.join(PromptCategory).where(PromptCategory.category == category_id)

    # 按标签筛选（多选）
    if tag_ids:
        tag_id_list = [int(tid.strip()) for tid in tag_ids.split(",") if tid.strip()]
        if tag_id_list:
            query = query.join(PromptTag).where(PromptTag.tag.in_(tag_id_list))
    # ================================================

    total = query.count()

    total = query.count()

    # ======== Phase 1: 更新排序逻辑 ========
    # 默认排序：置顶 → 收藏 → 最新
    if sort == "newest":
        order = [Prompt.is_pinned.desc(), Prompt.is_favorite.desc(), Prompt.id.desc()]
    elif sort == "oldest":
        order = [Prompt.is_pinned.desc(), Prompt.is_favorite.desc(), Prompt.id.asc()]
    elif sort == "name_asc":
        order = [Prompt.is_pinned.desc(), Prompt.is_favorite.desc(), Prompt.name.asc()]
    elif sort == "name_desc":
        order = [Prompt.is_pinned.desc(), Prompt.is_favorite.desc(), Prompt.name.desc()]
    elif sort == "updated":
        order = [Prompt.is_pinned.desc(), Prompt.is_favorite.desc(), Prompt.updated_at.desc()]
    elif sort == "most_used":  # 新增：按使用次数排序
        order = [Prompt.is_pinned.desc(), Prompt.is_favorite.desc(), Prompt.usage_count.desc()]
    else:
        order = [Prompt.is_pinned.desc(), Prompt.is_favorite.desc(), Prompt.id.desc()]
    # ==========================================
    
    offset = (page - 1) * page_size
    rows = query.order_by(*order).offset(offset).limit(page_size)

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
            # ======== Phase 1: 返回新字段 ========
            "is_favorite": r.is_favorite,
            "is_pinned": r.is_pinned,
            "rating": r.rating,
            "usage_count": r.usage_count,
            # ========================================
        })
    return {"prompts": prompts, "total": total, "page": page, "page_size": page_size}


@router.get("/prompts/{prompt_id}", response_model=dict)
def get_prompt(prompt_id: int):
    """获取单条提示词详情"""
    r = Prompt.get_or_none(Prompt.id == prompt_id)
    if r is None:
        raise HTTPException(404, "提示词不存在")

    # ======== Phase 2: 获取分类和标签 ========
    # 获取关联的分类
    categories = []
    for pc in PromptCategory.select().where(PromptCategory.prompt == prompt_id):
        cat = Category.get_or_none(Category.id == pc.category)
        if cat:
            categories.append({
                "id": cat.id,
                "name": cat.name,
                "color": cat.color
            })

    # 获取关联的标签
    tags = []
    for pt in PromptTag.select().where(PromptTag.prompt == prompt_id):
        tag = Tag.get_or_none(Tag.id == pt.tag)
        if tag:
            tags.append({
                "id": tag.id,
                "name": tag.name,
                "color": tag.color
            })
    # ================================================

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
        # ======== Phase 1: 返回新字段 ========
        "is_favorite": r.is_favorite,
        "is_pinned": r.is_pinned,
        "usage_count": r.usage_count,
        "last_used_at": str(r.last_used_at) if r.last_used_at else "",
        "rating": r.rating,
        # ======== Phase 2: 返回分类和标签 ========
        "categories": categories,
        "tags_detail": tags,
        # ================================================
    }


# ======== Phase 1: 添加收藏/置顶切换 API ========
@router.post("/prompts/{prompt_id}/favorite", response_model=dict)
def toggle_favorite(prompt_id: int):
    """切换提示词收藏状态"""
    r = Prompt.get_or_none(Prompt.id == prompt_id)
    if r is None:
        raise HTTPException(404, "提示词不存在")
    r.is_favorite = not r.is_favorite
    r.save()
    return {"success": True, "is_favorite": r.is_favorite}


@router.post("/prompts/{prompt_id}/pin", response_model=dict)
def toggle_pin(prompt_id: int):
    """切换提示词置顶状态"""
    r = Prompt.get_or_none(Prompt.id == prompt_id)
    if r is None:
        raise HTTPException(404, "提示词不存在")
    r.is_pinned = not r.is_pinned
    r.save()
    return {"success": True, "is_pinned": r.is_pinned}


@router.post("/prompts/{prompt_id}/rate", response_model=dict)
def rate_prompt(prompt_id: int, rating: int = Query(..., ge=1, le=5)):
    """设置提示词评级（1-5）"""
    r = Prompt.get_or_none(Prompt.id == prompt_id)
    if r is None:
        raise HTTPException(404, "提示词不存在")
    r.rating = rating
    r.save()
    return {"success": True, "rating": r.rating}


@router.post("/prompts/{prompt_id}/use", response_model=dict)
def mark_prompt_used(prompt_id: int):
    """标记提示词已被使用（增加使用次数）"""
    r = Prompt.get_or_none(Prompt.id == prompt_id)
    if r is None:
        raise HTTPException(404, "提示词不存在")
    r.usage_count += 1
    r.last_used_at = datetime.now()
    r.save()
    return {"success": True, "usage_count": r.usage_count}
# =================================================


@router.post("/prompts", status_code=201)
def create_prompt(data: PromptCreate):
    """新建提示词"""
    # ======== Phase 1: 处理新字段 ========
    data_dict = data.model_dump()
    # 确保布尔字段有默认值
    if "is_favorite" not in data_dict:
        data_dict["is_favorite"] = False
    if "is_pinned" not in data_dict:
        data_dict["is_pinned"] = False
    if "usage_count" not in data_dict:
        data_dict["usage_count"] = 0
    # ==========================================
    r = Prompt.create(**data_dict)
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
    """删除提示词（同时清理关联的分类、标签、生成历史）"""
    try:
        r = Prompt.get_or_none(Prompt.id == prompt_id)
        if r is None:
            raise HTTPException(404, "提示词不存在")
        # 先删除关联表中的记录，避免外键约束错误
        pc = PromptCategory.delete().where(PromptCategory.prompt == prompt_id).execute()
        pt = PromptTag.delete().where(PromptTag.prompt == prompt_id).execute()
        gh = GenHistory.delete().where(GenHistory.prompt_id == prompt_id).execute()
        r.delete_instance()
        return {"success": True, "deleted": {"prompt_categories": pc, "prompt_tags": pt, "gen_history": gh}}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"删除失败: {type(e).__name__}: {e}")


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
            "prompt_id": r.prompt_id,
            "filename": r.filename,
            "subfolder": r.subfolder,
            "img_type": r.img_type,
            "view_url": r.view_url,
            "created_at": str(r.created_at) if r.created_at else "",
            "prompt_name": p.name or "",  # 添加提示词名称
            **meta,
        })
    return {"items": items}
