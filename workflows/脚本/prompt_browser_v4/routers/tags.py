"""标签管理 API（读写都走 entity_tags，由 services.taxonomy 统一维护）"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from models import EntityTag, Tag, Prompt
from services.taxonomy import (
    add_prompt_tag_by_name,
    remove_prompt_tag_by_name,
    tag_image_counts,
    tag_prompt_counts,
)

router = APIRouter(tags=["标签"])


# ---------- Pydantic schemas ----------
class TagCreate(BaseModel):
    name: str
    color: str = "#5b8fb9"


class TagUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None


# ---------- 工具函数 ----------
def _tag_to_dict(t, count_scope: str = "prompt", counts_map: dict = None) -> dict:
    """count_scope=prompt 返回挂了这个标签的提示词数，image 返回去重图片数。

    两种计数都由 services.taxonomy 一次性批量算出（136 个标签不做 136 次聚合）。
    """
    return {
        "id": t.id,
        "name": t.name,
        "color": t.color,
        "usage_count": t.usage_count,
        "prompt_count": (counts_map or {}).get(t.id, 0),
    }


# ---------- Routes ----------
@router.get("/tags")
def list_tags(
    search: str = Query(""),
    popular: bool = Query(False, description="按使用次数排序"),
    count_scope: str = Query("prompt", description="计数维度: prompt=提示词数, image=图片数"),
):
    query = Tag.select()
    if search:
        query = query.where(Tag.name.contains(search))
    if popular:
        query = query.order_by(Tag.usage_count.desc(), Tag.name.asc())
    else:
        query = query.order_by(Tag.name.asc())
    counts_map = tag_image_counts() if count_scope == "image" else tag_prompt_counts()
    return {"tags": [_tag_to_dict(t, count_scope, counts_map) for t in query]}


@router.post("/tags", status_code=201)
def create_tag(data: TagCreate):
    try:
        t = Tag.create(**data.model_dump())
        return {"success": True, "id": t.id}
    except Exception as e:
        raise HTTPException(400, f"创建失败: {e}")


@router.put("/tags/{tag_id}")
def update_tag(tag_id: int, data: TagUpdate):
    t = Tag.get_or_none(Tag.id == tag_id)
    if t is None:
        raise HTTPException(404, "标签不存在")
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, "没有需要更新的字段")
    try:
        Tag.update(**updates).where(Tag.id == tag_id).execute()
    except Exception as e:
        raise HTTPException(400, f"更新失败: {e}")
    return {"success": True}


@router.delete("/tags/{tag_id}")
def delete_tag(tag_id: int):
    t = Tag.get_or_none(Tag.id == tag_id)
    if t is None:
        raise HTTPException(404, "标签不存在")
    # 关联关系一起清掉，避免留下悬空 entity_tags（旧实现只删 prompt_tags，
    # image_tags 与 entity_tags 里的关联会变成孤儿）
    EntityTag.delete().where(EntityTag.tag == tag_id).execute()
    t.delete_instance(recursive=False)
    return {"success": True}


@router.get("/tags/popular")
def get_popular_tags(
    limit: int = Query(20, ge=1, le=100),
    count_scope: str = Query("prompt", description="计数维度: prompt=提示词数, image=图片数"),
):
    tags = (
        Tag.select()
        .order_by(Tag.usage_count.desc(), Tag.name.asc())
        .limit(limit)
    )
    counts_map = tag_image_counts() if count_scope == "image" else tag_prompt_counts()
    return {"tags": [_tag_to_dict(t, count_scope, counts_map) for t in tags]}


@router.post("/tags/{tag_id}/prompts/{prompt_id}")
def add_prompt_to_tag(tag_id: int, prompt_id: int):
    t = Tag.get_or_none(Tag.id == tag_id)
    if t is None:
        raise HTTPException(404, "标签不存在")
    p = Prompt.get_or_none(Prompt.id == prompt_id)
    if p is None:
        raise HTTPException(404, "提示词不存在")
    if not add_prompt_tag_by_name(prompt_id, t.name):
        return {"success": True, "message": "已关联"}
    return {"success": True}


@router.delete("/tags/{tag_id}/prompts/{prompt_id}")
def remove_prompt_from_tag(tag_id: int, prompt_id: int):
    t = Tag.get_or_none(Tag.id == tag_id)
    if t is None:
        raise HTTPException(404, "标签不存在")
    if not remove_prompt_tag_by_name(prompt_id, t.name):
        raise HTTPException(404, "关联关系不存在")
    return {"success": True}
