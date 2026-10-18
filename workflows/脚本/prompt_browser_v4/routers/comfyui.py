"""ComfyUI 代理 —— 状态 / 图片 / 缩略图 / 工作流列表 / 跑图 / 批量生成"""
import json
import mimetypes
import os
import re
import traceback
from pathlib import Path
from urllib.parse import quote

import httpx
from io import BytesIO
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse, FileResponse
from PIL import Image
from pydantic import BaseModel

from config import settings
from models import Prompt, PromptCategory, Category
from services.helpers import _resolve_if_reparse, missing_image_response
from services.thumbnail import generate_thumbnail
from services.workflow_parser import load_workflow, inject_prompt
from services.comfyui_client import push_prompt, get_queue as fetch_queue
from routers.jobs import create_job, update_job_items
from state import batch_stop_flag

router = APIRouter(tags=["ComfyUI"])

DEPRECATED_DIR = settings.project_root / "废弃工作流"


def _is_valid_workflow(filepath: Path) -> bool:
    try:
        content = json.loads(filepath.read_text(encoding="utf-8"))
        # API 格式：扁平 {节点id: {class_type: ...}}
        if any(isinstance(v, dict) and "class_type" in v for v in content.values()):
            return True
        # 界面格式：{nodes: [...]}。load_workflow/ensure_api_format 能直接转换，
        # 与 /validate_workflow 的判定保持一致（旧逻辑只认 API 格式，
        # 导致界面里保存的工作流全部不出现在下拉列表中）。
        nodes = content.get("nodes")
        return isinstance(nodes, list) and any(
            isinstance(n, dict) and n.get("type") for n in nodes
        )
    except Exception:
        return False


def _find_default_workflow() -> str:
    candidates = []
    for d in [settings.project_root, DEPRECATED_DIR]:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.json")):
            try:
                if _is_valid_workflow(f):
                    candidates.append(str(f))
            except Exception:
                continue
    for c in candidates:
        if "文生图" in c:
            return c
    return candidates[0] if candidates else ""

COMFYUI_API = settings.comfyui_api


# ---------- Pydantic schemas ----------

class RunRequest(BaseModel):
    id: int
    workflow_path: str = ""
    workflow_content: str | None = None
    orientation: str = "portrait"
    quality: str = "4K"
    seed_override: int = 0


class RunTextRequest(BaseModel):
    prompt: str = ""
    negative_prompt: str = ""
    workflow_path: str = ""
    workflow_content: str | None = None
    orientation: str = "portrait"
    quality: str = "4K"
    seed: int = 0
    source_prompt_id: int = 0  # 试跑来源提示词 ID，0 表示无来源


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


class GenerateMissingRequest(BaseModel):
    """为所有「没有生成过图片」的提示词批量出图"""
    workflow_path: str = ""
    workflow_content: str | None = None
    orientation: str = "portrait"
    quality: str = "4K"
    prompt_ids: list[int] | None = None  # 可选：仅补全指定提示词（与缺图集合取交集）


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
    base = _resolve_if_reparse(base)
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
            headers={"Cache-Control": "no-cache"},
        )

    # 本地没有，代理到 ComfyUI（带超时，避免阻塞整个服务）
    url = (
        f"{COMFYUI_API}/view"
        f"?filename={quote(filename)}"
        f"&subfolder={quote(subfolder)}"
        f"&type={quote(type)}"
    )
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(url)
            if resp.status_code in (400, 404):
                # 本地没有 + ComfyUI 也没有 = 文件真的没了 → 给占位图，不再刷 404
                return missing_image_response()
            resp.raise_for_status()
            content = resp.content
            media_type = resp.headers.get("Content-Type", "image/png")
    except httpx.ConnectError:
        # ComfyUI 没开，本地也没有这个文件 → 同样属于"取不到图"
        return missing_image_response()
    except httpx.TimeoutException:
        raise HTTPException(504, "获取图片超时（ComfyUI 响应过慢）")
    except Exception as e:
        raise HTTPException(500, f"获取图片失败: {e}")

    # 把代理回来的图片落盘到本地，下次直接走本地路径，不再代理
    _cache_proxied_image(filename, subfolder, type, content)

    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Cache-Control": "no-cache"},
    )


