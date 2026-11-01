"""提示词 CRUD + 标签"""
import io
import json
import traceback
from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from app.schemas import PromptDetail, PromptListResponse
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

from app.models import (
    Prompt, Image, db, Category, Tag, EntityTag,
    PromptCategory, PromptTag, auto_classify_prompt,
)
from app.services.fragment_syntax import parse
from app.services.image_meta import get_image_metadata
from app.services.tagging import sync_prompt_tags

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




# ---------- Routes ----------

def _fragment_matched_ids(fragment_types: str, fragment_match: str, fragment_kw: str) -> list[int] | None:
    """按正文里的【类型】结构筛出提示词 id —— 碎片级检索（返回 None = 未启用该筛选）。

    为什么在 Python 里算而不是写 SQL：碎片是 `【类型】内容` 的**解析结果**，库里没有
    `prompt_fragments` 索引表；300+ 条提示词全表解析是毫秒级，而建表意味着 create/update/
    import/批量替换所有写入路径都要维护索引，成本远高于收益。真正到万级再换索引表。

    · `fragment_types`：逗号分隔的类型名
    · `fragment_match`：has=含有全部所选类型（默认）；only=出现过的类型集合恰好等于所选
      （这才是"只有某一段描写的提示词"，1-3 类混在一起的"单项提示词"分类给不出这个粒度）
    · `fragment_kw`：关键词必须**落在碎片正文里**（不是整段 prompt 的任意位置），
      且指定了类型时它得落在所选类型的那一片里 —— 否则搜一个词会把该提示词的所有碎片都当成命中
    """
    types = [t.strip() for t in (fragment_types or "").replace("，", ",").split(",") if t.strip()]
    keyword = (fragment_kw or "").strip().lower()
    if not types and not keyword:
        return None

    wanted = set(types)
    matched: list[int] = []
    for row in Prompt.select(Prompt.id, Prompt.prompt):
        fragments = parse(row.prompt)
        if not fragments:
            continue
        present = {f["type"] for f in fragments}
        if wanted:
            if fragment_match == "only":
                if present != wanted:
                    continue
            elif not wanted <= present:
                continue
        if keyword:
            hits = [f for f in fragments if keyword in (f["content"] or "").lower()]
            if not hits:
                continue
            if wanted and not any(f["type"] in wanted for f in hits):
                continue
        matched.append(row.id)
    return matched


def _build_prompt_query(
    search, tag, category_id, tag_ids, sort, order, tag_match="all",
    fragment_types="", fragment_match="has", fragment_kw="",
):
    """构造提示词筛选 + 排序后的查询（不含分页），供列表、定位、批量替换共用，保证三者一致。"""
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

    # 碎片级筛选：没有索引表，先在内存里算 id 集合再回填条件
    frag_ids = _fragment_matched_ids(fragment_types, fragment_match, fragment_kw)
    if frag_ids is not None:
        # 空集合要显式变成假条件：peewee 对各版本空 in_ 的生成行为不一致
        query = query.where(Prompt.id.in_(frag_ids) if frag_ids else (Prompt.id < 0))

    # ======== Phase 2: 添加分类和标签筛选 ========
    # 按分类筛选
    if category_id is not None:
        query = query.join(PromptCategory).where(PromptCategory.category == category_id)

    # 按标签筛选（多选）：tag_match=all 取交集，any 取并集
    if tag_ids:
        tag_id_list = [int(tid.strip()) for tid in tag_ids.split(",") if tid.strip()]
        if tag_id_list:
            # 用子查询而非 join：join 会让一个提示词因多个标签出现多行，total 被放大
            def _has(tid):
                return Prompt.id << EntityTag.select(EntityTag.entity_id).where(
                    (EntityTag.entity_type == "prompt") & (EntityTag.tag == tid)
                )

            if tag_match == "any":
                query = query.where(
                    Prompt.id
                    << EntityTag.select(EntityTag.entity_id).where(
                        (EntityTag.entity_type == "prompt")
                        & (EntityTag.tag.in_(tag_id_list))
                    )
                )
            else:
                for tid in tag_id_list:
                    query = query.where(_has(tid))
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
    tag_match: str = Query("all"),
    fragment_types: str = Query("", description="碎片类型，逗号分隔"),
    fragment_match: str = Query("has", description="has=含有, only=仅含"),
    fragment_kw: str = Query("", description="关键词需命中碎片正文"),
):
    """返回某条提示词在给定筛选/排序下的 0-based 全局序号，用于"定位到已选"跨页跳转。"""
    query = _build_prompt_query(
        search, tag, category_id, tag_ids, sort, order, tag_match,
        fragment_types, fragment_match, fragment_kw,
    )
    ids = [r.id for r in query]
    if prompt_id in ids:
        return {"found": True, "index": ids.index(prompt_id), "total": len(ids)}
    return {"found": False, "index": -1, "total": len(ids)}


