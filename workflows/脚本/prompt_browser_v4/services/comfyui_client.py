"""ComfyUI API 客户端 —— 所有与 ComfyUI 的 HTTP 交互"""
import json
import logging

import httpx

from config import settings

logger = logging.getLogger("prompt_browser.comfy")

COMFYUI_API = settings.comfyui_api


def fetch_json(url: str, timeout: int = 5) -> dict | None:
    """GET 请求 ComfyUI 并返回 JSON"""
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()
    except Exception:
        return None


def post_comfyui(path: str, data: dict | None = None, timeout: int = 5) -> httpx.Response | None:
    """POST 请求 ComfyUI"""
    try:
        body = json.dumps(data).encode("utf-8") if data is not None else b""
        headers = {"Content-Type": "application/json"} if data is not None else {}
        with httpx.Client(timeout=timeout) as client:
            return client.post(f"{COMFYUI_API}{path}", content=body, headers=headers)
    except Exception:
        return None


def push_prompt(api_workflow: dict) -> dict:
    """将工作流推送到 ComfyUI，返回 {prompt_id, ...}"""
    payload = json.dumps({"prompt": api_workflow}).encode("utf-8")
    logger.debug("提交 ComfyUI：nodes=%d first=%s", len(api_workflow), list(api_workflow.keys())[:10])

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                f"{COMFYUI_API}/prompt",
                content=payload,
                headers={"Content-Type": "application/json"},
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


def is_online(timeout: float = 2.0) -> bool:
    """真实探活。不要用 get_queue() 判断在线：它在失败时返回 {}，会让状态永远是 online。"""
    try:
        with httpx.Client(timeout=timeout) as client:
            return client.get(f"{COMFYUI_API}/queue").status_code < 500
    except Exception:
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
