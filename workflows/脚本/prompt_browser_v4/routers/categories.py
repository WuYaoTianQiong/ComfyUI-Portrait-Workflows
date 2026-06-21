"""分类管理 API"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List

from models import Category, PromptCategory, Prompt, db

router = APIRouter(tags=["分类"])


# ---------- Pydantic schemas ----------
class CategoryCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None
    color: str = "#6366f1"
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    parent_id: Optional[int] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None


# ---------- Routes ----------
@router.get("/categories", response_model=dict)
def list_categories(
    parent_id: Optional[int] = Query(None, description="父分类 ID，NULL=顶级分类"),
    tree: bool = Query(False, description="是否返回树形结构"),
):
    """获取分类列表（支持树形结构）"""
    if tree:
        # 返回树形结构
        all_cats = list(Category.select().order_by(Category.sort_order, Category.id))
        tree_data = build_category_tree(all_cats)
        return {"categories": tree_data}
    else:
        # 返回扁平列表
        query = Category.select()
        if parent_id is not None:
            query = query.where(Category.parent_id == parent_id)
        else:
            # 默认只返回顶级分类
            query = query.where(Category.parent_id.is_null())
        
        cats = []
        for c in query.order_by(Category.sort_order, Category.id):
            cats.append({
                "id": c.id,
                "name": c.name,
                "parent_id": c.parent_id,
                "color": c.color,
                "sort_order": c.sort_order,
                "prompt_count": PromptCategory.select().where(PromptCategory.category_id == c.id).count(),
            })
        return {"categories": cats}


def build_category_tree(categories: list, parent_id: Optional[int] = None) -> list:
    """递归构建分类树"""
    tree = []
    for c in categories:
        if c.parent_id == parent_id:
            node = {
                "id": c.id,
                "name": c.name,
                "parent_id": c.parent_id,
                "color": c.color,
                "sort_order": c.sort_order,
                "prompt_count": PromptCategory.select().where(PromptCategory.category_id == c.id).count(),
                "children": build_category_tree(categories, c.id),
            }
            tree.append(node)
    return tree


@router.post("/categories", status_code=201)
def create_category(data: CategoryCreate):
    """创建分类"""
    try:
        c = Category.create(**data.model_dump())
        return {"success": True, "id": c.id}
    except Exception as e:
        raise HTTPException(400, f"创建失败: {str(e)}")


@router.put("/categories/{cat_id}")
def update_category(cat_id: int, data: CategoryUpdate):
    """更新分类"""
    c = Category.get_or_none(Category.id == cat_id)
    if c is None:
        raise HTTPException(404, "分类不存在")
    
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, "没有需要更新的字段")
    
    Category.update(**updates).where(Category.id == cat_id).execute()
    return {"success": True}


@router.delete("/categories/{cat_id}")
def delete_category(cat_id: int):
    """删除分类（同时删除子分类和关联关系）"""
    c = Category.get_or_none(Category.id == cat_id)
    if c is None:
        raise HTTPException(404, "分类不存在")
    
    # 删除子分类
    delete_children_recursive(cat_id)
    
    # 删除自身
    c.delete_instance(recursive=False)
    return {"success": True}


def delete_children_recursive(cat_id: int):
    """递归删除子分类"""
    children = Category.select().where(Category.parent_id == cat_id)
    for child in children:
        delete_children_recursive(child.id)
        child.delete_instance(recursive=False)


@router.post("/categories/{cat_id}/prompts/{prompt_id}")
def add_prompt_to_category(cat_id: int, prompt_id: int):
    """将提示词添加到分类"""
    c = Category.get_or_none(Category.id == cat_id)
    if c is None:
        raise HTTPException(404, "分类不存在")
    
    p = Prompt.get_or_none(Prompt.id == prompt_id)
    if p is None:
        raise HTTPException(404, "提示词不存在")
    
    # 检查是否已关联
    exists = PromptCategory.get_or_none(
        (PromptCategory.prompt == prompt_id) & (PromptCategory.category == cat_id)
    )
    if exists:
        return {"success": True, "message": "已关联"}
    
    PromptCategory.create(prompt=prompt_id, category=cat_id)
    return {"success": True}


@router.delete("/categories/{cat_id}/prompts/{prompt_id}")
def remove_prompt_from_category(cat_id: int, prompt_id: int):
    """从分类中移除提示词"""
    pc = PromptCategory.get_or_none(
        (PromptCategory.prompt == prompt_id) & (PromptCategory.category == cat_id)
    )
    if pc is None:
        raise HTTPException(404, "关联关系不存在")
    
    pc.delete_instance()
    return {"success": True}
