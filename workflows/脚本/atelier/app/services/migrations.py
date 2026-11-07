"""数据库结构迁移框架：版本表 + 有序迁移。

为什么要有它：原来 `models.init_db` 里是一长串手写 `_migrate_column` 调用，每次启动
全跑一遍。它靠"列不存在才 ALTER"实现幂等，能用，但没有版本概念 —— 不知道这个库
到底升到哪一步、没法表达"A 必须在 B 之前"、迁移中途失败也无从重试。重构要动三张
核心表（标签收敛、可见性三态、派生列），先把地基补上。

约定：
- 迁移函数接收 db，内部自行完成 DDL/DML；`version` 单调递增，一经发布不再修改；
- 每个迁移在事务内执行，成功后写入 `schema_version`；失败则整体回滚且不记录版本，
  下次启动会重试；
- 迁移函数必须幂等（重复执行不报错、不改坏数据），因为回滚/重试都可能让它再跑一次；
- 建表（`db.create_tables(..., safe=True)`）不放进迁移，仍每次启动执行 ——
  新增模型表不需要写迁移。
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger("atelier.migrations")

VERSION_TABLE = "schema_version"


def pending_versions(db_path: str | Path, migrations) -> list[int]:
    """在 init_db 之前只读判断还有哪些迁移未应用。

    启动备份必须先于迁移执行，而那时还没有可用的 Peewee 连接，也不应该为了
    读版本号去建表。这里直接以只读方式打开 SQLite：库不存在或还没有版本表，
    都按 v0 处理；读取失败则保守地认为全部迁移都待应用。
    """
    path = Path(db_path)
    if not path.exists():
        return [int(ver) for ver, _, _ in migrations]
    try:
        with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=5) as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (VERSION_TABLE,),
            ).fetchone()
            if not exists:
                current = 0
            else:
                row = conn.execute(
                    f"SELECT MAX(version) FROM {VERSION_TABLE}"
                ).fetchone()
                current = int(row[0]) if row and row[0] is not None else 0
    except sqlite3.Error:
        logger.warning("读取迁移版本失败，按全部待迁移处理: %s", path, exc_info=True)
        return [int(ver) for ver, _, _ in migrations]
    return [int(ver) for ver, _, _ in migrations if int(ver) > current]


def ensure_version_table(db) -> None:
    db.execute_sql(
        f"CREATE TABLE IF NOT EXISTS {VERSION_TABLE} ("
        " version INTEGER PRIMARY KEY,"
        " applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        " note TEXT NOT NULL DEFAULT '')"
    )


def current_version(db) -> int:
    ensure_version_table(db)
    row = db.execute_sql(f"SELECT MAX(version) FROM {VERSION_TABLE}").fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def applied_versions(db) -> list[int]:
    ensure_version_table(db)
    rows = db.execute_sql(f"SELECT version FROM {VERSION_TABLE} ORDER BY version").fetchall()
    return [int(r[0]) for r in rows]


def apply_migrations(db, migrations) -> list[int]:
    """按版本号顺序执行尚未应用的迁移，返回本次应用的版本列表。"""
    ensure_version_table(db)
    version = current_version(db)
    applied: list[int] = []

    for item in migrations:
        ver, note, fn = item
        if ver <= version:
            continue
        logger.info("应用迁移 v%s: %s", ver, note)
        try:
            with db.atomic():
                fn(db)
                db.execute_sql(
                    f"INSERT OR REPLACE INTO {VERSION_TABLE} (version, note) VALUES (?, ?)",
                    (ver, note),
                )
        except Exception:
            logger.exception("迁移 v%s 失败，已回滚，下次启动重试", ver)
            raise
        applied.append(ver)

    if not applied:
        logger.debug("数据库结构已是最新（v%s）", version)
    return applied
