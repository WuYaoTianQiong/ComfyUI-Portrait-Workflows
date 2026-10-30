"""数据库在线备份 —— 用 SQLite 备份 API，服务运行中也可安全执行。

WAL 模式下直接 Copy-Item 主库文件会漏掉 -wal 里尚未 checkpoint 的数据，
必须走 sqlite3 的 backup() 才能拿到一致快照。

用法（项目解释器）：
    python tools/backup_db.py                    # 备份到 文档/backups/，保留最近 10 个
    python tools/backup_db.py --tag pre_refactor # 备份文件名带自定义标记
    python tools/backup_db.py --keep 5           # 只保留最近 5 个
    python tools/backup_db.py --list             # 只列出已有备份
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import settings  # noqa: E402


def _backup_dir() -> Path:
    d = Path(settings.project_root) / "文档" / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_backups() -> list[Path]:
    return sorted(_backup_dir().glob("*.db*"), key=lambda p: p.stat().st_mtime, reverse=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="SQLite 在线备份")
    parser.add_argument("--tag", default="bak", help="备份文件名标记")
    parser.add_argument("--keep", type=int, default=10, help="保留最近 N 个备份")
    parser.add_argument("--list", action="store_true", help="只列出已有备份")
    args = parser.parse_args()

    backups = list_backups()
    if args.list:
        print(f"备份目录: {_backup_dir()}")
        for p in backups:
            print(f"  {time.strftime('%Y-%m-%d %H:%M', time.localtime(p.stat().st_mtime))}"
                  f"  {p.stat().st_size / 1024 / 1024:6.2f} MB  {p.name}")
        return 0

    src = Path(settings.db_path)
    if not src.exists():
        print(f"数据库不存在: {src}")
        return 1

    stamp = time.strftime("%Y%m%d_%H%M%S")
    dst = _backup_dir() / f"{src.stem}.db.{args.tag}_{stamp}"

    # 在线备份：源库只读打开，目标库由 backup() 写入一致快照
    with sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=15) as s:
        with sqlite3.connect(str(dst)) as d:
            s.backup(d)
    size = dst.stat().st_size / 1024 / 1024
    print(f"已备份 -> {dst}  ({size:.2f} MB)")

    # 轮转：只保留最近 N 个
    stale = list_backups()[args.keep:]
    for p in stale:
        p.unlink(missing_ok=True)
        print(f"已删除旧备份: {p.name}")
    if stale:
        print(f"轮转完成，保留 {args.keep} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
