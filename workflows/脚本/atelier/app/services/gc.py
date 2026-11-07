"""资产生命周期：派生缓存可回收，用户上传只盘点不自动删。

- 缩略图 / 远端缓存都是可重建的派生物，按天数回收是安全的；
- 上传图可能只被前端草稿引用（配方不落库），因此只清理 `.incoming-*`
  临时文件，其余只做占用盘点，绝不自动删除。
"""
from __future__ import annotations

import time
from pathlib import Path

from app.config import settings
from app.services import uploads

DAY = 86400


def _files(root: Path, pattern: str = "*", recursive: bool = False) -> list[Path]:
    if not root.is_dir():
        return []
    try:
        iterator = root.rglob(pattern) if recursive else root.glob(pattern)
        return [p for p in iterator if p.is_file()]
    except OSError:
        return []


def _older_than(path: Path, days: float) -> bool:
    try:
        return (time.time() - path.stat().st_mtime) >= max(0.0, days) * DAY
    except OSError:
        return False


def _delete(paths: list[Path], dry_run: bool) -> int:
    if dry_run:
        return 0
    removed = 0
    for path in paths:
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def _bytes(paths: list[Path]) -> int:
    return sum(p.stat().st_size for p in paths if p.is_file())


def gc_thumbnails(dry_run: bool = True, older_than_days: float = 30) -> dict:
    root = Path(settings.thumbnail_dir)
    candidates = [p for p in _files(root, "*.webp") if _older_than(p, older_than_days)]
    return {
        "scope": "thumbnails",
        "dry_run": dry_run,
        "eligible": len(candidates),
        "bytes": _bytes(candidates),
        "deleted": _delete(candidates, dry_run),
    }


def gc_remote_cache(dry_run: bool = True, older_than_days: float = 30) -> dict:
    root = Path(settings.reference_cache_dir)
    candidates = [p for p in _files(root, recursive=True) if _older_than(p, older_than_days)]
    return {
        "scope": "reference_remote",
        "dry_run": dry_run,
        "eligible": len(candidates),
        "bytes": _bytes(candidates),
        "deleted": _delete(candidates, dry_run),
    }


def gc_upload_temp(dry_run: bool = True, older_than_days: float = 1) -> dict:
    root = uploads.uploads_dir()
    candidates = [
        p for p in _files(root, ".incoming-*") if _older_than(p, older_than_days)
    ]
    return {
        "scope": "upload_temp",
        "dry_run": dry_run,
        "eligible": len(candidates),
        "bytes": _bytes(candidates),
        "deleted": _delete(candidates, dry_run),
    }


def inventory_uploads() -> dict:
    """上传图只盘点：配方草稿可能只在前端 localStorage 里，不能自动删。"""
    root = uploads.uploads_dir()
    files = _files(root)
    return {
        "scope": "uploads",
        "count": len(files),
        "bytes": _bytes(files),
        "note": "上传图可能被前端草稿引用，本工具只盘点，不自动删除",
    }


def run_gc(
    dry_run: bool = True,
    older_than_days: float = 30,
    include_remote: bool = True,
) -> dict:
    report = {
        "thumbnails": gc_thumbnails(dry_run, older_than_days),
        "upload_temp": gc_upload_temp(dry_run, 1),
        "uploads": inventory_uploads(),
    }
    if include_remote:
        report["reference_remote"] = gc_remote_cache(dry_run, older_than_days)
    return report
