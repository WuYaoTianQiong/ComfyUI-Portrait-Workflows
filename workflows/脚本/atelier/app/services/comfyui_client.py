"""ComfyUI API 客户端 —— 所有与 ComfyUI 的 HTTP 交互"""
import atexit
import json
import logging
import threading
import time

import httpx

from app.config import settings

logger = logging.getLogger("atelier.comfy")

COMFYUI_API = settings.comfyui_api

# 同步 HTTP 客户端复用。
# 旧实现每次请求都 `with httpx.Client(...)`，而 httpx 在 __init__ 里会同步构建
# SSLContext（Windows 证书库实测约 1.0–1.5s），缩略图缺图回退、每 30 秒的同步、
# 每 10 秒的状态轮询都要各付一次。这里只建一次，线程间共享（httpx.Client 可并发）。
# trust_env=False：目标固定是本机 ComfyUI；同时避开 Windows 上 NO_PROXY 含 `[::1]`
# 时 httpx 0.28 抛 "Invalid port: ':1]'" 的问题。
_sync_client: httpx.Client | None = None
_sync_client_lock = threading.Lock()


def get_sync_client() -> httpx.Client:
    """返回进程内共享的同步 httpx 客户端；调用方不要 close。"""
    global _sync_client
    with _sync_client_lock:
        if _sync_client is None or _sync_client.is_closed:
            _sync_client = httpx.Client(
                timeout=httpx.Timeout(30.0, connect=5.0),
                limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
                follow_redirects=True,
                trust_env=False,
            )
        return _sync_client


def close_sync_client() -> None:
    global _sync_client
    with _sync_client_lock:
        if _sync_client is not None and not _sync_client.is_closed:
            _sync_client.close()
        _sync_client = None


atexit.register(close_sync_client)

# object_info 缓存：成功缓存 5 分钟，失败缓存 30 秒。
# 失败也要缓存，否则 ComfyUI 无响应时每个节点类型都要各等一次超时。
_OBJECT_INFO_TTL = 300.0
_OBJECT_INFO_FAIL_TTL = 30.0
_OBJECT_INFO_TIMEOUT = 4.0
_object_info: dict | None = None
_object_info_at = 0.0
_object_info_fail_until = 0.0

# 探活结果的短缓存（见 is_online 的注释）：挡住前端 10s 轮询造成的重复长探测。
# 15s 略大于前端轮询间隔（App.vue refetchInterval=10s），使轮询基本都命中缓存；
# 代价是 ComfyUI 刚恢复时最多 15s 才被发现（原来 10s 轮询 + 6.5s 探测也要 16s）。
_ONLINE_TTL_SECONDS = 15.0
_online_cache: tuple[float, bool] | None = None


