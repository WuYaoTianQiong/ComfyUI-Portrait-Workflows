"""碎片库 API —— 独立碎片 CRUD + 按类型分组（供 Composer 使用）"""
import traceback
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from models import Fragment, db
from shared import FRAGMENT_TYPES, templates

router = APIRouter(tags=["碎片库"])


def _ensure_table():
    """确保 fragments 表存在（防御性创建）"""
    try:
        db.create_tables([Fragment], safe=True)
    except Exception as e:
        print(f"[fragments] 建表失败: {type(e).__name__}: {e}")

# ---------- Pydantic ----------

class FragmentCreate(BaseModel):
    name: str = ""
    fragment_type: str = "人物面部"
    content: str = ""
    tags: str = ""


class FragmentUpdate(BaseModel):
    name: Optional[str] = None
    fragment_type: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[str] = None


# ---------- Routes ----------

@router.get("/fragments")
def list_fragments(
    search: str = Query(""),
    fragment_type: str = Query(""),
    page: int = Query(1),
    page_size: int = Query(100),
):
    """列出碎片库，支持搜索和类型筛选"""
    _ensure_table()
    query = Fragment.select()
    if search:
        like = f"%{search}%"
        query = query.where(
            Fragment.content.contains(search)
            | Fragment.name.contains(search)
            | Fragment.tags.contains(search)
        )
    if fragment_type:
        query = query.where(Fragment.fragment_type == fragment_type)

    total = query.count()
    rows = query.order_by(Fragment.id.desc()).offset((page - 1) * page_size).limit(page_size)

    items = []
    for r in rows:
        items.append({
            "id": r.id,
            "name": r.name or "",
            "fragment_type": r.fragment_type,
            "content": r.content,
            "tags": r.tags or "",
            "usage_count": r.usage_count,
            "created_at": str(r.created_at) if r.created_at else "",
            "updated_at": str(r.updated_at) if r.updated_at else "",
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/fragments/by_type")
def get_fragments_by_type():
    """按碎片类型分组（供 Composer 使用）"""
    _ensure_table()
    grouped = {t: [] for t in FRAGMENT_TYPES}
    for r in Fragment.select().order_by(Fragment.id.desc()):
        ft = r.fragment_type
        if ft in grouped:
            grouped[ft].append({
                "fragment_id": r.id,
                "name": r.name or "",
                "fragment_type": ft,
                "content": r.content,
                "tags": r.tags or "",
                "usage_count": r.usage_count,
            })
    # 统计
    total = sum(len(v) for v in grouped.values())
    return {"grouped": grouped, "total": total}


@router.post("/fragments", status_code=201)
def create_fragment(data: FragmentCreate):
    """创建独立碎片"""
    _ensure_table()
    if data.fragment_type not in FRAGMENT_TYPES:
        raise HTTPException(400, f"无效的碎片类型，可选: {', '.join(FRAGMENT_TYPES)}")
    if not data.content.strip():
        raise HTTPException(400, "碎片内容不能为空")
    r = Fragment.create(
        name=data.name.strip(),
        fragment_type=data.fragment_type,
        content=data.content.strip(),
        tags=data.tags.strip(),
    )
    return {"success": True, "id": r.id}


@router.put("/fragments/{fragment_id}")
def update_fragment(fragment_id: int, data: FragmentUpdate):
    """更新碎片"""
    _ensure_table()
    r = Fragment.get_or_none(Fragment.id == fragment_id)
    if r is None:
        raise HTTPException(404, "碎片不存在")

    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, "没有需要更新的字段")
    if "fragment_type" in updates and updates["fragment_type"] not in FRAGMENT_TYPES:
        raise HTTPException(400, f"无效的碎片类型")

    updates["updated_at"] = datetime.now()
    Fragment.update(**updates).where(Fragment.id == fragment_id).execute()
    return {"success": True}


@router.delete("/fragments/{fragment_id}")
def delete_fragment(fragment_id: int):
    """删除碎片"""
    _ensure_table()
    r = Fragment.get_or_none(Fragment.id == fragment_id)
    if r is None:
        raise HTTPException(404, "碎片不存在")
    Fragment.delete_by_id(fragment_id)
    return {"success": True}


# ====================================================================
# Phase 2: HTMX 端点 —— 返回碎片库列表的 HTML 片段
# ====================================================================

@router.get("/fragments/html", response_class=HTMLResponse)
def fragments_list_html(
    request: Request,
    search: str = Query(""),
    fragment_type: str = Query(""),
    page: int = Query(1),
    page_size: int = Query(500),
):
    _ensure_table()
    query = Fragment.select()
    if search:
        query = query.where(
            Fragment.content.contains(search)
            | Fragment.name.contains(search)
            | Fragment.tags.contains(search)
        )
    if fragment_type:
        query = query.where(Fragment.fragment_type == fragment_type)
    total = query.count()
    rows = query.order_by(Fragment.id.desc()).offset((page - 1) * page_size).limit(page_size)
    items = []
    for r in rows:
        items.append({
            "id": r.id, "name": r.name or "", "fragment_type": r.fragment_type,
            "content": r.content, "tags": r.tags or "", "usage_count": r.usage_count,
            "created_at": str(r.created_at) if r.created_at else "",
            "updated_at": str(r.updated_at) if r.updated_at else "",
        })
    return templates.TemplateResponse("fragments/list.jinja2", {
        "request": request, "items": items, "total": total,
        "page": page, "page_size": page_size,
        "search": search, "fragment_type": fragment_type,
    })
