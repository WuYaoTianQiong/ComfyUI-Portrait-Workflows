"""提示词 CRUD + 标签"""
import io
import json
import traceback
from fastapi import APIRouter, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import StreamingResponse, HTMLResponse
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

from models import Prompt, GenHistory, db, Category, Tag, PromptCategory, PromptTag, auto_classify_prompt
from services.helpers import get_image_metadata
from shared import templates

router = APIRouter(tags=["提示词"])


# ====================================================================
# 导出：必须注册在 /prompts/{prompt_id} 之前，否则 "export" 会被当成 prompt_id
# 由动态路由先匹配，永远返回 422。FastAPI 按注册顺序匹配，改路径不如改顺序。
# ====================================================================

@router.get("/prompts/export")
def export_prompts():
    """导出所有提示词为 JSON 文件"""
    rows = Prompt.select().order_by(Prompt.id)
    data = []
    for r in rows:
        data.append({
            "name": r.name or "",
            "prompt": r.prompt or "",
            "negative_prompt": r.negative_prompt or "",
            "steps": r.steps, "cfg_scale": r.cfg_scale,
            "sampler": r.sampler or "", "seed": r.seed,
            "model": r.model or "", "width": r.width, "height": r.height,
            "tags": r.tags or "", "note": r.note or "",
            "is_favorite": r.is_favorite, "is_pinned": r.is_pinned,
            "rating": r.rating,
        })
    json_str = json.dumps({"prompts": data}, ensure_ascii=False, indent=2)
    return StreamingResponse(
        io.BytesIO(json_str.encode("utf-8")),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=prompts_export.json"},
    )


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
    # ======== 新增：自动分类 ========
    auto_categorize: bool = False
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

