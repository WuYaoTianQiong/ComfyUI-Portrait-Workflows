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

logger = logging.getLogger("atelier.migrations")

VERSION_TABLE = "schema_version"


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
