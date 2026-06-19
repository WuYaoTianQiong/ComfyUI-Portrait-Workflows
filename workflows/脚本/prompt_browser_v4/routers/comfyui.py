"""ComfyUI 代理 —— 状态 / 图片 / 缩略图 / 跑图 / 批量生成"""
import json
import mimetypes
import os
import traceback
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel

from config import settings
from models import Prompt
from services.thumbnail import generate_thumbnail
from services.workflow_parser import load_workflow, inject_prompt
from services.comfyui_client import push_prompt, get_queue as fetch_queue
from routers.jobs import create_job, update_job_items
from state import batch_stop_flag

router = APIRouter(tags=["ComfyUI"])

COMFYUI_API = settings.comfyui_api


# ---------- Pydantic schemas ----------

class RunRequest(BaseModel):
    id: int
    workflow_path: str = ""
    workflow_content: str | None = None
    orientation: str = "portrait"
    quality: str = "4K"
    seed_override: int = 0


class BatchItem(BaseModel):
    prompt_id: int
    seed: int = 0


class BatchRequest(BaseModel):
    items: list[BatchItem]
    workflow_path: str = ""
    workflow_content: str | None = None
    orientation: str = "portrait"
    quality: str = "4K"
    title: str = "批量生成"


# ---------- Status ----------

@router.get("/status")
def check_status():
    try:
        queue = fetch_queue()
        return {
            "comfyui": "online",
            "queue_running": len(queue.get("queue_running", [])),
            "queue_pending": len(queue.get("queue_pending", [])),
        }
    except Exception:
        return {"comfyui": "offline", "queue_running": 0, "queue_pending": 0}


# ---------- 图片代理 ----------

def _find_image_locally(filename: str, subfolder: str, img_type: str) -> Path | None:
    """在本地 ComfyUI 目录查找图片"""
    if img_type == "input":
        base = settings.comfyui_root / "input"
    else:
        base = settings.comfyui_root / "output"
    path = base / (subfolder or "") / filename if subfolder else base / filename
    return path if path.exists() else None


