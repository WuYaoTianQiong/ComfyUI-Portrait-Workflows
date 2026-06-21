"""标签管理 API"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List

from models import Tag, PromptTag, Prompt, db

router = APIRouter(tags=["标签"])


# ---------- Pydantic schemas ----------
class TagCreate(BaseModel):
    name: str
    color: str = "#8b5cf6"


class TagUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None


# ---------- Routes ----------
@router.get("/tags", response_model=dict)
def list_tags(
    search: str = Query(""),
    popular: bool = Query(False, description="按使用次数排序"),
):
    """获取标签列表"""
    query = Tag.select()
    if search:
        query = query.where(Tag.name.contains(search))
    
    if popular:
        query = query.order_by(Tag.usage_count.desc(), Tag.name.asc())
    else:
        query = query.order_by(Tag.name.asc())
    
    tags = []
    for t in query:
        tags.append({
            "id": t.id,
            "name": t.name,
            "color": t.color,
            "usage_count": t.usage_count,
            "prompt_count": PromptTag.select().where(PromptTag.tag_id == t.id).count(),
        })
    return {"tags": tags}


@router.post("/tags", status_code=201)
def create_tag(data: TagCreate):
    """创建标签"""
    try:
        t = Tag.create(**data.model_dump())
        return {"success": True, "id": t.id}
    except Exception as e:
        raise HTTPException(400, f"创建失败: {str(e)}")


@router.put("/tags/{tag_id}")
def update_tag(tag_id: int, data: TagUpdate):
    """更新标签"""
    t = Tag.get_or_none(Tag.id == tag_id)
    if t is None:
        raise HTTPException(404, "标签不存在")
    
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, "没有需要更新的字段")
    
    Tag.update(**updates).where(Tag.id == tag_id).execute()
    return {"success": True}


@router.delete("/tags/{tag_id}")
def delete_tag(tag_id: int):
    """删除标签（同时删除关联关系）"""
    t = Tag.get_or_none(Tag.id == tag_id)
    if t is None:
        raise HTTPException(404, "标签不存在")
    
    # 删除关联关系
    PromptTag.delete().where(PromptTag.tag == tag_id).execute()
    
    # 删除标签
    t.delete_instance(recursive=False)
    return {"success": True}


@router.post("/tags/{tag_id}/prompts/{prompt_id}")
def add_prompt_to_tag(tag_id: int, prompt_id: int):
    """将提示词添加到标签"""
    t = Tag.get_or_none(Tag.id == tag_id)
    if t is None:
        raise HTTPException(404, "标签不存在")
    
    p = Prompt.get_or_none(Prompt.id == prompt_id)
    if p is None:
        raise HTTPException(404, "提示词不存在")
    
    # 检查是否已关联
    exists = PromptTag.get_or_none(
        (PromptTag.prompt == prompt_id) & (PromptTag.tag == tag_id)
    )
    if exists:
        return {"success": True, "message": "已关联"}
    
    PromptTag.create(prompt=prompt_id, tag=tag_id)
    
    # 更新标签使用次数
    Tag.update(usage_count=Tag.usage_count + 1).where(Tag.id == tag_id).execute()
    
    return {"success": True}


@router.delete("/tags/{tag_id}/prompts/{prompt_id}")
def remove_prompt_from_tag(tag_id: int, prompt_id: int):
    """从标签中移除提示词"""
    pt = PromptTag.get_or_none(
        (PromptTag.prompt == prompt_id) & (PromptTag.tag == tag_id)
    )
    if pt is None:
        raise HTTPException(404, "关联关系不存在")
    
    pt.delete_instance()
    
    # 更新标签使用次数
    Tag.update(usage_count=Tag.usage_count - 1).where(Tag.id == tag_id).execute()
    
    return {"success": True}


@router.get("/tags/popular", response_model=dict)
def get_popular_tags(limit: int = Query(20, ge=1, le=100)):
    """获取热门标签（按使用次数排序）"""
    tags = (
        Tag.select()
        .order_by(Tag.usage_count.desc(), Tag.name.asc())
        .limit(limit)
    )
    result = []
    for t in tags:
        result.append({
            "id": t.id,
            "name": t.name,
            "color": t.color,
            "usage_count": t.usage_count,
        })
    return {"tags": result}
