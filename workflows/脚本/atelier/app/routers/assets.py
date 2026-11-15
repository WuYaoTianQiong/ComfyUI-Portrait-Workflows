"""资产元数据 API —— 18+ 分级 / 姿势可用性 / 双人人数风险。

上游素材（JSON 与图片）只读，这里只操作 `asset_overrides` 表：
- `GET  /api/assets/stats`                各类型分级计数（含提示词「待确认」）
- `GET  /api/assets/overrides`            覆盖行列表
- `PUT  /api/assets/overrides/{type}/{key}` 单条 upsert
- `POST /api/assets/overrides/batch`      批量 upsert

提示词的「待确认」是派生态（关键词命中但未显式标记），不落库，因此只出现在
stats 与 `/api/prompts?content_rating=pending`，不在覆盖行列表里。
"""
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import asset_meta, reference_library

router = APIRouter(tags=["资产元数据"])


class OverridePatch(BaseModel):
    """单条覆盖；未传的字段保持原值，`rating=""` 表示清空为继承默认。"""

    rating: Optional[str] = None
    usable: Optional[bool] = None
    usable_note: Optional[str] = None
    risk: Optional[str] = None


class BatchOverrideRequest(OverridePatch):
    asset_type: str
    keys: list[str] = Field(default_factory=list)


class OverrideRow(BaseModel):
    asset_type: str
    asset_key: str
    rating: Optional[str] = None
    usable: Optional[bool] = None
    usable_note: str = ""
    risk: str = ""
    updated_at: str = ""


def _to_row(row: Any) -> dict[str, Any]:
    return {
        "asset_type": row.asset_type,
        "asset_key": row.asset_key,
        "rating": row.rating,
        "usable": row.usable,
        "usable_note": row.usable_note or "",
        "risk": row.risk or "",
        "updated_at": str(row.updated_at) if row.updated_at else "",
    }


@router.get("/assets/stats")
def asset_stats():
    """各类型分级计数：提示词与图片含 pending（待确认），姿势/工作流只统计显式覆盖。"""
    prompt_counts = asset_meta.prompt_rating_counts()
    image_counts = asset_meta.image_rating_counts()
    pose_counts = reference_library.rating_counts("pose")
    workflow_counts = asset_meta.override_counts(asset_meta.ASSET_WORKFLOW)

    return {
        "prompt": prompt_counts,
        "pose": pose_counts,
        "image": image_counts,
        "workflow": {
            "nsfw": workflow_counts[asset_meta.RATING_NSFW],
            "safe": workflow_counts[asset_meta.RATING_SAFE],
        },
    }


@router.get("/assets/overrides", response_model=list[OverrideRow])
def list_asset_overrides(
    asset_type: str = Query("", description="pose / prompt / image / workflow；空 = 全部"),
    rating: str = Query("", description="nsfw / safe；空 = 全部"),
    limit: int = Query(200),
    offset: int = Query(0),
):
    if rating and rating not in asset_meta.VALID_RATINGS:
        raise HTTPException(400, f"不支持的分级：{rating}（仅支持 nsfw / safe）")
    rows = asset_meta.list_overrides(asset_type, rating, limit, offset)
    return [_to_row(row) for row in rows]


@router.put("/assets/overrides/{asset_type}/{asset_key:path}", response_model=OverrideRow)
def put_asset_override(asset_type: str, asset_key: str, patch: OverridePatch):
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "至少提供一个要修改的字段")
    try:
        row = asset_meta.set_override(asset_type, asset_key, **fields)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return _to_row(row)


@router.post("/assets/overrides/batch")
def batch_asset_overrides(req: BatchOverrideRequest):
    fields = req.model_dump(exclude_unset=True, exclude={"asset_type", "keys"})
    if not fields:
        raise HTTPException(400, "至少提供一个要修改的字段")
    if not req.keys:
        raise HTTPException(400, "keys 不能为空")
    try:
        updated = asset_meta.batch_set(req.asset_type, req.keys, **fields)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"updated": updated}
