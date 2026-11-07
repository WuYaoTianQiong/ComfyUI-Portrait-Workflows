"""回收可重建的派生资产；上传图只盘点。

用法：
    python tools/gc_assets.py                 # dry-run，只报告
    python tools/gc_assets.py --confirm       # 真正删除缩略图/远端缓存/临时上传
    python tools/gc_assets.py --days 7        # 只回收 7 天前的派生缓存
    python tools/gc_assets.py --confirm --days 0   # 回收全部派生缓存
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.gc import run_gc  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true", help="真正删除；默认只 dry-run")
    parser.add_argument("--days", type=float, default=30, help="派生缓存保留天数")
    parser.add_argument("--no-remote", action="store_true", help="不处理外链缓存")
    args = parser.parse_args()

    report = run_gc(
        dry_run=not args.confirm,
        older_than_days=max(0.0, args.days),
        include_remote=not args.no_remote,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
