"""标签解析与关联维护 —— entity_tags 的唯一写入口。

背景：标签体系原本三轨并行：

1. `prompts.tags`：逗号分隔 **文本**，既是编辑入口也是搜索条件；
2. `prompt_tags`：提示词与标签的关联表；
3. `image_tags`：图片与标签的关联表（另有"经来源提示词继承"的第二条路径）。

三套数据互不同步，最终线上出现「136 个标签、0 条关联」——标签筛选、侧栏计数
全部失效，而且没有任何报错。现在统一为：

- **写入口唯一**：UI 仍在编辑 `prompts.tags` 文本，后端写完文本立刻调用
  `sync_prompt_tags()` 把它解析进 `entity_tags`（阶段内双写，前端无需改动）；
- **读入口唯一**：所有筛选 / 计数 / 详情只查 `entity_tags`，
  `prompt_tags` / `image_tags` 降级为只读的历史快照；
- **拆分规则**：只按中英文逗号与分号拆，**不拆空格** —— 线上确实存在
  `Moody Photography` 这类带空格的标签；`f/1.8` 这类光圈值也属于标签本身。
"""

from __future__ import annotations

import re

from peewee import IntegrityError

from app.models import EntityTag, Prompt, Tag, db

# 逗号（中/英）与分号（中/英）。刻意不含空格：会切坏 "Moody Photography"。
_TAG_SEP_RE = re.compile(r"[,，;；]")

ENTITY_PROMPT = "prompt"
ENTITY_IMAGE = "image"

#: 保留标签：标记「多图拼贴 / 双人 / 参考图指令」等不适合单图随机合成的提示词。
#: 随机配方接口按它过滤；手动碎片弹层只展示警告，不隐藏。
RANDOM_EXCLUDE_TAG = "随机排除"

#: 手动碎片弹层展示的警告文案（标签口径：多图 / 双人 / 服装不完整等）。
RANDOM_EXCLUDE_WARNING = "不适合单图随机合成"


def split_tags(text: str | None) -> list[str]:
    """把标签文本拆成去重、保序的标签名列表。"""
    if not text:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for part in _TAG_SEP_RE.split(text):
        name = part.strip()
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def get_or_create_tag(name: str) -> Tag:
    """按名称取标签，没有则创建。并发下依赖 name 的唯一约束兜底。"""
    name = name.strip()
    tag = Tag.get_or_none(Tag.name == name)
    if tag is not None:
        return tag
    try:
        return Tag.create(name=name)
    except IntegrityError:
        return Tag.get(Tag.name == name)


def entity_tag_ids(entity_type: str, entity_id: int) -> list[int]:
    return [
        row.tag_id
        for row in EntityTag.select(EntityTag.tag)
        .where((EntityTag.entity_type == entity_type) & (EntityTag.entity_id == entity_id))
    ]


def prompt_tag_ids(prompt_id: int) -> list[int]:
    return entity_tag_ids(ENTITY_PROMPT, prompt_id)


def image_tag_ids(image_id: int, prompt_id: int | None = None) -> list[int]:
    """图片的标签：直接打在图片上的 + 经来源提示词继承的（并集去重）。

    "继承"是只读语义：来源提示词后来新增的标签，图片立刻能看到；但图片自己
    多打的标签不会回流到提示词。
    """
    result = set(entity_tag_ids(ENTITY_IMAGE, image_id))
    if prompt_id:
        result.update(entity_tag_ids(ENTITY_PROMPT, prompt_id))
    return sorted(result)


def _resolve_names(text: str | None) -> tuple[list[str], set[int]]:
    names: list[str] = []
    wanted: set[int] = set()
    for name in split_tags(text):
        tag = get_or_create_tag(name)
        wanted.add(tag.id)
        names.append(tag.name)
    return names, wanted


def _resolve_ids(tag_ids) -> tuple[list[str], set[int]]:
    ids: list[int] = []
    for raw in tag_ids or []:
        tag_id = int(raw)
        if tag_id not in ids:
            ids.append(tag_id)
    if not ids:
        return [], set()
    rows = {t.id: t.name for t in Tag.select().where(Tag.id.in_(ids))}
    missing = [tag_id for tag_id in ids if tag_id not in rows]
    if missing:
        raise ValueError(f"标签不存在: {missing}")
    return [rows[tag_id] for tag_id in ids], set(ids)