def _build_prompt_query(search, tag, category_id, tag_ids, sort, order):
    """构造提示词筛选 + 排序后的查询（不含分页），供列表与"定位到已选"共用，保证排序一致。"""
    query = Prompt.select()
    if search:
        query = query.where(
            (Prompt.prompt.contains(search))
            | (Prompt.name.contains(search))
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

    # ======== 排序逻辑 ========
    # 兼容旧版 sort 参数 + 新增 order 参数
    sort_field_map = {
        "created": Prompt.created_at,
        "name": Prompt.name,
        "usage": Prompt.usage_count,
        "rating": Prompt.rating,
    }
    is_asc = (order == "asc")

    if sort == "default":
        order_list = [Prompt.is_pinned.desc(), Prompt.is_favorite.desc(), Prompt.id.desc()]
    elif sort in sort_field_map:
        field = sort_field_map[sort]
        ordered = field.asc() if is_asc else field.desc()
        order_list = [Prompt.is_pinned.desc(), ordered]
    elif sort == "oldest":
        order_list = [Prompt.is_pinned.desc(), Prompt.id.asc()]
    elif sort == "updated":
        order_list = [Prompt.is_pinned.desc(), Prompt.updated_at.desc()]
    else:
        # 默认 newest
        order_list = [Prompt.is_pinned.desc(), Prompt.id.desc()]
    # ==========================================
    return query.order_by(*order_list)


@router.get("/prompts/position", response_model=dict)
def prompt_position(
    prompt_id: int = Query(...),
    search: str = Query(""),
    tag: str = Query(""),
    category_id: Optional[int] = Query(None),
    tag_ids: Optional[str] = Query(None),
    sort: str = Query("newest"),
    order: str = Query("desc"),
):
    """返回某条提示词在给定筛选/排序下的 0-based 全局序号，用于"定位到已选"跨页跳转。"""
    query = _build_prompt_query(search, tag, category_id, tag_ids, sort, order)
    ids = [r.id for r in query]
    if prompt_id in ids:
        return {"found": True, "index": ids.index(prompt_id), "total": len(ids)}
    return {"found": False, "index": -1, "total": len(ids)}


@router.get("/prompts", response_model=dict)
def list_prompts(
    search: str = Query(""),
    tag: str = Query(""),
    category_id: Optional[int] = Query(None),
    tag_ids: Optional[str] = Query(None),
    sort: str = Query("newest"),
    order: str = Query("desc"),
    page: int = Query(1),
    page_size: int = Query(50),
):
    """搜索提示词列表，支持排序和分页"""
    query = _build_prompt_query(search, tag, category_id, tag_ids, sort, order)
    total = query.count()
    
    offset = (page - 1) * page_size
    rows = query.offset(offset).limit(page_size)

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


# ====================================================================
# Phase 2: HTMX 端点 —— 返回提示词列表的 HTML 片段
# ====================================================================

@router.get("/prompts/html")
def prompts_list_html(
    request: Request,
    search: str = Query(""),
    tag: str = Query(""),
    category_id: Optional[str] = Query(None),
    tag_ids: Optional[str] = Query(None),
    sort: str = Query("newest"),
    order: str = Query("desc"),
    page: int = Query(1),
    page_size: int = Query(50),
):
    """返回提示词列表 HTML 片段（供 HTMX 加载）"""
    query = Prompt.select()
    if search:
        query = query.where(
            (Prompt.prompt.contains(search))
            | (Prompt.name.contains(search))
            | (Prompt.tags.contains(search))
            | (Prompt.note.contains(search))
        )
    if tag:
        query = query.where(Prompt.tags.contains(tag))
    # HTMX 可能传 "null" 字符串，转为 None
    cat_id: Optional[int] = None
    if category_id and category_id not in ("null", "", "None"):
        try:
            cat_id = int(category_id)
        except (ValueError, TypeError):
            pass
    if cat_id is not None:
        query = query.join(PromptCategory).where(PromptCategory.category == cat_id)
    if tag_ids and tag_ids not in ("null", "", "None"):
        tid_list = [int(t.strip()) for t in tag_ids.split(",") if t.strip()]
        if tid_list:
            query = query.join(PromptTag).where(PromptTag.tag.in_(tid_list))

    total = query.count()

    # 排序逻辑与 JSON 接口保持一致
    is_asc = (order == "asc")
    if sort == "default":
        order_list = [Prompt.is_pinned.desc(), Prompt.is_favorite.desc(), Prompt.id.desc()]
    elif sort == "oldest":
        order_list = [Prompt.is_pinned.desc(), Prompt.id.asc()]
    elif sort == "updated":
        order_list = [Prompt.is_pinned.desc(), Prompt.updated_at.desc()]
    elif sort in ("created", "name", "usage", "rating"):
        field_map = {
            "created": Prompt.created_at,
            "name": Prompt.name,
            "usage": Prompt.usage_count,
            "rating": Prompt.rating,
        }
        field = field_map[sort]
        ordered = field.asc() if is_asc else field.desc()
        order_list = [Prompt.is_pinned.desc(), ordered]
    else:
        order_list = [Prompt.is_pinned.desc(), Prompt.id.desc()]

    offset = (page - 1) * page_size
    rows = query.order_by(*order_list).offset(offset).limit(page_size)

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
            "is_favorite": r.is_favorite,
            "is_pinned": r.is_pinned,
            "rating": r.rating,
            "usage_count": r.usage_count,
        })

    return templates.TemplateResponse(
        "prompts/list.jinja2",
        {
            "request": request,
            "prompts": prompts,
            "total": total,
            "page": page,
            "page_size": page_size,
            "search": search,
            "sort": sort,
            "category_id": category_id or "",
            "tag_ids": tag_ids or "",
            "selected_id": 0,       # 前端 JS 维护选中状态
            "selected_ids": [],
        },
    )


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
    auto_categorize = data_dict.pop("auto_categorize", False)  # 提取并移除该字段
    # 确保布尔字段有默认值
    if "is_favorite" not in data_dict:
        data_dict["is_favorite"] = False
    if "is_pinned" not in data_dict:
        data_dict["is_pinned"] = False
    if "usage_count" not in data_dict:
        data_dict["usage_count"] = 0
    # ==========================================
    r = None
    with db.atomic():
        r = Prompt.create(**data_dict)
        # 自动类型分类
        auto_classify_prompt(r.id)

        # 自动分类到"组合创作"
        if auto_categorize or "组合创作" in (data_dict.get("tags") or ""):
            # 查找或创建"组合创作"分类
            cat = Category.get_or_none(Category.name == "组合创作")
            if not cat:
                cat = Category.create(name="组合创作", color="#6366f1", parent_id=None)
            # 关联提示词到分类
            PromptCategory.get_or_create(prompt=r.id, category=cat.id)

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
    with db.atomic():
        Prompt.update(**updates).where(Prompt.id == prompt_id).execute()

        # 如果更新了 prompt 内容，重新自动分类
        if "prompt" in updates:
            auto_classify_prompt(prompt_id)

    return {"success": True}