def _cache_proxied_image(filename: str, subfolder: str, img_type: str, content: bytes) -> None:
    """将代理获取到的图片保存到 ComfyUI 本地目录，便于后续直接读取。"""
    try:
        if img_type == "input":
            base = settings.comfyui_root / "input"
        else:
            base = settings.comfyui_root / "output"
        base = _resolve_if_reparse(base)
        target_dir = base / (subfolder or "")
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / filename).write_bytes(content)
    except Exception:
        # 落盘失败不影响本次返回
        pass


def _fetch_remote_image(filename: str, subfolder: str, img_type: str) -> bytes | None:
    """从 ComfyUI /view 代理取回原图字节（带超时，失败返回 None）。"""
    url = (
        f"{COMFYUI_API}/view"
        f"?filename={quote(filename)}"
        f"&subfolder={quote(subfolder)}"
        f"&type={quote(img_type)}"
    )
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(url)
            if resp.status_code in (404, 400):
                return None
            resp.raise_for_status()
            return resp.content
    except (httpx.ConnectError, httpx.TimeoutException):
        return None
    except Exception:
        return None


@router.get("/thumbnail")
def serve_thumbnail(
    filename: str = Query(...),
    subfolder: str = Query(""),
    type: str = Query("output"),
    size: int = Query(300),
    v: str = Query(None),  # cache-busting 版本号，仅用于生成不同 URL，不参与处理逻辑
):
    thumb_path = generate_thumbnail(filename, subfolder, type, size)
    if thumb_path is not None:
        return FileResponse(
            str(thumb_path),
            media_type="image/webp",
            headers={"Cache-Control": "no-cache"},
        )

    # 本地原图不存在：回退到 ComfyUI 代理取图并即时生成缩略图
    # （与 /api/image 一致，解决历史图片已不在本地磁盘时缩略图裂图的问题）
    raw = _fetch_remote_image(filename, subfolder, type)
    if raw is None:
        # 文件确实没了：返回「文件缺失」占位图（200），避免画廊/工作台里刷一屏 404
        return missing_image_response()
    try:
        with Image.open(BytesIO(raw)) as img:
            img.thumbnail((size, size), Image.LANCZOS)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            buf = BytesIO()
            img.save(buf, "WEBP", quality=80)
            buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="image/webp",
            headers={"Cache-Control": "no-cache"},
        )
    except Exception:
        return missing_image_response()


@router.post("/thumbnail/clear")
def clear_thumbnail_cache():
    """清空所有缩略图缓存文件。下次访问时自动按新缓存键重新生成。"""
    from config import settings
    import shutil
    import os

    td = settings.thumbnail_dir
    count = 0
    if td.exists():
        count = len(list(td.glob("*.webp")))
        shutil.rmtree(td)
        td.mkdir(parents=True, exist_ok=True)
    return {"success": True, "deleted": count}


@router.get("/validate_workflow")
def validate_workflow(path: str = Query("")):
    """验证工作流文件是否合法（仅检查格式，不要求特定节点类型）"""
    if not path or not os.path.exists(path):
        return {"valid": False, "error": "文件不存在"}
    try:
        with open(path, "r", encoding="utf-8") as f:
            wf = json.load(f)
        # 仅检查是否为合法的 ComfyUI 工作流格式（API 格式或 UI 格式）
        if isinstance(wf, dict):
            # API 格式：至少包含一个节点（key 为数字字符串，value 含 class_type）
            if any("class_type" in v for v in wf.values() if isinstance(v, dict)):
                return {"valid": True, "name": os.path.basename(path)}
            # UI 格式：包含 nodes 数组
            if "nodes" in wf and isinstance(wf["nodes"], list):
                return {"valid": True, "name": os.path.basename(path)}
        return {"valid": False, "error": "不支持的工作流格式"}
    except Exception as e:
        return {"valid": False, "error": str(e)}


