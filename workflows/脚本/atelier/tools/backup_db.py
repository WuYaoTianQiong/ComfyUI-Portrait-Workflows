"""数据库在线备份 —— CLI 包装，实现在 services/maintenance.py。

WAL 模式下直接复制主库文件会漏掉 -wal 里尚未 checkpoint 的数据，必须走
sqlite3 的 backup() 才能拿到一致快照。

用法（项目解释器）：
    python tools/backup_db.py                    # 备份到 文档/backups/，保留最近 10 个
    python tools/backup_db.py --tag pre_refactor # 备份文件名带自定义标记
    python tools/backup_db.py --keep 5           # 只保留最近 5 个
    python tools/backup_db.py --list             # 只列出已有备份
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.maintenance import backup_database, backup_dir, list_backups  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="SQLite 在线备份")
    parser.add_argument("--tag", default="bak", help="备份文件名标记")
    parser.add_argument("--keep", type=int, default=10, help="保留最近 N 个备份")
    parser.add_argument("--list", action="store_true", help="只列出已有备份")
    args = parser.parse_args()

    if args.list:
        print(f"备份目录: {backup_dir()}")
        for p in list_backups():
            mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime))
            print(f"  {mtime}  {p.stat().st_size / 1024 / 1024:6.2f} MB  {p.name}")
        return 0

    dst = backup_database(args.tag)
    print(f"已备份 -> {dst}  ({dst.stat().st_size / 1024 / 1024:.2f} MB)")

    stale = list_backups()[args.keep:]
    for p in stale:
        p.unlink(missing_ok=True)
        print(f"已删除旧备份: {p.name}")
    if stale:
        print(f"轮转完成，保留 {args.keep} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
