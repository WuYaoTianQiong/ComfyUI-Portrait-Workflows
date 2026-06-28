"""模板管理 API —— 引用式模板，碎片实时从原始提示词解析"""
import re
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from models import Template, TemplateFragment, Prompt, Category, db

router = APIRouter(tags=["模板"])

# ---------- helpers ----------

FRAGMENT_TYPES = ["人物外貌", "姿态动作", "服装配饰", "场景背景", "风格技术"]


def _extract_fragment(prompt_text: str, fragment_type: str) -> str:
    """从 prompt 文本中提取指定类型的碎片内容"""
    if not prompt_text:
        return ""
    # 支持 【类型】内容 格式
    pattern = r'【' + re.escape(fragment_type) + r'】\s*(.*?)(?=\n【|$)'
    m = re.search(pattern, prompt_text, re.DOTALL)
    return m.group(1).strip() if m else ""


def _resolve_fragment(prompt_id: int | None, fragment_type: str, cached: str) -> dict:
    """解析碎片：优先从提示词实时提取，兜底用缓存"""
    if prompt_id:
        p = Prompt.get_or_none(Prompt.id == prompt_id)
        if p and p.prompt:
            live = _extract_fragment(p.prompt, fragment_type)
            if live:
                return {"content": live, "source_exists": True, "source_name": p.name or f"#{p.id}"}

    # 来源不可用 → 返回缓存
    return {
        "content": cached,
        "source_exists": False,
        "source_name": "来源已删除" if prompt_id else "自定义内容",
    }


def _template_to_dict(t: Template) -> dict:
    fragments = []
    for tf in TemplateFragment.select().where(TemplateFragment.template == t.id).order_by(TemplateFragment.sort_order):
        resolved = _resolve_fragment(tf.prompt_id, tf.fragment_type, tf.cached_content)
        fragments.append({
            "id": tf.id,
            "prompt_id": tf.prompt_id,
            "fragment_type": tf.fragment_type,
            "sort_order": tf.sort_order,
            "cached_content": tf.cached_content,
            "content": resolved["content"],
            "source_exists": resolved["source_exists"],
            "source_name": resolved["source_name"],
        })
    return {
        "id": t.id,
        "name": t.name,
        "category_id": t.category_id,
        "fragments": fragments,
        "fragment_count": len(fragments),
        "created_at": str(t.created_at) if t.created_at else "",
        "updated_at": str(t.updated_at) if t.updated_at else "",
    }


# ---------- pydantic schemas ----------

class FragmentRef(BaseModel):
    prompt_id: int
    fragment_type: str


class TemplateCreate(BaseModel):
    name: str
    category_id: Optional[int] = None
    fragments: list[FragmentRef]


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    category_id: Optional[int] = None
    fragments: Optional[list[FragmentRef]] = None


# ---------- routes ----------

@router.get("/templates", response_model=dict)
def list_templates(category_id: Optional[int] = Query(None)):
    """获取模板列表，可选按分类筛选"""
    query = Template.select()
    if category_id is not None:
        query = query.where(Template.category == category_id)
    rows = query.order_by(Template.updated_at.desc())
    return {"templates": [_template_to_dict(t) for t in rows]}


@router.get("/templates/{template_id}", response_model=dict)
def get_template(template_id: int):
    """获取单个模板详情（碎片实时解析）"""
    t = Template.get_or_none(Template.id == template_id)
    if t is None:
        raise HTTPException(404, "模板不存在")
    return {"template": _template_to_dict(t)}


@router.get("/templates/{template_id}/resolve", response_model=dict)
def resolve_template(template_id: int):
    """手动重新解析模板碎片（获取实时内容）"""
    t = Template.get_or_none(Template.id == template_id)
    if t is None:
        raise HTTPException(404, "模板不存在")
    return {"template": _template_to_dict(t)}


@router.post("/templates", status_code=201)
def create_template(data: TemplateCreate):
    """创建模板（自动保存碎片缓存快照）"""
    try:
        t = Template.create(
            name=data.name,
            category=data.category_id if data.category_id else None,
        )
        for i, fr in enumerate(data.fragments):
            # 提取缓存快照
            cached = ""
            if fr.prompt_id:
                p = Prompt.get_or_none(Prompt.id == fr.prompt_id)
                if p:
                    cached = _extract_fragment(p.prompt, fr.fragment_type)
            TemplateFragment.create(
                template=t.id,
                prompt=fr.prompt_id if fr.prompt_id else None,
                fragment_type=fr.fragment_type,
                cached_content=cached,
                sort_order=i,
            )
        return {"success": True, "id": t.id}
    except Exception as e:
        raise HTTPException(400, f"创建失败: {e}")


