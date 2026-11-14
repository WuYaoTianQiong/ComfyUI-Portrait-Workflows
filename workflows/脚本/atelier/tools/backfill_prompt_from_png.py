"""从 PNG 内嵌的 ComfyUI prompt 元数据回填 gen_history.prompt_params。

背景：写者线程每轮只刷新 20 个活跃任务（已改为按最久未刷新轮转）。在这次修复
之前，超过 20 个 job 的横评批次里，较早的 job 掉出窗口后不会再被推进，出图只能
被磁盘扫描兜底入库 —— 这类记录只有宽高/体积，`prompt_params` 里没有提示词，
档案左栏因此显示“（出图参数里没有留下提示词正文）”。

PNG 里仍保存着提交时的 API 工作流，可以从中还原实际注入的正向/负向文本；
负向是否生效沿用 workflow_parser 的同一套能力探测。

用法（项目解释器）：
    python tools/backfill_prompt_from_png.py            # 预演，只统计
    python tools/backfill_prompt_from_png.py --yes      # 真正写库（先自动备份）
    python tools/backfill_prompt_from_png.py --yes --limit 20
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.models import Image, db  # noqa: E402
from app.services.image_meta import read_embedded_prompt  # noqa: E402
from app.services.maintenance import backup_database  # noqa: E402


def _load_params(raw: str | None) -> dict:
    try:
        data = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser(description="从 PNG 元数据回填缺失的提示词")
    parser.add_argument("--yes", action="store_true", help="真正写库（默认只预演）")
    parser.add_argument("--limit", type=int, default=0, help="最多回填 N 条（0=不限）")
    args = parser.parse_args()

    if not Path(settings.db_path).exists():
        print(f"数据库不存在: {settings.db_path}")
        return 1

    db.connect(reuse_if_open=True)
    scanned = 0
    missing_total = 0
    candidates: list[tuple[Image, dict]] = []
    for row in Image.select().where(Image.is_deleted == False).order_by(Image.id).iterator():
        scanned += 1
        params = _load_params(row.prompt_params)
        if params.get("prompt"):
            continue
        missing_total += 1
        if args.limit and len(candidates) >= args.limit:
            continue
        candidates.append((row, params))

    restored: list[tuple[Image, dict, dict]] = []
    unreadable = 0
    for row, params in candidates:
        meta = read_embedded_prompt(row.filename, row.subfolder or "", row.img_type or "output")
        if meta.get("prompt"):
            restored.append((row, params, meta))
        else:
            unreadable += 1

    print(f"库: {settings.db_path}")
    print(f"扫描 {scanned} 条，缺提示词 {missing_total} 条，本次处理 {len(candidates)} 条")
    print(f"可从 PNG 恢复 {len(restored)} 条，无法读取 {unreadable} 条")
    for row, _params, meta in restored[:5]:
        print(f"  #{row.id} {row.filename} | {meta['prompt'][:50]!r}")

    if not args.yes:
        print("\n预演模式，未做任何修改。确认无误后加 --yes 执行。")
        return 0
    if not restored:
        print("没有可回填的记录。")
        return 0

    backup = backup_database("pre_prompt_backfill")
    print(f"已备份到: {backup}")

    with db.atomic():
        for row, params, meta in restored:
            merged = dict(params)
            merged["prompt"] = meta["prompt"]
            if meta.get("negative_prompt"):
                merged["negative_prompt"] = meta["negative_prompt"]
            merged["compiled"] = {
                "positive": meta["prompt"],
                "negative": meta.get("negative_prompt", ""),
                "negative_effective": bool(meta.get("negative_effective")),
                "notes": [],
                "warnings": [],
            }
            Image.update(
                prompt_params=json.dumps(merged, ensure_ascii=False),
            ).where(Image.id == row.id).execute()

    print(f"已回填 {len(restored)} 条；剩余无法恢复 {unreadable} 条。备份保留在 {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
