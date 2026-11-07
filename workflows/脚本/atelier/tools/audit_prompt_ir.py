"""Prompt IR 影子审计：只读扫描提示词，报告无法无损往返的结构。

用法：
    python tools/audit_prompt_ir.py
    python tools/audit_prompt_ir.py --limit 50
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.models import Prompt, db, init_db  # noqa: E402
from app.services.prompt_ir import shadow_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="只扫描最近 N 条，0 = 全部")
    args = parser.parse_args()

    init_db()
    query = Prompt.select().order_by(Prompt.id.desc())
    if args.limit > 0:
        query = query.limit(args.limit)
    rows = list(query)

    findings = []
    for row in rows:
        report = shadow_report(row.prompt)
        if not report["issues"]:
            continue
        findings.append({
            "id": row.id,
            "name": row.name,
            "issues": report["issues"],
            "whitespace_only": report["whitespace_only"],
            "fragment_types": report["fragment_types"],
            "negative_terms": report["negative_terms"],
        })

    backup_dir = Path(settings.data_dir) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"prompt_ir_shadow_{datetime.now():%Y%m%d_%H%M%S}.json"
    target.write_text(
        json.dumps({
            "scanned": len(rows),
            "issue_count": len(findings),
            "findings": findings,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"扫描 {len(rows)} 条，结构差异 {len(findings)} 条")
    print(f"报告: {target}")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