@router.get("/prompts", response_model=PromptListResponse)
def list_prompts(
    search: str = Query(""),
    tag: str = Query(""),
    category_id: Optional[int] = Query(None),
    tag_ids: Optional[str] = Query(None),
    sort: str = Query("newest"),
    order: str = Query("desc"),
    page: int = Query(1),
    page_size: int = Query(50),
    tag_match: str = Query("all", description="多标签语义：all=交集, any=并集"),
    fragment_types: str = Query("", description="碎片类型，逗号分隔（如 人物面部,人物服饰）"),
    fragment_match: str = Query("has", description="has=含有所选类型, only=仅含所选类型"),
    fragment_kw: str = Query("", description="关键词需命中碎片正文"),
):
    """搜索提示词列表，支持排序和分页"""
    query = _build_prompt_query(
        search, tag, category_id, tag_ids, sort, order, tag_match,
        fragment_types, fragment_match, fragment_kw,
    )
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


@router.get("/prompts/full")
def list_prompts_full(
    search: str = Query(""),
    category_id: Optional[int] = Query(None),
    tag_ids: Optional[str] = Query(None),
    tag_match: str = Query("all"),
    fragment_types: str = Query(""),
    fragment_match: str = Query("has"),
    fragment_kw: str = Query(""),
    ids: str = Query(""),
):
    """按当前筛选（或指定 ids）返回提示词全文（批量替换碎片用，不分页）。

    列表接口只给 60 字预览，批量替换必须拿到完整正文；这里复用与列表完全
    相同的筛选条件（含碎片筛选），避免"看到的和替换的不是同一批"。
    `ids` 用于"只替换左侧已勾选的提示词"——勾选可能跨页/跨筛选，不能再套筛选。
    """
    if ids:
        id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
        query = Prompt.select().where(Prompt.id.in_(id_list)).order_by(Prompt.id)
    else:
        query = _build_prompt_query(
            search, "", category_id, tag_ids, "newest", "desc", tag_match,
            fragment_types, fragment_match, fragment_kw,
        )
    rows = list(query)
    return {
        "items": [
            {
                "id": r.id,
                "name": r.name or "",
                "prompt": r.prompt or "",
                "negative_prompt": r.negative_prompt or "",
                "seed": r.seed,
                "steps": r.steps,
                "cfg_scale": r.cfg_scale,
                "sampler": r.sampler or "",
                "model": r.model or "",
                "tags": r.tags or "",
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.get("/prompts/{prompt_id}", response_model=PromptDetail)
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

    # 获取关联的标签（以 entity_tags 为准）
    tags = [
        {"id": row.id, "name": row.name, "color": row.color}
        for row in Tag.select(Tag.id, Tag.name, Tag.color)
        .join(EntityTag, on=(EntityTag.tag == Tag.id))
        .where((EntityTag.entity_type == "prompt") & (EntityTag.entity_id == prompt_id))
    ]
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
        # 标签文本 → entity_tags（文本是唯一事实来源，写文本就要同步关联表）
        sync_prompt_tags(r.id, data_dict.get("tags"))

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
        # 标签文本变了就重算关联表，否则标签筛选会与界面显示脱节
        if "tags" in updates:
            sync_prompt_tags(prompt_id, updates.get("tags"))

    return {"success": True}


@router.delete("/prompts/{prompt_id}")
def delete_prompt(prompt_id: int):
    """删除提示词（清理关联的分类/标签，但保留生成历史）。

    以前这里会 `Image.delete()`：删一条提示词，它名下所有出图记录一起消失，
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
            # entity_tags 是当前唯一的读路径，必须一起清，否则留下悬空关联
            EntityTag.delete().where(
                (EntityTag.entity_type == "prompt") & (EntityTag.entity_id == prompt_id)
            ).execute()
            gh = Image.update(prompt_id=None).where(Image.prompt_id == prompt_id).execute()
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
        Image
        .select()
        .where(
            (Image.prompt_id == prompt_id) &
            (Image.is_deleted == False)
        )
        .order_by(Image.id.desc())
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
                # 与单条创建保持一致：文本标签是唯一事实来源，写入时同步关联表
                sync_prompt_tags(r.id, d.get("tags"))
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
        EntityTag.delete().where(
            (EntityTag.entity_type == "prompt") & (EntityTag.entity_id.in_(ids))
        ).execute()
        # 与单条删除保持一致：只解除关联，不删出图记录（旧实现这里 Image.delete()，
        # 批量删提示词会把画廊里对应的图片记录一起抹掉）
        Image.update(prompt_id=None).where(Image.prompt_id.in_(ids)).execute()
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
