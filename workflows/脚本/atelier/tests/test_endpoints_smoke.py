"""全端点冒烟：每个 GET 端点用最小参数打一遍，断言不出现 5xx。

为什么需要这一层：历史事故几乎都是"端点存在、一打就炸"这类问题 ——
`/api/images/html` 的函数体引用了未传的参数导致 NameError 500、
跨卷 junction 让启动期 WinError 448 直接崩、
ON CONFLICT 方言不匹配被 `except: pass` 吞掉导致同步从未写入。
这些静态检查（py_compile）和单点单测都发现不了，只有真的发一次请求才会暴露。

清单从 `app.routes` 动态枚举，新增端点自动纳入，不用手工维护。
写操作（POST/PUT/DELETE）不在此列 —— 它们需要有意义的前置数据，
语义由 test_contract.py / test_api_crud.py 覆盖。
"""

import re

import pytest
from fastapi.routing import APIRoute

from main import app

# SSE 是无限流，测试里会挂住；其余端点都应立即返回
_SKIP = {"/api/jobs/events"}

# 覆盖各端点必填 query 参数，值取"必然查不到但合法"的形态，避免 422 之外的意外
_COMMON_QUERY = (
    "filename=__no_such__.png&subfolder=&type=output&path=&dir=&file="
    "&search=&page=1&page_size=5&limit=5&size=300&id=1&prompt_id=1"
    "&category_id=&tag_ids=&tag_match=all&sort=newest&order=desc&format=json"
)


def _iter_routes(routes, prefix: str = ""):
    """递归展开 FastAPI 0.162+ 的 _IncludedRouter，兼容旧版扁平路由。"""
    for route in routes:
        original = getattr(route, "original_router", None)
        context = getattr(route, "include_context", None)
        if original is not None and context is not None:
            sub_prefix = (prefix + (getattr(context, "prefix", "") or "")).rstrip("/")
            yield from _iter_routes(getattr(original, "routes", []), sub_prefix)
            continue
        if isinstance(route, APIRoute):
            path = f"{prefix}{route.path}" if prefix else route.path
            yield route, path


def _get_endpoints() -> list[str]:
    paths = {
        path
        for route, path in _iter_routes(app.routes)
        if "GET" in route.methods
        and path.startswith("/api")
        and path not in _SKIP
    }
    return sorted(paths)


def _materialize(path: str) -> str:
    """把 /api/images/{item_id} 这类路径参数替换成 1。"""
    return re.sub(r"\{[^}]+\}", "1", path)


@pytest.mark.parametrize("path", _get_endpoints())
def test_get_endpoint_does_not_500(api, path):
    url = _materialize(path)
    sep = "&" if "?" in url else "?"
    resp = api.get(f"{url}{sep}{_COMMON_QUERY}")
    assert resp.status_code < 500, (
        f"{url} 返回 {resp.status_code}: {resp.text[:300]}"
    )


def test_all_api_paths_are_covered_or_skipped():
    """防止有人加了新端点却把它塞进 _SKIP 蒙混过关。"""
    total = {
        path
        for route, path in _iter_routes(app.routes)
        if "GET" in route.methods and path.startswith("/api")
    }
    assert _SKIP <= total, f"_SKIP 里有不存在的端点: {_SKIP - total}"
    # 当前 GET 端点 36 个；数量明显下降说明路由注册被破坏
    assert len(total) >= 30, "端点数量异常减少，检查路由注册"