@router.delete("/prompts/{prompt_id}")
def delete_prompt(prompt_id: int):
    """删除提示词（清理关联的分类/标签，但保留生成历史）。

    以前这里会 `GenHistory.delete()`：删一条提示词，它名下所有出图记录一起消失，
    而磁盘文件还在 —— 下次同步又把图扫回来，表现为"删不干净 + 记录反复重建"。
    现在改为只解除关联（prompt_id 置空），图片仍留在画廊。
    """
    try:
        r = Prompt.get_or_none(Prompt.id == prompt_id)
        if r is None:
            raise HTTPException(404, "提示词不存在")
        # 关联表清理 + 解除历史关联 + 删主行必须同一事务
        with db.atomic():
            pc = PromptCategory.delete().where(PromptCategory.prompt == prompt_id).execute()
            pt = PromptTag.delete().where(PromptTag.prompt == prompt_id).execute()
            gh = GenHistory.update(prompt_id=None).where(GenHistory.prompt_id == prompt_id).execute()
            r.delete_instance()
        return {
            "success": True,
            "deleted": {"prompt_categories": pc, "prompt_tags": pt, "gen_history": 0},
            "gen_history_detached": gh,
        }
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
        .where(
            (GenHistory.prompt_id == prompt_id) &
            (GenHistory.is_deleted == False)
        )
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


# ====================================================================
# 新增：提示词导入 + 批量操作
# ====================================================================

class BatchImportRequest(BaseModel):
    prompts: list[PromptCreate]


@router.post("/prompts/import")
def import_prompts(data: BatchImportRequest):
    """批量导入提示词（JSON 格式）

    修复：PromptCreate 含 prompts 表不存在的字段（如 auto_categorize），
    直接 model_dump 建库会报错，需先剥离；并复用单条创建的自动类型分类逻辑。
    """
    imported = 0
    errors = []
    # prompts 表不存在、需在建库前剔除的字段
    non_columns = {"auto_categorize"}
    for i, item in enumerate(data.prompts):
        try:
            d = item.model_dump()
            for k in non_columns:
                d.pop(k, None)
            with db.atomic():
                r = Prompt.create(**d)
                # 与单条创建保持一致，自动归入 组合/单项/零散
                auto_classify_prompt(r.id)
            imported += 1
        except Exception as e:
            errors.append({"index": i, "error": str(e)})
    msg = f"成功导入 {imported} 条"
    if errors:
        msg += f"，{len(errors)} 条失败"
    return {"success": True, "imported": imported, "errors": errors, "message": msg}


class BatchIdsRequest(BaseModel):
    ids: list[int]


@router.post("/prompts/batch_delete")
def batch_delete_prompts(data: BatchIdsRequest):
    """批量删除提示词（连带清理关联关系）"""
    ids = data.ids
    if not ids:
        raise HTTPException(400, "ids 不能为空")
    with db.atomic():
        PromptCategory.delete().where(PromptCategory.prompt.in_(ids)).execute()
        PromptTag.delete().where(PromptTag.prompt.in_(ids)).execute()
        GenHistory.delete().where(GenHistory.prompt_id.in_(ids)).execute()
        deleted = Prompt.delete().where(Prompt.id.in_(ids)).execute()
    return {"success": True, "deleted": deleted}


@router.post("/prompts/batch_favorite")
def batch_favorite_prompts(data: BatchIdsRequest, favorite: bool = Query(True)):
    """批量设置/取消收藏"""
    ids = data.ids
    if not ids:
        raise HTTPException(400, "ids 不能为空")
    Prompt.update(is_favorite=favorite).where(Prompt.id.in_(ids)).execute()
    return {"success": True, "updated": len(ids), "is_favorite": favorite}