def get_object_info(force: bool = False) -> dict:
    """一次性拉取 ComfyUI 的 `/object_info` 并缓存，返回 {node_type: spec}。

    为什么整份拉取而不是按节点类型逐个请求 `/object_info/{node}`：
    逐个请求时，每个未缓存过的节点类型都要一次往返；ComfyUI 无响应（在跑图、
    或卡死）时每个都要等满超时 —— 实测冷启动列 11 个工作流要 57 秒。
    整份只取一次后，离线场景也最多只等一次超时，且 30 秒内不再重试。
    """
    global _object_info, _object_info_at, _object_info_fail_until

    now = time.monotonic()
    if not force:
        if _object_info is not None and now - _object_info_at < _OBJECT_INFO_TTL:
            return _object_info
        if now < _object_info_fail_until:
            return {}

    try:
        resp = get_sync_client().get(f"{COMFYUI_API}/object_info", timeout=_OBJECT_INFO_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        _object_info = data if isinstance(data, dict) else {}
        _object_info_at = now
        _object_info_fail_until = 0.0
        return _object_info
    except Exception as exc:
        _object_info_fail_until = now + _OBJECT_INFO_FAIL_TTL
        logger.debug(
            "拉取 object_info 失败（%.0fs 内不再重试）：%s", _OBJECT_INFO_FAIL_TTL, type(exc).__name__
        )
        return {}


def fetch_json(url: str, timeout: int = 5) -> dict | None:
    """GET 请求 ComfyUI 并返回 JSON"""
    try:
        resp = get_sync_client().get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def post_comfyui(path: str, data: dict | None = None, timeout: int = 5) -> httpx.Response | None:
    """POST 请求 ComfyUI"""
    try:
        body = json.dumps(data).encode("utf-8") if data is not None else b""
        headers = {"Content-Type": "application/json"} if data is not None else {}
        return get_sync_client().post(
            f"{COMFYUI_API}{path}", content=body, headers=headers, timeout=timeout
        )
    except Exception:
        return None


def push_prompt(api_workflow: dict) -> dict:
    """将工作流推送到 ComfyUI，返回 {prompt_id, ...}"""
    payload = json.dumps({"prompt": api_workflow}).encode("utf-8")
    logger.debug("提交 ComfyUI：nodes=%d first=%s", len(api_workflow), list(api_workflow.keys())[:10])

    try:
        resp = get_sync_client().post(
            f"{COMFYUI_API}/prompt",
            content=payload,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        if resp.status_code != 200:
            logger.error("ComfyUI 拒绝任务：HTTP %s %s", resp.status_code, resp.text[:500])
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        logger.error("ComfyUI 返回错误：%s %s", e.response.status_code, e.response.text[:500])
        raise RuntimeError(f"ComfyUI 连接失败: {e}")
    except httpx.HTTPError as e:
        raise RuntimeError(f"ComfyUI 连接失败: {e}")


def is_online(timeout: float = 5.0, retries: int = 2) -> bool:
    """真实探活。不要用 get_queue() 判断在线：它在失败时返回 {}，会让状态永远是 online。

    `timeout` 5s + 重试 2 次：ComfyUI 刚重启、加载模型或跑图重负载时，`/queue` 可能
    在 2 秒内不应答；旧的 2s 单次探活会把这种"忙"误判成"离线"，前端于是禁用提交按钮
    （实测 2026-11-04 就遇到：状态报 offline，但提交与出图都正常）。

    探活结果按 `_ONLINE_TTL_SECONDS`（15s）短缓存：离线时一次探活实测要 **8.2s**
    （反代 502 / 连接等到超时），而前端每 10s 轮询 `/api/system/status`，
    不缓存就是每次轮询都卡满一次超时 —— 顶栏「参考图库」入口实测要等 8s 才出现。
    15s 略大于轮询间隔，让轮询基本都命中缓存。
    """
    global _online_cache
    now = time.monotonic()
    if _online_cache is not None and (now - _online_cache[0]) < _ONLINE_TTL_SECONDS:
        return _online_cache[1]
    ok = _probe_online(timeout=timeout, retries=retries)
    _online_cache = (time.monotonic(), ok)
    return ok


def _probe_online(timeout: float, retries: int) -> bool:
    """真正打一次 `/queue`；`is_online` 的缓存层与它分开，便于测试直接绕过缓存。

    只有**超时**才重试：超时可能只是 ComfyUI 在跑图/加载模型（忙），值得再等一次。
    连接被拒、DNS 失败、反代 502 都是"确定不可用"，重试只会把接口拖成 8~9 秒
    （实测离线时 `/api/system/status` 要 8.2s，顶栏入口跟着晚 8s 才出现）。
    """
    for attempt in range(max(1, retries)):
        try:
            resp = get_sync_client().get(f"{COMFYUI_API}/queue", timeout=timeout)
            if resp.status_code < 500:
                return True
                # 5xx：ComfyUI 或它前面的反代明确报上游不可用，再试也不会变好
                return False
        except httpx.TimeoutException:
            pass
        except Exception:
            return False
        if attempt + 1 < retries:
            time.sleep(0.3)
    return False


def get_queue() -> dict:
    """获取 ComfyUI 队列状态（ComfyUI 重负载时响应较慢，提高超时）"""
    result = fetch_json(f"{COMFYUI_API}/queue", timeout=30)
    return result or {}


def get_history(max_items: int = 100) -> dict:
    """获取 ComfyUI 最近历史（限制条数以加速），超时随条数自动缩放"""
    timeout = max(5, min(30, max_items // 20))  # 100条=5s, 500条=25s, 上限30s
    result = fetch_json(f"{COMFYUI_API}/history?max_items={max_items}", timeout=timeout)
    return result or {}


def get_progress() -> dict | None:
    """获取当前任务的实时进度"""
    return fetch_json(f"{COMFYUI_API}/progress", timeout=3)


def interrupt():
    """中断当前任务"""
    post_comfyui("/interrupt", timeout=3)


def delete_queue_items(prompt_ids: list[str]) -> bool:
    """从 ComfyUI 队列里定向删除指定 prompt。

    取消单个任务时用它代替 clear_queue()：后者会把别的任务一起清掉。
    ComfyUI 的 /queue 接口接受 {"delete": [prompt_id, ...]}。
    """
    if not prompt_ids:
        return True
    resp = post_comfyui("/queue", data={"delete": prompt_ids}, timeout=5)
    return bool(resp and resp.status_code < 400)


def clear_queue():
    """清空队列"""
    post_comfyui("/queue", data={"clear": True}, timeout=3)


def get_history_for_prompt(prompt_id: str) -> dict | None:
    """获取特定 prompt_id 的历史"""
    return fetch_json(f"{COMFYUI_API}/history/{prompt_id}", timeout=5)
