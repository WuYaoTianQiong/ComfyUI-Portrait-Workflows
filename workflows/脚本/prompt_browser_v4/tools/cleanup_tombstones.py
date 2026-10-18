"""清理 gen_history 里的软删除墓碑（is_deleted=1）。

背景：唯一索引是 `(filename, subfolder, img_type) WHERE is_deleted=0` 的部分索引，
软删除的行永远不会与存活行冲突。配合"文件还在磁盘就重新 INSERT"的同步逻辑，
每删一次就会多留一行墓碑 —— 生产库里 1206 行中 1159 行是墓碑（96%）。

本脚本只删数据库行，**不动磁盘上的图片文件**。

用法：
    python tools/cleanup_tombstones.py            # 预演，只打印将删除多少
    python tools/cleanup_tombstones.py --yes      # 真正执行（先自动备份）
    python tools/cleanup_tombstones.py --yes --keep-recent 7   # 保留最近 7 天的墓碑
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _db_path() -> Path:
    from config import settings

    return Path(settings.db_path)


def _backup(db_path: Path) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup = db_path.with_name(f"{db_path.name}.bak_tombstone_{stamp}")
    shutil.copy2(db_path, backup)
    # WAL 模式下未 checkpoint 的数据在 -wal 里
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(db_path) + suffix)
        if sidecar.exists():
            shutil.copy2(sidecar, str(backup) + suffix)
    return backup


def main() -> int:
    parser = argparse.ArgumentParser(description="清理软删除墓碑")
    parser.add_argument("--yes", action="store_true", help="真正执行删除（默认只预演）")
    parser.add_argument("--keep-recent", type=int, default=0,
                        help="保留最近 N 天内的墓碑（默认 0 = 全删）")
    args = parser.parse_args()

    db_path = _db_path()
    if not db_path.exists():
        print(f"数据库不存在: {db_path}")
        return 1

    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.execute("PRAGMA foreign_keys=ON")

    where = "is_deleted = 1"
    params: tuple = ()
    if args.keep_recent > 0:
        where += " AND (created_at IS NULL OR created_at < datetime('now', ?))"
        params = (f"-{args.keep_recent} days",)

    total = conn.execute("SELECT COUNT(*) FROM gen_history").fetchone()[0]
    live = conn.execute("SELECT COUNT(*) FROM gen_history WHERE is_deleted = 0").fetchone()[0]
    doomed = conn.execute(f"SELECT COUNT(*) FROM gen_history WHERE {where}", params).fetchone()[0]
    tags = conn.execute(
        f"SELECT COUNT(*) FROM image_tags WHERE image_id IN "
        f"(SELECT id FROM gen_history WHERE {where})", params
    ).fetchone()[0]
    cats = conn.execute(
        f"SELECT COUNT(*) FROM image_categories WHERE image_id IN "
        f"(SELECT id FROM gen_history WHERE {where})", params
    ).fetchone()[0]

    print(f"库: {db_path}")
    print(f"总记录 {total} | 存活 {live} | 墓碑 {total - live}")
    print(f"本次将删除: 墓碑 {doomed} 条、图片标签 {tags} 条、图片分类 {cats} 条")

    if not args.yes:
        print("\n预演模式，未做任何修改。确认无误后加 --yes 执行。")
        conn.close()
        return 0

    if doomed == 0:
        print("没有需要清理的墓碑。")
        conn.close()
        return 0

    backup = _backup(db_path)
    print(f"\n已备份到: {backup}")

    try:
        conn.execute("BEGIN")
        conn.execute(
            f"DELETE FROM image_tags WHERE image_id IN "
            f"(SELECT id FROM gen_history WHERE {where})", params
        )
        conn.execute(
            f"DELETE FROM image_categories WHERE image_id IN "
            f"(SELECT id FROM gen_history WHERE {where})", params
        )
        deleted = conn.execute(f"DELETE FROM gen_history WHERE {where}", params).rowcount
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        print(f"删除失败，已回滚: {exc}")
        conn.close()
        return 1

    try:
        conn.execute("VACUUM")
    except sqlite3.OperationalError as exc:
        print(f"VACUUM 跳过（可能有连接占用）: {exc}")

    remaining = conn.execute("SELECT COUNT(*) FROM gen_history").fetchone()[0]
    conn.close()
    print(f"已删除 {deleted} 条墓碑；剩余记录 {remaining} 条。备份保留在 {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
