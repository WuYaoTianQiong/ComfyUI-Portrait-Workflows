"""回收 gen_history 里的软删除墓碑（is_deleted=1）—— CLI 包装。

实现在 services/maintenance.py::purge_tombstones，本文件只负责交互与备份。
服务启动时已经会自动跑一次（保留最近 7 天），这个脚本用于手动清理更早的墓碑。

背景：唯一索引是 `(filename, subfolder, img_type) WHERE is_deleted=0` 的部分索引，
软删除的行永远不会与存活行冲突。配合"文件还在磁盘就重新 INSERT"的同步逻辑，
每删一次就会多留一行墓碑 —— 线上曾出现 528/538（98%）是墓碑。

本脚本只删数据库行，**不动磁盘上的图片文件**。

用法：
    python tools/cleanup_tombstones.py                      # 预演，只打印将删除多少
    python tools/cleanup_tombstones.py --yes                # 真正执行（先自动备份）
    python tools/cleanup_tombstones.py --yes --keep-recent 30  # 保留最近 30 天的墓碑
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.services.maintenance import backup_database, purge_tombstones  # noqa: E402


def _vacuum() -> None:
    try:
        with sqlite3.connect(str(settings.db_path), timeout=10) as conn:
            conn.execute("VACUUM")
    except sqlite3.OperationalError as exc:
        print(f"VACUUM 跳过（可能有连接占用）: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="回收软删除墓碑")
    parser.add_argument("--yes", action="store_true", help="真正执行删除（默认只预演）")
    parser.add_argument("--keep-recent", type=int, default=7,
                        help="保留最近 N 天内的墓碑（默认 7，与启动维护一致）")
    args = parser.parse_args()

    if not Path(settings.db_path).exists():
        print(f"数据库不存在: {settings.db_path}")
        return 1

    preview = purge_tombstones(keep_days=args.keep_recent, dry_run=True)
    print(f"库: {settings.db_path}")
    print(f"墓碑总数 {preview['tombstones']} | 超过 {args.keep_recent} 天可回收 {preview['eligible']}")

    if not args.yes:
        print("\n预演模式，未做任何修改。确认无误后加 --yes 执行。")
        return 0
    if preview["eligible"] == 0:
        print("没有需要回收的墓碑。")
        return 0

    backup = backup_database("pre_tombstone")
    print(f"已备份到: {backup}")

    result = purge_tombstones(keep_days=args.keep_recent, dry_run=False)
    _vacuum()
    remaining = preview["tombstones"] - result["deleted"]
    print(f"已回收 {result['deleted']} 条墓碑、{result['relations']} 条标签/分类关联；"
          f"剩余墓碑 {remaining} 条。备份保留在 {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
