"""通用 CRUD 基类路由 —— 消除 Tags / Categories / Fragments 等模块的重复代码

用法:
    1. 直接实例化标准 CRUD:
        router = BaseCRUDRouter(
            model_class=Tag, prefix="tags", tag="标签",
            create_schema=TagCreate, update_schema=TagUpdate,
        ).router

    2. 子类化扩展:
        class TagRouter(BaseCRUDRouter):
            def custom_serialize(self, obj) -> dict:
                return { "id": obj.id, "name": obj.name, ... }
            def on_before_delete(self, item_id: int):
                PromptTag.delete().where(PromptTag.tag == item_id).execute()
        router = TagRouter(...).router
"""

from typing import Any, Optional, Type, Callable

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from peewee import Model as PeeweeModel, fn


class BaseCRUDRouter:
    """为 Peewee 模型一键生成 CRUD 路由。"""

    def __init__(
        self,
        model_class: Type[PeeweeModel],
        prefix: str,
        tag: str,
        *,
        search_fields: Optional[list] = None,
        default_sort: Optional[list] = None,
        create_schema: Optional[Type[BaseModel]] = None,
        update_schema: Optional[Type[BaseModel]] = None,
        # 跳过默认路由
        skip_list: bool = False,
        skip_get: bool = False,
        skip_create: bool = False,
        skip_update: bool = False,
        skip_delete: bool = False,
    ):
        self.model = model_class
        self.prefix = prefix
        self.tag = tag
        self.search_fields = search_fields or []
        self.default_sort = default_sort or [model_class.id.desc()]
        self.create_schema = create_schema
        self.update_schema = update_schema

        self.router = APIRouter(tags=[tag])
        if not skip_list:
            self._register_list()
        if not skip_get:
            self._register_get()
        if not skip_create:
            self._register_create()
        if not skip_update:
            self._register_update()
        if not skip_delete:
            self._register_delete()

    # ========== 可重写的钩子 ==========

    def custom_serialize(self, obj) -> dict:
        """序列化单个对象。重写此方法以自定义返回字段。"""
        result = {}
        for field_name in obj._meta.sorted_field_names:
            val = getattr(obj, field_name)
            if hasattr(val, "isoformat"):
                val = str(val)
            result[field_name] = val
        return result

    def custom_list(self, search: str = "", page: int = 1, page_size: int = 100) -> tuple:
        """自定义列表查询。返回 (items_dict_list, total_count)。
        默认实现: 搜索 + 分页 + 排序。重写以实现自定义查询逻辑。"""
        query = self.model.select()
        if search and self.search_fields:
            from functools import reduce
            import operator
            conditions = [field.contains(search) for field in self.search_fields]
            if conditions:
                query = query.where(reduce(operator.or_, conditions))
        total = query.count()
        rows = query.order_by(*self.default_sort).offset((page - 1) * page_size).limit(page_size)
        return [self.custom_serialize(r) for r in rows], total

    def on_before_create(self, data: BaseModel) -> dict:
        """创建前钩子，返回要写入的数据 dict。"""
        return data.model_dump()

    def on_before_update(self, item_id: int, data: BaseModel) -> dict:
        """更新前钩子，返回要更新的字段 dict。"""
        return data.model_dump(exclude_unset=True)

    def on_before_delete(self, item_id: int):
        """删除前钩子，用于清理关联数据。"""
        pass

    # ========== 内部注册方法 ==========

    def _register_list(self):
        @self.router.get(f"/{self.prefix}")
        def list_items(
            search: str = Query(""),
            page: int = Query(1, ge=1),
            page_size: int = Query(100, ge=1, le=1000),
        ):
            items, total = self.custom_list(search=search, page=page, page_size=page_size)
            return {"items": items, "total": total, "page": page, "page_size": page_size}

    def _register_get(self):
        @self.router.get(f"/{self.prefix}/{{item_id}}")
        def get_item(item_id: int):
            obj = self.model.get_or_none(self.model.id == item_id)
            if obj is None:
                raise HTTPException(404, f"{self.tag}不存在")
            return {"item": self.custom_serialize(obj)}

    def _register_create(self):
        if not self.create_schema:
            return

        @self.router.post(f"/{self.prefix}", status_code=201)
        def create_item(data: self.create_schema):  # type: ignore
            try:
                values = self.on_before_create(data)
                obj = self.model.create(**values)
                return {"success": True, "id": obj.id}
            except Exception as e:
                raise HTTPException(400, f"创建失败: {e}")

    def _register_update(self):
        if not self.update_schema:
            return

        @self.router.put(f"/{self.prefix}/{{item_id}}")
        def update_item(item_id: int, data: self.update_schema):  # type: ignore
            obj = self.model.get_or_none(self.model.id == item_id)
            if obj is None:
                raise HTTPException(404, f"{self.tag}不存在")

            updates = self.on_before_update(item_id, data)
            if not updates:
                raise HTTPException(400, "没有需要更新的字段")

            self.model.update(**updates).where(self.model.id == item_id).execute()
            return {"success": True}

    def _register_delete(self):
        @self.router.delete(f"/{self.prefix}/{{item_id}}")
        def delete_item(item_id: int):
            obj = self.model.get_or_none(self.model.id == item_id)
            if obj is None:
                raise HTTPException(404, f"{self.tag}不存在")

            self.on_before_delete(item_id)
            self.model.delete_by_id(item_id)
            return {"success": True}