def _adjust_usage(tag_ids, delta: int) -> None:
    for tag_id in tag_ids:
        if delta > 0:
            db.execute_sql(
                "UPDATE tags SET usage_count = COALESCE(usage_count, 0) + 1 WHERE id = ?",
                (tag_id,),
            )
        else:
            db.execute_sql(
                "UPDATE tags SET usage_count = CASE WHEN COALESCE(usage_count, 0) > 0 "
                "THEN COALESCE(usage_count, 0) - 1 ELSE 0 END WHERE id = ?",
                (tag_id,),
            )


def sync_prompt_tags(
    prompt_id: int, text: str | None = None, tag_ids=None,
) -> dict:
    """把提示词的标签关联设成给定集合，并回写 `prompts.tags` 只读缓存。

    - `tag_ids` 优先：UI 走标签 ID 时不再经过文本解析；
    - `text` 兼容旧调用：解析标签名并自动创建；
    - 无论哪条路径，`entity_tags` 都是唯一事实来源，文本只是派生缓存。
    """
    if tag_ids is not None:
        names, wanted = _resolve_ids(tag_ids)
    else:
        names, wanted = _resolve_names(text)

    current = set(prompt_tag_ids(prompt_id))
    to_add = wanted - current
    to_remove = current - wanted

    with db.atomic():
        for tag_id in to_add:
            EntityTag.get_or_create(
                entity_type=ENTITY_PROMPT, entity_id=prompt_id, tag=tag_id
            )
        if to_remove:
            EntityTag.delete().where(
                (EntityTag.entity_type == ENTITY_PROMPT)
                & (EntityTag.entity_id == prompt_id)
                & (EntityTag.tag.in_(list(to_remove)))
            ).execute()
        Prompt.update(tags=", ".join(names)).where(Prompt.id == prompt_id).execute()
        if to_add:
            _adjust_usage(to_add, +1)
        if to_remove:
            _adjust_usage(to_remove, -1)

    return {
        "added": len(to_add), "removed": len(to_remove), "text": ", ".join(names),
    }


def set_prompt_tags_by_ids(prompt_id: int, tag_ids) -> dict:
    return sync_prompt_tags(prompt_id, tag_ids=tag_ids)


def _rebuild_prompt_tag_texts(prompt_ids) -> int:
    """按 entity_tags 重写这些提示词的标签缓存（改名/删标签后调用）。"""
    changed = 0
    for prompt_id in prompt_ids:
        names = [
            row.name
            for row in Tag.select(Tag.name)
            .join(EntityTag, on=(EntityTag.tag == Tag.id))
            .where(
                (EntityTag.entity_type == ENTITY_PROMPT)
                & (EntityTag.entity_id == prompt_id)
            )
            .order_by(EntityTag.id)
        ]
        Prompt.update(tags=", ".join(names)).where(Prompt.id == prompt_id).execute()
        changed += 1
    return changed


def rename_tag(tag_id: int, new_name: str) -> int:
    """重命名标签。关联表存的是 id，改名天然全量生效；只需重建文本缓存。"""
    new_name = (new_name or "").strip()
    if not new_name:
        raise ValueError("标签名不能为空")
    if _TAG_SEP_RE.search(new_name):
        raise ValueError("标签名不能包含逗号或分号")
    tag = Tag.get_or_none(Tag.id == tag_id)
    if tag is None:
        raise ValueError("标签不存在")
    if tag.name == new_name:
        return 0
    if Tag.get_or_none(Tag.name == new_name) is not None:
        raise ValueError("标签已存在")
    affected = [
        row.entity_id
        for row in EntityTag.select(EntityTag.entity_id).where(
            (EntityTag.entity_type == ENTITY_PROMPT) & (EntityTag.tag == tag_id)
        )
    ]
    with db.atomic():
        Tag.update(name=new_name).where(Tag.id == tag_id).execute()
        return _rebuild_prompt_tag_texts(affected)


def delete_tag_with_refs(tag_id: int) -> int:
    """删除标签；关联与文本缓存都按 id 清理，不再扫描全库文本。"""
    tag = Tag.get_or_none(Tag.id == tag_id)
    if tag is None:
        raise ValueError("标签不存在")
    affected = [
        row.entity_id
        for row in EntityTag.select(EntityTag.entity_id).where(
            (EntityTag.entity_type == ENTITY_PROMPT) & (EntityTag.tag == tag_id)
        )
    ]
    with db.atomic():
        EntityTag.delete().where(EntityTag.tag == tag_id).execute()
        tag.delete_instance(recursive=False)
        return _rebuild_prompt_tag_texts(affected)


