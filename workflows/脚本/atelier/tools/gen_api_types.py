"""从后端 OpenAPI 生成前端 API 类型（命名规范 §8.3 / §9）。

为什么不再手写 `frontend/src/api/types.ts`：`schemas.py` 与它原本是两份手工
维护的镜像，后端改一个字段名，前端只会在运行时看到 `undefined`。现在唯一真源
是 Pydantic 模型 → `/openapi.json` → `openapi-typescript` → `openapi.d.ts`，
`types.ts` 只剩一层语义别名（`export type HistoryItem = ...`）。

用法（在项目根或任意目录）：
    python tools/gen_api_types.py
    或  cd frontend && npm run gen:api

产物：
    frontend/openapi.json          —— 后端 schema 快照，入库以便 review diff
    frontend/src/api/openapi.d.ts  —— 生成的 TS 类型，不手改
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 只导出 schema，不启动服务、不连数据库；仍然把库指到临时目录，
# 万一某个模块在 import 期就摸库，也不会碰到真实数据。
os.environ.setdefault("ATELIER_NO_BROWSER", "1")
os.environ.setdefault("ATELIER_DB_PATH", str(Path(tempfile.mkdtemp()) / "openapi_snapshot.db"))

from app.main import app  # noqa: E402

SCHEMA_PATH = ROOT / "frontend" / "openapi.json"
OUT_PATH = ROOT / "frontend" / "src" / "api" / "openapi.d.ts"


def main() -> int:
    schema = app.openapi()
    SCHEMA_PATH.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    schemas = list((schema.get("components") or {}).get("schemas") or {})
    print(f"openapi.json: {len(schema.get('paths') or {})} 条路径 / {len(schemas)} 个模型")

    # 参数一律用「相对 frontend/ 的路径」：项目路径里有中文（`脚本`），
    # Windows + shell=True 会把中文参数按 URL 编码传给 node，node 找不到文件。
    cmd = ["npx", "openapi-typescript", "openapi.json", "-o", "src/api/openapi.d.ts"]
    result = subprocess.run(
        cmd,
        cwd=str(ROOT / "frontend"),
        shell=(os.name == "nt"),
    )
    if result.returncode != 0:
        print("openapi-typescript 执行失败；先确认 frontend/ 已 npm install", file=sys.stderr)
        return result.returncode
    print(f"生成完成: {OUT_PATH.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