# ---------- 工作流列表与配置 ----------

@router.get("/workflows")
def list_workflows(sort: str = Query("mtime")):
    """列出所有可用工作流"""
    results: list[dict] = []
    seen: set[str] = set()

    for d in [settings.project_root, DEPRECATED_DIR]:
        if not d.exists():
            continue
        for f in d.glob("*.json"):
            if not _is_valid_workflow(f):
                continue
            fp = str(f)
            if fp not in seen:
                seen.add(fp)
                results.append({
                    "path": fp,
                    "name": f.name,
                    "mtime": f.stat().st_mtime,
                })

    if sort == "mtime":
        results.sort(key=lambda x: x["mtime"], reverse=True)
    else:
        results.sort(key=lambda x: x["name"])

    return {"workflows": results, "default": _find_default_workflow()}


@router.get("/config")
def get_config():
    """返回默认工作流和数据库路径等配置"""
    default = _find_default_workflow()
    return {
        "workflow_path": default,
        "workflow_name": Path(default).name if default else "未设置",
        "db_path": str(settings.db_path),
    }


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

        # 注入提示词：传 ComfyUI 时去掉【】碎片标题
        clean_prompt = re.sub(r'【[^】]+】\s*', '', p.prompt or "")
        prompt_data = {
            "prompt": clean_prompt,
            "negative_prompt": p.negative_prompt or "",
            "seed": p.seed or 0,
            "seed_override": req.seed_override,
            "orientation": req.orientation,
            "quality": req.quality,
        }
        inject_prompt(api_wf, prompt_data)

        # 创建任务记录
        prompt_params = {
            "prompt": clean_prompt,
            "negative_prompt": p.negative_prompt or "",
            "seed": req.seed_override or (p.seed or 0),
            "steps": p.steps, "cfg_scale": p.cfg_scale,
            "sampler": p.sampler or "", "model": p.model or "",
            "width": p.width, "height": p.height,
            "source": "prompt_run",
        }
        items = [{
            "prompt_id": req.id,
            "seed": req.seed_override or (p.seed or 0),
            "prompt_preview": (p.name or p.prompt or "")[:40],
            "prompt_params": json.dumps(prompt_params, ensure_ascii=False),
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


# ---------- 裸 prompt 跑图（无需 prompt_id） ----------

@router.post("/run_text")
def run_text_prompt(req: RunTextRequest):
    """直接提交 prompt 文本生成，无需数据库中已有记录"""
    workflow_path = req.workflow_path or ""
    if not workflow_path:
        raise HTTPException(400, "缺少工作流路径")

    try:
        api_wf = load_workflow(workflow_path, req.workflow_content)

        prompt_data = {
            "prompt": re.sub(r'【[^】]+】\s*', '', req.prompt or ""),
            "negative_prompt": req.negative_prompt or "",
            "seed": req.seed or 0,
            "orientation": req.orientation,
            "quality": req.quality,
        }
        inject_prompt(api_wf, prompt_data)

        prompt_params = {
            "prompt": req.prompt or "",
            "negative_prompt": req.negative_prompt or "",
            "seed": req.seed or 0,
            "source": "text_run",
            "source_prompt_id": req.source_prompt_id or 0,
        }
        # 试跑若指定了来源提示词，直接关联到该提示词的 history（否则关弹窗就找不到了）
        linked_prompt_id = req.source_prompt_id or 0
        items = [{
            "prompt_id": linked_prompt_id,
            "seed": req.seed or 0,
            "prompt_preview": (req.prompt or "")[:40],
            "prompt_params": json.dumps(prompt_params, ensure_ascii=False),
        }]
        job_id = create_job("single", "文本跑图", items, workflow_path, req.orientation, req.quality)

        result = push_prompt(api_wf)
        comfy_pid = result.get("prompt_id", "")
        items[0]["comfyui_prompt_id"] = comfy_pid
        items[0]["status"] = "pending"
        update_job_items(job_id, items, status="running")

        return {"success": True, "job_id": job_id, "result": result}

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
                "prompt": re.sub(r'【[^】]+】\s*', '', p.prompt or ""),
                "negative_prompt": p.negative_prompt or "",
                "seed": p.seed or 0,
                "seed_override": item.seed,
                "steps": p.steps,
                "cfg_scale": p.cfg_scale,
                "sampler": p.sampler,
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


# ---------- 补全缺图 ----------

def _missing_prompt_ids():
    """返回所有「没有生成过图片」的提示词 ID 列表（DB 关联判定）。

    缺图判定：GenHistory 中不存在该 prompt_id 的未删除记录，即视为缺图。
    """
    from models import GenHistory

    have_ids = {
        r.prompt_id
        for r in GenHistory
        .select(GenHistory.prompt_id)
        .where(
            (GenHistory.is_deleted == False)
            & (GenHistory.prompt_id.is_null(False))
        )
        .distinct()
    }
    return [p.id for p in Prompt.select(Prompt.id).order_by(Prompt.id)
            if p.id not in have_ids]


@router.get("/generate_missing/count")
def generate_missing_count():
    """仅统计缺图提示词数量，不触发出图（供前端二次确认使用）。"""
    missing_ids = _missing_prompt_ids()
    total = Prompt.select().count()
    return {"count": len(missing_ids), "total": total}


@router.get("/generate_missing/list")
def generate_missing_list():
    """返回所有缺图提示词的概要清单，供前端审核模态框展示与勾选。"""
    missing_ids = _missing_prompt_ids()
    if not missing_ids:
        return {"items": []}
    # 分类映射（一个提示词可能多个分类）
    cat_rows = (
        PromptCategory
        .select(PromptCategory.prompt, Category.name)
        .join(Category)
        .where(PromptCategory.prompt.in_(missing_ids))
    )
    cat_map: dict = {}
    for r in cat_rows:
        cat_map.setdefault(r.prompt_id, []).append(r.category.name)
    prompts = {p.id: p for p in Prompt.select().where(Prompt.id.in_(missing_ids))}
    items = []
    for pid in missing_ids:
        p = prompts.get(pid)
        if not p:
            continue
        items.append({
            "id": p.id,
            "name": p.name or "(未命名)",
            "category": ", ".join(cat_map.get(pid, [])),
            "steps": p.steps,
            "cfg_scale": p.cfg_scale,
            "sampler": p.sampler,
            "seed": p.seed,
            "model": p.model,
            "width": p.width,
            "height": p.height,
        })
    return {"items": items}


@router.post("/generate_missing")
def generate_missing(req: GenerateMissingRequest):
    """为所有「没有生成过图片」的提示词统一批量出图。

    缺图判定（DB 关联）：GenHistory 中不存在该 prompt_id 的未删除记录，即视为缺图。
    每条提示词使用其自身保存的参数（steps/cfg/sampler/seed/分辨率），
    实际出图逻辑完全复用 batch_generate。
    """
    # 缺图集合（DB 关联判定）：复用辅助函数
    missing_ids = _missing_prompt_ids()
    if req.prompt_ids:  # 仅补全用户勾选的子集（与缺图集合取交集，防御重复出图）
        want = set(req.prompt_ids)
        missing_ids = [pid for pid in missing_ids if pid in want]

    if not missing_ids:
        return {
            "success": True, "job_id": None, "count": 0,
            "results": [], "errors": [],
            "message": "所有提示词都已有图片，无需补全",
        }

    batch_req = BatchRequest(
        items=[BatchItem(prompt_id=pid, seed=0) for pid in missing_ids],
        workflow_path=req.workflow_path,
        workflow_content=req.workflow_content,
        orientation=req.orientation,
        quality=req.quality,
        title=f"补全缺图 ({len(missing_ids)} 条)",
    )
    result = batch_generate(batch_req)
    result["count"] = len(missing_ids)
    return result
