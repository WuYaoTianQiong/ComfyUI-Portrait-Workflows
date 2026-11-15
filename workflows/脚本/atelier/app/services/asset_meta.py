"""资产元数据覆盖层 —— 18+ 分级 / 姿势可用性 / 人数风险的唯一读写入口。

设计口径（2026-11-15 统一管理方案）：

- 上游素材（JSON 与图片）只读，人工判定全部落在 `asset_overrides`；
- `rating` 只有显式写入 `nsfw` / `safe` 时才生效，NULL 表示继承素材自身默认；
- 提示词未显式标记但命中 NSFW 关键词时呈现为 `pending`（待确认）：
  安全模式同样隐藏，但不写库，等人工确认后再落 `safe` / `nsfw`；
- 这样既不会把普通时装（内衣 / 泳装标签）永久误判成 18+，也不会让真正
  的敏感条目在安全模式下意外露出。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models import AssetOverride, Prompt, db
from app.services.fragment_syntax import contains_nsfw_keyword

RATING_NSFW = "nsfw"
RATING_SAFE = "safe"
RATING_PENDING = "pending"
#: 可写入覆盖表的分级；`pending` 是派生态，不落库。
VALID_RATINGS = (RATING_NSFW, RATING_SAFE)
EFFECTIVE_RATINGS = (RATING_NSFW, RATING_SAFE, RATING_PENDING)

ASSET_PROMPT = "prompt"
ASSET_IMAGE = "image"
ASSET_WORKFLOW = "workflow"


def overrides_map(asset_type: str) -> dict[str, AssetOverride]:
    """一次取某类型的全部覆盖行，键为 `asset_key`（批量读取避免 N+1）。"""
    if not asset_type:
        return {}
    rows = AssetOverride.select().where(AssetOverride.asset_type == asset_type)
    return {row.asset_key: row for row in rows}


def get_override(asset_type: str, asset_key: str) -> AssetOverride | None:
    if not asset_type or not asset_key:
        return None
    return AssetOverride.get_or_none(
        (AssetOverride.asset_type == asset_type)
        & (AssetOverride.asset_key == str(asset_key))
    )


def _normalize_rating(value: str | None) -> str | None:
    """校验分级；空串表示“清空为继承”，None 表示“不修改”。"""
    if value is None:
        return None
    rating = value.strip().lower()
    if not rating:
        return ""
    if rating not in VALID_RATINGS:
        raise ValueError(f"不支持的分级：{value}（仅支持 nsfw / safe）")
    return rating


def set_override(
    asset_type: str,
    asset_key: str,
    *,
    rating: str | None = None,
    usable: bool | None = None,
    usable_note: str | None = None,
    risk: str | None = None,
) -> AssetOverride:
    """单条 upsert。字段传 None = 不修改；`rating=""` = 清空为继承默认。"""
    key = str(asset_key or "").strip()
    if not asset_type or not key:
        raise ValueError("asset_type 与 asset_key 不能为空")
    row = get_override(asset_type, key)
    if row is None:
        row = AssetOverride.create(
            asset_type=asset_type, asset_key=key,
            rating=None, usable=None, usable_note="", risk="",
        )
    fields: dict[str, Any] = {}
    normalized = _normalize_rating(rating)
    if normalized is not None:
        fields["rating"] = normalized or None
    if usable is not None:
        fields["usable"] = bool(usable)
    if usable_note is not None:
        fields["usable_note"] = usable_note.strip()
    if risk is not None:
        fields["risk"] = risk.strip()
    if fields:
        fields["updated_at"] = datetime.now()
        AssetOverride.update(**fields).where(AssetOverride.id == row.id).execute()
        row = AssetOverride.get_by_id(row.id)
    return row


def batch_set(asset_type: str, keys: list[str], **fields: Any) -> int:
    """批量 upsert；返回实际处理的键数量。"""
    clean = [str(key).strip() for key in keys if str(key).strip()]
    if not clean:
        return 0
    with db.atomic():
        for key in clean:
            set_override(asset_type, key, **fields)
    return len(clean)


def list_overrides(
    asset_type: str = "",
    rating: str = "",
    limit: int = 200,
    offset: int = 0,
) -> list[AssetOverride]:
    query = AssetOverride.select()
    if asset_type:
        query = query.where(AssetOverride.asset_type == asset_type)
    if rating:
        query = query.where(AssetOverride.rating == rating)
    return list(
        query.order_by(AssetOverride.updated_at.desc(), AssetOverride.id.desc())
        .offset(max(0, offset))
        .limit(max(1, min(limit, 1000)))
    )


def prompt_rating(row: Any, overrides: dict[str, AssetOverride] | None = None) -> str:
    """提示词的有效分级：显式覆盖 > 关键词待确认 > 安全。"""
    key = str(getattr(row, "id", ""))
    override = (overrides or {}).get(key)
    if override is not None and override.rating in VALID_RATINGS:
        return override.rating
    if contains_nsfw_keyword(
        getattr(row, "tags", "") or "", getattr(row, "note", "") or ""
    ):
        return RATING_PENDING
    return RATING_SAFE


def prompt_ratings() -> dict[str, AssetOverride]:
    """提示词覆盖行（批量读取用）。"""
    return overrides_map(ASSET_PROMPT)


# ---------------------------------------------------------------------------
# 图片分级：不逐张人工标，继承来源提示词的三态口径
# ---------------------------------------------------------------------------


def _prompt_lookup(overrides: dict[str, AssetOverride]) -> dict[int, str]:
    """一次算出全部提示词的有效分级，键为提示词主键。"""
    return {
        row.id: prompt_rating(row, overrides)
        for row in Prompt.select(Prompt.id, Prompt.tags, Prompt.note)
    }


def image_rating(
    image_id: int,
    prompt_id: int | None,
    prompt_map: dict[int, str],
    image_overrides: dict[str, AssetOverride] | None = None,
) -> str:
    """图片的有效分级：图片显式覆盖 > 来源提示词分级 > 安全。

    图片是提示词的产物，逐张人工标 600+ 张不现实；继承来源提示词后，
    「提示词标了 18+ → 它出的图也 18+」自动成立，只在对不上时单张覆盖。
    """
    override = (image_overrides or {}).get(str(image_id))
    if override is not None and override.rating in VALID_RATINGS:
        return override.rating
    if prompt_id:
        inherited = prompt_map.get(int(prompt_id))
        if inherited:
            return inherited
    return RATING_SAFE


def image_rating_map() -> dict[int, str]:
    """全部未删除图片的有效分级（批量，避免逐条查库）。"""
    from app.models import Image

    prompt_map = _prompt_lookup(prompt_ratings())
    image_overrides = overrides_map(ASSET_IMAGE)
    return {
        row.id: image_rating(row.id, row.prompt_id, prompt_map, image_overrides)
        for row in Image.select(Image.id, Image.prompt_id).where(Image.is_deleted == False)  # noqa: E712
    }


def image_ratings_for(rows) -> dict[int, str]:
    """按给定图片行（一页 / 单条）算有效分级，只查这批行涉及的提示词。

    列表接口用它：整表 `image_rating_map()` 在几千张图时要扫全表，
    分页时没必要。
    """
    prompt_overrides = prompt_ratings()
    prompt_ids = {int(row.prompt_id) for row in rows if row.prompt_id}
    prompt_map = (
        {
            row.id: prompt_rating(row, prompt_overrides)
            for row in Prompt.select(Prompt.id, Prompt.tags, Prompt.note).where(
                Prompt.id.in_(prompt_ids)
            )
        }
        if prompt_ids
        else {}
    )
    image_overrides = overrides_map(ASSET_IMAGE)
    return {
        row.id: image_rating(row.id, row.prompt_id, prompt_map, image_overrides)
        for row in rows
    }


def image_ids_by_rating(rating: str) -> list[int]:
    """按有效分级取图片 id；非法分级返回空列表。"""
    needle = (rating or "").strip().lower()
    if needle not in EFFECTIVE_RATINGS:
        return []
    return [image_id for image_id, value in image_rating_map().items() if value == needle]


def image_rating_counts() -> dict[str, int]:
    counts = {"total": 0, RATING_NSFW: 0, RATING_SAFE: 0, RATING_PENDING: 0}
    for value in image_rating_map().values():
        counts["total"] += 1
        counts[value] += 1
    return counts


def is_hidden_in_safe_mode(rating: str) -> bool:
    """安全模式是否隐藏：显式 18+ 与待确认都隐藏，避免旧条目意外露出。"""
    return rating in (RATING_NSFW, RATING_PENDING)


def prompt_ids_by_rating(rating: str) -> list[int]:
    """按有效分级取提示词 id；非法分级返回空列表。"""
    needle = (rating or "").strip().lower()
    if needle not in EFFECTIVE_RATINGS:
        return []
    overrides = prompt_ratings()
    return [
        row.id
        for row in Prompt.select(Prompt.id, Prompt.tags, Prompt.note)
        if prompt_rating(row, overrides) == needle
    ]


def prompt_rating_counts() -> dict[str, int]:
    counts = {"total": 0, RATING_NSFW: 0, RATING_SAFE: 0, RATING_PENDING: 0}
    overrides = prompt_ratings()
    for row in Prompt.select(Prompt.id, Prompt.tags, Prompt.note):
        counts["total"] += 1
        counts[prompt_rating(row, overrides)] += 1
    return counts


def override_counts(asset_type: str) -> dict[str, int]:
    """某类型的显式覆盖计数；未写的记为 `unmarked`（不会出现在这里，仅便于对照）。"""
    counts = {RATING_NSFW: 0, RATING_SAFE: 0}
    for row in AssetOverride.select().where(AssetOverride.asset_type == asset_type):
        if row.rating in VALID_RATINGS:
            counts[row.rating] += 1
    return counts
