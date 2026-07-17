"""标签管理 API"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from models import Tag, PromptTag, Prompt, ImageTag, GenHistory, db

router = APIRouter(tags=["标签"])


# ---------- Pydantic schemas ----------
class TagCreate(BaseModel):
    name: str
    color: str = "#5b8fb9"


class TagUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None


# ---------- 工具函数 ----------
def _batch_image_counts() -> dict:
    """一次性算出每个标签的去重图片数（直接 image_tags OR 经 prompt 继承）。

    避免逐标签各跑一次 COUNT（136 个标签 = 136 次聚合）。用一条带 UNION 的
    SQL 同时覆盖「直接打标签」与「经来源提示词继承」两条路径并去重，仅 1 次查询。
    """
    cur = db.execute_sql(
        """
        SELECT tag_id, COUNT(DISTINCT gh_id) FROM (
            SELECT it.tag_id AS tag_id, gh.id AS gh_id
            FROM gen_history gh
            JOIN image_tags it ON it.image_id = gh.id
            UNION
            SELECT pt.tag_id AS tag_id, gh.id AS gh_id
            FROM gen_history gh
            JOIN prompt_tags pt ON pt.prompt_id = gh.prompt_id
        ) GROUP BY tag_id
        """
    )
    return {row[0]: row[1] for row in cur.fetchall()}


def _tag_to_dict(t, count_scope: str = "prompt", counts_map: dict = None) -> dict:
    if count_scope == "image":
        # 图片数来自一次性批量统计（直接 image_tags OR 经 prompt 继承，已去重）
        img_count = (counts_map or {}).get(t.id, 0)
    else:
        img_count = PromptTag.select().where(PromptTag.tag_id == t.id).count()
    return {
        "id": t.id, "name": t.name, "color": t.color,
        "usage_count": t.usage_count,
        "prompt_count": img_count,
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
    counts_map = _batch_image_counts() if count_scope == "image" else None
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
    Tag.update(**updates).where(Tag.id == tag_id).execute()
    return {"success": True}


@router.delete("/tags/{tag_id}")
def delete_tag(tag_id: int):
    t = Tag.get_or_none(Tag.id == tag_id)
    if t is None:
        raise HTTPException(404, "标签不存在")
    PromptTag.delete().where(PromptTag.tag == tag_id).execute()
    t.delete_instance(recursive=False)
    return {"success": True}


@router.get("/tags/popular")
def get_popular_tags(limit: int = Query(20, ge=1, le=100)):
    tags = (
        Tag.select()
        .order_by(Tag.usage_count.desc(), Tag.name.asc())
        .limit(limit)
    )
    counts_map = _batch_image_counts() if count_scope == "image" else None
    return {"tags": [_tag_to_dict(t, count_scope, counts_map) for t in tags]}


@router.post("/tags/{tag_id}/prompts/{prompt_id}")
def add_prompt_to_tag(tag_id: int, prompt_id: int):
    t = Tag.get_or_none(Tag.id == tag_id)
    if t is None:
        raise HTTPException(404, "标签不存在")
    p = Prompt.get_or_none(Prompt.id == prompt_id)
    if p is None:
        raise HTTPException(404, "提示词不存在")
    exists = PromptTag.get_or_none(
        (PromptTag.prompt == prompt_id) & (PromptTag.tag == tag_id)
    )
    if exists:
        return {"success": True, "message": "已关联"}
    PromptTag.create(prompt=prompt_id, tag=tag_id)
    Tag.update(usage_count=Tag.usage_count + 1).where(Tag.id == tag_id).execute()
    return {"success": True}


@router.delete("/tags/{tag_id}/prompts/{prompt_id}")
def remove_prompt_from_tag(tag_id: int, prompt_id: int):
    pt = PromptTag.get_or_none(
        (PromptTag.prompt == prompt_id) & (PromptTag.tag == tag_id)
    )
    if pt is None:
        raise HTTPException(404, "关联关系不存在")
    pt.delete_instance()
    Tag.update(usage_count=Tag.usage_count - 1).where(Tag.id == tag_id).execute()
    return {"success": True}
