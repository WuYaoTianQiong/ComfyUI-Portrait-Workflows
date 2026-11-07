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


def sync_prompt_tags(prompt_id: int, text: str | None) -> dict:
    """按标签文本全量重算该提示词的 entity_tags，返回 {added, removed}。

    全量重算而非增量：文本是唯一事实来源，重算才能保证"文本里删掉一个标签"
    在关联表里也真的消失。数据量小（单条提示词最多十几个标签），成本可忽略。
    """
    wanted: set[int] = set()
    for name in split_tags(text):
        wanted.add(get_or_create_tag(name).id)

    current = set(prompt_tag_ids(prompt_id))
    to_add = wanted - current
    to_remove = current - wanted

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
    return {"added": len(to_add), "removed": len(to_remove)}


def _rewrite_tag_text(text: str | None, old: str, new: str) -> tuple[str, bool]:
    """把标签文本里的 old 精确替换成 new；new 为空表示删除。"""
    parts: list[str] = []
    changed = False
    for raw in _TAG_SEP_RE.split(text or ""):
        name = raw.strip()
        if not name:
            continue
        if name == old:
            changed = True
            if new:
                parts.append(new)
        else:
            parts.append(name)
    return ", ".join(parts), changed


def _sync_prompt_tag_texts(old: str, new: str) -> int:
    """改写所有提示词的标签文本并重算关联；返回受影响条数。"""
    changed = 0
    for prompt in Prompt.select():
        text, hit = _rewrite_tag_text(prompt.tags, old, new)
        if not hit:
            continue
        Prompt.update(tags=text).where(Prompt.id == prompt.id).execute()
        sync_prompt_tags(prompt.id, text)
        changed += 1
    return changed


def rename_tag(tag_id: int, new_name: str) -> int:
    """重命名标签，并把所有提示词文本里的旧名同步改掉。

    否则下次保存提示词时，旧文本会经 `sync_prompt_tags` 把旧标签重新创建出来。
    """
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
    old_name = tag.name
    with db.atomic():
        Tag.update(name=new_name).where(Tag.id == tag_id).execute()
        return _sync_prompt_tag_texts(old_name, new_name)


def delete_tag_with_refs(tag_id: int) -> int:
    """删除标签，同时清掉所有提示词文本与关联表中的引用。"""
    tag = Tag.get_or_none(Tag.id == tag_id)
    if tag is None:
        raise ValueError("标签不存在")
    with db.atomic():
        changed = _sync_prompt_tag_texts(tag.name, "")
        EntityTag.delete().where(EntityTag.tag == tag_id).execute()
        tag.delete_instance(recursive=False)
    return changed


def add_prompt_tag_by_name(prompt_id: int, name: str) -> bool:
    """把标签追加到提示词（同时改文本与关联表）。返回是否发生变化。

    文本是唯一事实来源：只写关联表不写文本的话，用户下次编辑提示词触发
    `sync_prompt_tags` 全量重算时，这条关联会被冲掉。
    """
    from app.models import Prompt

    name = (name or "").strip()
    if not name:
        return False
    prompt = Prompt.get_or_none(Prompt.id == prompt_id)
    if prompt is None:
        return False
    names = split_tags(prompt.tags)
    if name in names:
        return False
    names.append(name)
    text = ",".join(names)
    Prompt.update(tags=text).where(Prompt.id == prompt_id).execute()
    sync_prompt_tags(prompt_id, text)
    return True


def remove_prompt_tag_by_name(prompt_id: int, name: str) -> bool:
    """从提示词去掉标签（同时改文本与关联表）。返回是否发生变化。"""
    from app.models import Prompt

    name = (name or "").strip()
    prompt = Prompt.get_or_none(Prompt.id == prompt_id)
    if prompt is None or not name:
        return False
    names = split_tags(prompt.tags)
    if name not in names:
        return False
    names = [n for n in names if n != name]
    text = ",".join(names)
    Prompt.update(tags=text).where(Prompt.id == prompt_id).execute()
    sync_prompt_tags(prompt_id, text)
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
