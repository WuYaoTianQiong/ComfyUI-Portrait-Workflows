"""文件墓碑：软删除后阻止磁盘扫描/ComfyUI 历史同步把同一文件重新入库。"""
from __future__ import annotations

from app.models import FileTombstone


def tombstone_key(filename: str, subfolder: str = "", img_type: str = "output") -> str:
    """稳定的路径身份；Windows 路径大小写不敏感，统一 casefold。"""
    parts = (
        (img_type or "output").strip().casefold(),
        (subfolder or "").strip().replace("\\", "/").casefold(),
        (filename or "").strip().casefold(),
    )
    return "/".join(parts)


def mark_tombstone(
    filename: str, subfolder: str = "", img_type: str = "output", reason: str = "",
) -> str:
    key = tombstone_key(filename, subfolder, img_type)
    FileTombstone.insert(asset_key=key, reason=reason).on_conflict_replace().execute()
    return key


def clear_tombstone(filename: str, subfolder: str = "", img_type: str = "output") -> None:
    key = tombstone_key(filename, subfolder, img_type)
    FileTombstone.delete().where(FileTombstone.asset_key == key).execute()


def tombstoned_keys() -> set[str]:
    return {row.asset_key for row in FileTombstone.select(FileTombstone.asset_key)}


def is_tombstoned(filename: str, subfolder: str = "", img_type: str = "output") -> bool:
    key = tombstone_key(filename, subfolder, img_type)
    return FileTombstone.get_or_none(FileTombstone.asset_key == key) is not None
