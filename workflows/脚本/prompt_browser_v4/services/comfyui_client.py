"""ComfyUI API 客户端 —— 所有与 ComfyUI 的 HTTP 交互"""
import json

import httpx

from config import settings

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
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                f"{COMFYUI_API}/prompt",
                content=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as e:
        raise RuntimeError(f"ComfyUI 连接失败: {e}")


def get_queue() -> dict:
    """获取 ComfyUI 队列状态"""
    result = fetch_json(f"{COMFYUI_API}/queue", timeout=3)
    return result or {}


def get_history() -> dict:
    """获取 ComfyUI 全局历史"""
    result = fetch_json(f"{COMFYUI_API}/history", timeout=5)
    return result or {}


def get_progress() -> dict | None:
    """获取当前任务的实时进度"""
    return fetch_json(f"{COMFYUI_API}/progress", timeout=3)


def interrupt():
    """中断当前任务"""
    post_comfyui("/interrupt", timeout=3)


def clear_queue():
    """清空队列"""
    post_comfyui("/queue", data={"clear": True}, timeout=3)


def get_history_for_prompt(prompt_id: str) -> dict | None:
    """获取特定 prompt_id 的历史"""
    return fetch_json(f"{COMFYUI_API}/history/{prompt_id}", timeout=5)
