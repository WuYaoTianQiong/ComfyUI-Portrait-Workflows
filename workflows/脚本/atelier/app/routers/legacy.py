"""旧路径 308 别名 —— P3 路由资源化的过渡层。

为什么需要：① E2E 与契约测试硬编码了旧路径；② 浏览器书签、以及用户手上
正在跑的旧前端构建产物仍在用旧路径；③ 硬刷新之前，页面里的 `fetch` 不会变。

做法：每个旧路径返回 308（永久重定向，**保留方法与请求体**），浏览器会自动
用新路径重发一次，前端无需感知。

退役规则（命名规范 §6.4）：**留一个版本**。日志里每条别名都会累计计数，
按「首次访问」这一行进观察窗口，清零后本文件整份删除即可。

⚠ 必须在 `main.py` 里**晚于全部正式路由**注册（见该文件注释）。
"""
from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

logger = logging.getLogger("atelier.legacy")

router = APIRouter(tags=["兼容别名"], include_in_schema=False)

#: (旧路径, 新路径, 是否连子路径一起重定向)
#: 路径不含 `/api` 前缀 —— 本 router 由 main.py 以 prefix="/api" 挂载，
#: 拼 Location 时统一补上（少了它浏览器会跳到 `/images/...` 这种非 API 路径）。
_API_PREFIX = "/api"
_ALIASES: list[tuple[str, str, bool]] = [
    ("/status", "/system/status", False),
    ("/config", "/system/config", False),
    ("/stats", "/system/stats", False),
    ("/run", "/runs", False),
    ("/run_text", "/runs/text", False),
    ("/batch_generate", "/runs/batch", False),
    ("/progress", "/jobs/progress", False),
    ("/batch_stop", "/jobs/stop_all", False),
]

_hits: dict[str, int] = {}
_hits_lock = threading.Lock()


def get_hit_counts() -> dict[str, int]:
    """当前进程内各旧路径的访问次数（给运维/测试看，不对外暴露）。"""
    with _hits_lock:
        return dict(_hits)


def reset_hit_counts() -> None:
    """清空计数（测试用）。"""
    with _hits_lock:
        _hits.clear()


def _redirect(request: Request, target: str) -> RedirectResponse:
    old_path = request.url.path
    with _hits_lock:
        _hits[old_path] = _hits.get(old_path, 0) + 1
        total = _hits[old_path]

    query = request.url.query
    location = f"{_API_PREFIX}{target}"
    if query:
        location = f"{location}?{query}"
    if total == 1:
        # 每个旧路径只打一次 WARNING：扫日志时这一行就是"该别名还在被用"的清单
        logger.warning(
            "旧路径别名首次访问 %s %s → %s", request.method, old_path, location
        )
    logger.info(
        "旧路径别名 %s %s → %s（该路径累计 %d 次）",
        request.method, old_path, location, total,
    )
    return RedirectResponse(location, status_code=308)


def _register_exact(old: str, new: str) -> None:
    async def endpoint(request: Request, _new: str = new):
        return _redirect(request, _new)

    router.add_api_route(
        old,
        endpoint,
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
        name=f"legacy{old.replace('/', '_')}",
    )


def _register_subtree(old: str, new: str) -> None:
    async def endpoint(request: Request, rest: str, _new: str = new):
        return _redirect(request, f"{_new}/{rest}")

    router.add_api_route(
        f"{old}/{{rest:path}}",
        endpoint,
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
        name=f"legacy{old.replace('/', '_')}_subtree",
    )


for _old, _new, _with_subtree in _ALIASES:
    _register_exact(_old, _new)
    if _with_subtree:
        _register_subtree(_old, _new)