def _current_tag_ids(prompt_id: int) -> list[int]:
    return list(
        EntityTag.select(EntityTag.tag)
        .where(
            (EntityTag.entity_type == ENTITY_PROMPT)
            & (EntityTag.entity_id == prompt_id)
        )
        .order_by(EntityTag.id)
        .scalars()
    )


def add_prompt_tag_by_name(prompt_id: int, name: str) -> bool:
    """追加标签：先写关联，再按关联回写文本缓存。"""
    name = (name or "").strip()
    if not name:
        return False
    if Prompt.get_or_none(Prompt.id == prompt_id) is None:
        return False
    tag = get_or_create_tag(name)
    current = _current_tag_ids(prompt_id)
    if tag.id in current:
        return False
    set_prompt_tags_by_ids(prompt_id, current + [tag.id])
    return True


def remove_prompt_tag_by_name(prompt_id: int, name: str) -> bool:
    """移除标签：先解析出 id，再从关联里删掉并回写文本缓存。"""
    name = (name or "").strip()
    if not name:
        return False
    if Prompt.get_or_none(Prompt.id == prompt_id) is None:
        return False
    tag = Tag.get_or_none(Tag.name == name)
    if tag is None:
        return False
    current = _current_tag_ids(prompt_id)
    if tag.id not in current:
        return False
    set_prompt_tags_by_ids(prompt_id, [tid for tid in current if tid != tag.id])
    return True


def sync_image_tags(image_id: int, tag_ids) -> dict:
    """把图片的"直接标签"设成给定集合（不动经提示词继承的部分）。"""
    wanted = {int(t) for t in tag_ids}
    current = set(entity_tag_ids(ENTITY_IMAGE, image_id))
    to_add = wanted - current
    to_remove = current - wanted
    for tag_id in to_add:
        EntityTag.get_or_create(entity_type=ENTITY_IMAGE, entity_id=image_id, tag=tag_id)
    if to_remove:
        EntityTag.delete().where(
            (EntityTag.entity_type == ENTITY_IMAGE)
            & (EntityTag.entity_id == image_id)
            & (EntityTag.tag.in_(list(to_remove)))
        ).execute()
    return {"added": len(to_add), "removed": len(to_remove)}


# ---------------------------------------------------------------------------
# 批量计数（侧栏与标签管理页用，全部一次查询）
# ---------------------------------------------------------------------------

def tag_prompt_counts() -> dict[int, int]:
    cur = db.execute_sql(
        "SELECT tag_id, COUNT(*) FROM entity_tags "
        f"WHERE entity_type = '{ENTITY_PROMPT}' GROUP BY tag_id"
    )
    return {row[0]: row[1] for row in cur.fetchall()}


def tag_image_counts() -> dict[int, int]:
    """每个标签对应的**去重**图片数：直接打标签 ∪ 经来源提示词继承。"""
    cur = db.execute_sql(
        f"""
        SELECT tag_id, COUNT(DISTINCT gh_id) FROM (
            SELECT et.tag_id AS tag_id, gh.id AS gh_id
            FROM gen_history gh
            JOIN entity_tags et
              ON et.entity_type = '{ENTITY_IMAGE}' AND et.entity_id = gh.id
            WHERE gh.is_deleted = 0
            UNION
            SELECT et.tag_id AS tag_id, gh.id AS gh_id
            FROM gen_history gh
            JOIN entity_tags et
              ON et.entity_type = '{ENTITY_PROMPT}' AND et.entity_id = gh.prompt_id
            WHERE gh.is_deleted = 0
        ) GROUP BY tag_id
        """
    )
    return {row[0]: row[1] for row in cur.fetchall()}


def recalc_usage_counts() -> None:
    """按 entity_tags 重算 tags.usage_count（旧字段，保留兼容）。"""
    db.execute_sql("UPDATE tags SET usage_count = 0")
    db.execute_sql(
        "UPDATE tags SET usage_count = ("
        "  SELECT COUNT(*) FROM entity_tags WHERE entity_tags.tag_id = tags.id"
        ")"
    )
