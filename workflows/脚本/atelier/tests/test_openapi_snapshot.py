"""`frontend/openapi.json` 必须与后端当前 schema 一致。

前端类型不再手写（`types.ts` 只是 `openapi.d.ts` 的别名层），所以"后端改了字段
但忘了重新生成"会变成一次无声的契约漂移 —— 用户点到那个字段才会发现 `undefined`。
这条用例把漂移挡在提交前：

    python tools/gen_api_types.py     # 重新生成 openapi.json + openapi.d.ts
"""
import json
import sys

import fastapi
import pydantic

from main import app

from app.config import settings

SNAPSHOT = settings.app_root / "frontend" / "openapi.json"


def test_openapi_snapshot_is_up_to_date():
    assert SNAPSHOT.is_file(), f"缺少前端类型快照：{SNAPSHOT}（运行 tools/gen_api_types.py）"
    committed = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    current = json.loads(json.dumps(app.openapi(), ensure_ascii=False, sort_keys=True))

    if committed == current:
        return

    # 失败原因二选一：真契约漂移（改了 schemas/路由没重新生成），
    # 或解释器不对——OpenAPI 输出随 fastapi 版本变，本机曾有双 Python 环境
    # （生产/CI 的 pythoncore=0.115.12，商店版=0.136.3），见 baseline-failures.txt。
    # 这里把解释器事实打进断言消息，让红灯自己说明是哪种情况。
    raise AssertionError(
        "后端 OpenAPI 与 frontend/openapi.json 不一致。二选一：\n"
        "  1) 改了 schemas.py / 路由 → 运行 python tools/gen_api_types.py 重生成并入库；\n"
        f"  2) 解释器不对 → 当前 {sys.executable}（fastapi {fastapi.__version__} / "
        f"pydantic {pydantic.__version__}），快照必须用 ci.ps1 的解释器（pythoncore）生成"
    )
