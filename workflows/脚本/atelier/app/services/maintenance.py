"""数据库维护任务：在线备份、墓碑回收、备份轮转。

为什么需要（背景）：`gen_history` 的唯一索引是
`(filename, subfolder, img_type) WHERE is_deleted=0` 的部分索引 —— 软删除行永远
不参与冲突，于是每删一次就多留一行墓碑。线上曾出现 538 行里 528 行是墓碑（98%），
既占空间，也让所有"全量扫描"类操作（同步、巡检、清理）越来越慢。

三条硬规矩：
1. **只删 is_deleted=1 且超过保留期的行**，活记录一行都不碰；
2. 回收前自动做一次在线备份（SQLite backup API，WAL 下也算数）；
3. 墓碑的 created_at 由 SQLite CURRENT_TIMESTAMP 写成 **UTC**，比较时必须用
   UTC 的 now，否则东八区会凭空多出 8 小时，保留期直接失效。
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models import EntityTag, Image, ImageCategory, ImageTag, db
from app.config import settings
from app.services.tagging import recalc_usage_counts
from app.services.thumbnail import clear_thumbnails_for

logger = logging.getLogger("atelier.maintenance")

BACKUP_KEEP = 10
TOMBSTONE_KEEP_DAYS = 7


def _is_production_db() -> bool:
    """当前连的是不是生产运行库（而非测试/冒烟用的临时库）。

    2026-11-06 起运行库归一在 `data_dir`（默认 `<app_root>/data`，可 ATELIER_DATA_DIR 覆盖）。
    测试/冒烟会通过 ATELIER_DB_PATH 把库显式指到临时目录，此时 db_path 与
    `data_dir/<库名>` 不一致，维护任务（备份/轮转/墓碑回收）自动跳过，避免把
    临时库的备份写进真实 backups/ 目录。
    """
    import os

    # 显式 ATELIER_DB_PATH（测试/冒烟/临时库，可能恰好与 data_dir 同目录）一律视为非生产库。
    # 注意不能用 settings.model_fields_set：pydantic-settings 在 validator 之后会把派生
    # 赋值（db_path/thumbnail_dir）也记进去，运行期已无法区分「env 显式指定」与「默认派生」。
    if os.environ.get("ATELIER_DB_PATH"):
        return False
    db = Path(settings.db_path)
    expected = Path(settings.data_dir) / "prompts.db"
    try:
        return os.path.normcase(os.path.abspath(db)) == os.path.normcase(os.path.abspath(expected))
    except OSError:
        return False


# ---------------------------------------------------------------------------
# 备份
# ---------------------------------------------------------------------------

def backup_dir() -> Path:
    d = Path(settings.data_dir) / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_backups() -> list[Path]:
    return sorted(backup_dir().glob("*.db*"), key=lambda p: p.stat().st_mtime, reverse=True)


def backup_database(tag: str = "bak", stamp: str | None = None) -> Path:
    """在线备份当前库，返回备份文件路径。

    必须走 sqlite3 的 backup()：WAL 模式下直接复制主库文件会漏掉 -wal 里
    尚未 checkpoint 的数据。
    """
    src = Path(settings.db_path)
    if not src.exists():
        raise FileNotFoundError(f"数据库不存在: {src}")
    stamp = stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = backup_dir() / f"{src.stem}.db.{tag}_{stamp}"
    with sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=15) as s:
        with sqlite3.connect(str(dst)) as d:
            s.backup(d)
    return dst


def rotate_backups(keep: int = BACKUP_KEEP) -> dict:
    """把散落的 .db.bak* 归档进 backups/legacy/，再按数量轮转 backups/。

    扫描两个位置：新运行数据根 `data_dir`（2026-11-06 起）与旧位置
    `<库根>/文档/`（迁移期间的旧备份仍然散落在这里）。两处按绝对路径去重；
    迁移完成后旧目录自然为空，多扫一遍无副作用。

    历史遗留的备份进 legacy/ 且不参与轮转 —— 那是过去手工打的快照，可能对应某次
    事故的恢复点，不值得为了省几十 MB 删掉；轮转只作用于本次重构之后自动生成的备份。
    """
    import os

    target_dir = backup_dir() / "legacy"
    target_dir.mkdir(parents=True, exist_ok=True)

    scan_dirs = (Path(settings.data_dir), Path(settings.library_root) / "文档")
    moved = 0
    seen: set[str] = set()
    for scan_dir in scan_dirs:
        if not scan_dir.is_dir():
            continue
        for p in scan_dir.glob("*.db.bak*"):
            if not p.is_file():
                continue
            key = os.path.normcase(os.path.abspath(p))
            if key in seen:
                continue
            seen.add(key)
            dst = target_dir / p.name
            if dst.exists():
                continue
            try:
                shutil.move(str(p), str(dst))
                moved += 1
            except OSError as exc:
                logger.warning("归档备份失败 %s: %s", p.name, exc)

    backups = list_backups()
    removed = 0
    for p in backups[keep:]:
        try:
            p.unlink()
            removed += 1
        except OSError as exc:
            logger.warning("删除旧备份失败 %s: %s", p.name, exc)
    return {"moved": moved, "removed": removed, "kept": min(len(backups), keep)}


# ---------------------------------------------------------------------------
# 墓碑回收
# ---------------------------------------------------------------------------

def purge_tombstones(keep_days: int = TOMBSTONE_KEEP_DAYS, dry_run: bool = True) -> dict:
    """回收超过保留期的软删除记录及其标签/分类关联。不动磁盘文件。"""
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    deadline = now_utc - timedelta(days=keep_days)

    tombstones = Image.select().where(Image.is_deleted == True).count()
    rows = list(
        Image.select(Image.id, Image.filename, Image.subfolder, Image.img_type).where(
            (Image.is_deleted == True)
            & ((Image.created_at.is_null(True)) | (Image.created_at < deadline))
        )
    )
    ids = [r.id for r in rows]
    result = {
        "tombstones": tombstones, "eligible": len(ids), "deleted": 0,
        "relations": 0, "thumbnails": 0,
    }
    if dry_run or not ids:
        return result

    with db.atomic():
        result["relations"] = (
            ImageTag.delete().where(ImageTag.image.in_(ids)).execute()
            + ImageCategory.delete().where(ImageCategory.image.in_(ids)).execute()
            + EntityTag.delete().where(
                (EntityTag.entity_type == "image") & (EntityTag.entity_id.in_(ids))
            ).execute()
        )
        result["deleted"] = Image.delete().where(Image.id.in_(ids)).execute()

    for row in rows:
        result["thumbnails"] += clear_thumbnails_for(
            row.filename or "", row.subfolder or "", row.img_type or "output"
        )
    try:
        recalc_usage_counts()
    except Exception:
        logger.exception("墓碑回收后重算标签计数失败")
    return result


# ---------------------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------------------

def run_startup_maintenance(
    keep_days: int = TOMBSTONE_KEEP_DAYS,
    backup_keep: int = BACKUP_KEEP,
    backup_tag: str = "startup",
) -> None:
    """启动时跑一次：在线备份 → 归档/轮转 → 回收墓碑。

    任何一步失败都只记日志，绝不阻断启动（维护任务是辅助，不是必需品）。
    只在生产库上执行：冒烟测试用临时库启动服务时若也跑维护，会把临时库的备份
    写进真实 backups/ 目录，还可能把真实备份挤出轮转窗口。
    """
    import os

    if not _is_production_db():
        logger.info("当前不是生产库（%s），跳过启动维护", settings.db_path)
        return
    try:
        path = backup_database(backup_tag)
        logger.info("启动备份完成: %s", path.name)
    except Exception:
        logger.exception("启动备份失败，本次跳过墓碑回收")

    try:
        rot = rotate_backups(backup_keep)
        if rot["moved"] or rot["removed"]:
            logger.info("备份轮转：归档 %s 个，清理 %s 个，保留 %s 个",
                        rot["moved"], rot["removed"], rot["kept"])
    except Exception:
        logger.exception("备份轮转失败")

    try:
        res = purge_tombstones(keep_days=keep_days, dry_run=False)
        if res["deleted"]:
            logger.info(
                "墓碑回收：共 %s 条墓碑，回收 %s 条（保留最近 %s 天），清理关联 %s 条",
                res["tombstones"], res["deleted"], keep_days, res["relations"],
            )
        else:
            logger.info("墓碑回收：共 %s 条墓碑，均未超过 %s 天保留期", res["tombstones"], keep_days)
    except Exception:
        logger.exception("墓碑回收失败")
