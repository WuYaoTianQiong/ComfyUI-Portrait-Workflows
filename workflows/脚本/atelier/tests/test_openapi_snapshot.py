"""`frontend/openapi.json` 必须与后端当前 schema 一致。

前端类型不再手写（`types.ts` 只是 `openapi.d.ts` 的别名层），所以"后端改了字段
但忘了重新生成"会变成一次无声的契约漂移 —— 用户点到那个字段才会发现 `undefined`。
这条用例把漂移挡在提交前：

    python tools/gen_api_types.py     # 重新生成 openapi.json + openapi.d.ts
"""
import json

from main import app

from app.config import settings

SNAPSHOT = settings.app_root / "frontend" / "openapi.json"


def test_openapi_snapshot_is_up_to_date():
    assert SNAPSHOT.is_file(), f"缺少前端类型快照：{SNAPSHOT}（运行 tools/gen_api_types.py）"
    committed = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    current = json.loads(json.dumps(app.openapi(), ensure_ascii=False, sort_keys=True))

    assert committed == current, (
        "后端 OpenAPI 与 frontend/openapi.json 不一致 —— "
        "改了 schemas.py / 路由后请运行 python tools/gen_api_types.py"
    )