@router.get("/image")
def proxy_image(
    filename: str = Query(...),
    subfolder: str = Query(""),
    type: str = Query("output"),
):
    # 优先读本地文件（ComfyUI 离线也能用）
    local = _find_image_locally(filename, subfolder, type)
    if local:
        mt, _ = mimetypes.guess_type(str(local))
        return FileResponse(
            str(local),
            media_type=mt or "image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    # 本地没有，代理到 ComfyUI
    url = (
        f"{COMFYUI_API}/view"
        f"?filename={quote(filename)}"
        f"&subfolder={quote(subfolder)}"
        f"&type={quote(type)}"
    )
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
        return StreamingResponse(
            iter([resp.content]),
            media_type=resp.headers.get("Content-Type", "image/png"),
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except httpx.ConnectError:
        raise HTTPException(503, "ComfyUI 未运行，本地也无此文件")
    except Exception as e:
        raise HTTPException(500, f"获取图片失败: {e}")


@router.get("/thumbnail")
def serve_thumbnail(
    filename: str = Query(...),
    subfolder: str = Query(""),
    type: str = Query("output"),
    size: int = Query(300),
):
    thumb_path = generate_thumbnail(filename, subfolder, type, size)
    if thumb_path is None:
        raise HTTPException(404, "无法生成缩略图")
    return FileResponse(
        str(thumb_path),
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=604800"},
    )


@router.get("/validate_workflow")
def validate_workflow(path: str = Query("")):
    if not path or not os.path.exists(path):
        return {"valid": False, "error": "文件不存在"}
    try:
        with open(path, "r", encoding="utf-8") as f:
            wf = json.load(f)
        has_clip = any(
            isinstance(v, dict) and v.get("class_type") == "CLIPTextEncode"
            for v in wf.values()
        )
        return {"valid": has_clip, "name": os.path.basename(path)}
    except Exception as e:
        return {"valid": False, "error": str(e)}


# ---------- 单图跑图 ----------

@router.post("/run")
def run_prompt(req: RunRequest):
    """单图生成"""
    p = Prompt.get_or_none(Prompt.id == req.id)
    if p is None:
        raise HTTPException(404, "提示词不存在")

    workflow_path = req.workflow_path or ""
    if not workflow_path:
        raise HTTPException(400, "缺少工作流路径")

    try:
        # 加载并解析工作流
        api_wf = load_workflow(workflow_path, req.workflow_content)

        # 注入提示词
        prompt_data = {
            "prompt": p.prompt or "",
            "negative_prompt": p.negative_prompt or "",
            "seed": p.seed or 0,
            "seed_override": req.seed_override,
            "orientation": req.orientation,
            "quality": req.quality,
        }
        inject_prompt(api_wf, prompt_data)

        # 创建任务记录
        items = [{
            "prompt_id": req.id,
            "seed": req.seed_override or (p.seed or 0),
            "prompt_preview": (p.name or p.prompt or "")[:40],
        }]
        job_id = create_job("single", "单图生成", items, workflow_path, req.orientation, req.quality)

        # 推送 ComfyUI
        result = push_prompt(api_wf)
        comfy_pid = result.get("prompt_id", "")
        items[0]["comfyui_prompt_id"] = comfy_pid
        items[0]["status"] = "pending"
        update_job_items(job_id, items, status="running")

        dims = ""
        if p.width and p.height:
            dims = f"{p.width}×{p.height}"

        return {"success": True, "job_id": job_id, "result": result, "dimensions": dims}

    except FileNotFoundError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"{type(e).__name__}: {e}")


# ---------- 批量生成 ----------

@router.post("/batch_generate")
def batch_generate(req: BatchRequest):
    """批量 / 变体生成"""
    if not req.items:
        raise HTTPException(400, "缺少 items")

    workflow_path = req.workflow_path or ""

    # 创建任务记录
    items_raw = [{"prompt_id": it.prompt_id, "seed": it.seed} for it in req.items]
    job_id = create_job(
        "batch", req.title,
        items_raw, workflow_path,
        req.orientation, req.quality,
    )

    results = []
    errors = []

    for i, item in enumerate(req.items):
        # 检查停止标志
        if batch_stop_flag.is_set():
            items_raw[i]["status"] = "cancelled"
            items_raw[i]["error"] = "已取消"
            errors.append({"index": i, "prompt_id": item.prompt_id, "error": "已取消"})
            continue

        pid = item.prompt_id
        if not pid:
            items_raw[i]["status"] = "error"
            items_raw[i]["error"] = "缺少 prompt_id"
            errors.append({"index": i, "error": "缺少 prompt_id"})
            continue

        p = Prompt.get_or_none(Prompt.id == pid)
        if p is None:
            items_raw[i]["status"] = "error"
            items_raw[i]["error"] = f"提示词 {pid} 不存在"
            errors.append({"index": i, "prompt_id": pid, "error": f"提示词 {pid} 不存在"})
            continue

        try:
            api_wf = load_workflow(workflow_path, req.workflow_content)
            prompt_data = {
                "prompt": p.prompt or "",
                "negative_prompt": p.negative_prompt or "",
                "seed": p.seed or 0,
                "seed_override": item.seed,
                "orientation": req.orientation,
                "quality": req.quality,
            }
            inject_prompt(api_wf, prompt_data)

            result = push_prompt(api_wf)
            comfy_pid = result.get("prompt_id", "")
            items_raw[i]["comfyui_prompt_id"] = comfy_pid
            items_raw[i]["status"] = "pending"
            items_raw[i]["prompt_preview"] = (p.name or p.prompt or "")[:40]
            results.append({"index": i, "prompt_id": pid, "comfyui_prompt_id": comfy_pid})
        except Exception as e:
            traceback.print_exc()
            items_raw[i]["status"] = "error"
            items_raw[i]["error"] = str(e)
            errors.append({"index": i, "prompt_id": pid, "error": str(e)})

    batch_stop_flag.clear()
    status = "running" if results else "error"
    update_job_items(job_id, items_raw, status=status)

    return {"success": len(results) > 0, "job_id": job_id, "results": results, "errors": errors}