@router.put("/templates/{template_id}")
def update_template(template_id: int, data: TemplateUpdate):
    """更新模板（名称/分类/碎片）"""
    t = Template.get_or_none(Template.id == template_id)
    if t is None:
        raise HTTPException(404, "模板不存在")

    if data.name is not None:
        t.name = data.name
    if data.category_id is not None:
        t.category = data.category_id
    t.updated_at = datetime.now()
    t.save()

    if data.fragments is not None:
        # 删除旧碎片
        TemplateFragment.delete().where(TemplateFragment.template == template_id).execute()
        # 插入新碎片
        for i, fr in enumerate(data.fragments):
            cached = ""
            if fr.prompt_id:
                p = Prompt.get_or_none(Prompt.id == fr.prompt_id)
                if p:
                    cached = _extract_fragment(p.prompt, fr.fragment_type)
            TemplateFragment.create(
                template=template_id,
                prompt=fr.prompt_id if fr.prompt_id else None,
                fragment_type=fr.fragment_type,
                cached_content=cached,
                sort_order=i,
            )
    return {"success": True}


@router.delete("/templates/{template_id}")
def delete_template(template_id: int):
    """删除模板"""
    t = Template.get_or_none(Template.id == template_id)
    if t is None:
        raise HTTPException(404, "模板不存在")
    # 级联删除碎片
    TemplateFragment.delete().where(TemplateFragment.template == template_id).execute()
    t.delete_instance()
    return {"success": True}


@router.get("/templates/as_items", response_model=dict)
def list_templates_as_prompt_items():
    """返回模板列表，格式兼容 prompt 列表前端渲染"""
    rows = Template.select().order_by(Template.updated_at.desc())
    items = []
    for t in rows:
        fragments = list(TemplateFragment.select().where(TemplateFragment.template == t.id).order_by(TemplateFragment.sort_order))
        # 组装预览文本
        preview_parts = []
        has_missing = False
        for tf in fragments:
            resolved = _resolve_fragment(tf.prompt_id, tf.fragment_type, tf.cached_content)
            preview_parts.append(f"【{tf.fragment_type}】{resolved['content'][:40]}")
            if not resolved["source_exists"]:
                has_missing = True

        prompt_preview = " · ".join(preview_parts) if preview_parts else "(空模板)"
        if len(prompt_preview) > 120:
            prompt_preview = prompt_preview[:120] + "..."

        items.append({
            "id": t.id,
            "name": t.name or "",
            "prompt_preview": prompt_preview,
            "tags": "📦 组合模板",
            "_is_template": True,
            "_has_missing": has_missing,
            "fragment_count": len(fragments),
            "created_at": str(t.created_at) if t.created_at else "",
            "steps": None,
            "sampler": "",
            "model": "",
            "is_favorite": False,
            "is_pinned": False,
            "rating": None,
            "usage_count": 0,
        })

    return {"prompts": items, "total": len(items), "page": 1, "page_size": 999}


# ---------- 从 localStorage 迁移 ----------

@router.post("/templates/migrate")
def migrate_templates():
    """将浏览器 localStorage 中的模板一次性导入数据库"""
    # 这个 API 由前端调用，前端的旧模板数据通过请求体传入
    return {"success": True, "message": "请使用 POST /templates/batch_import"}


class BatchImportItem(BaseModel):
    name: str
    fragments: list[FragmentRef]


class BatchImportRequest(BaseModel):
    items: list[BatchImportItem]


@router.post("/templates/batch_import")
def batch_import_templates(data: BatchImportRequest):
    """批量从 localStorage 导入旧模板"""
    imported = 0
    for item in data.items:
        try:
            t = Template.create(name=item.name)
            for i, fr in enumerate(item.fragments):
                cached = ""
                if fr.prompt_id:
                    p = Prompt.get_or_none(Prompt.id == fr.prompt_id)
                    if p:
                        cached = _extract_fragment(p.prompt, fr.fragment_type)
                TemplateFragment.create(
                    template=t.id,
                    prompt=fr.prompt_id if fr.prompt_id else None,
                    fragment_type=fr.fragment_type,
                    cached_content=cached,
                    sort_order=i,
                )
            imported += 1
        except Exception:
            pass
    return {"success": True, "imported": imported}
