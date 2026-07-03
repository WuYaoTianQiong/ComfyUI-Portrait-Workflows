"""历史记录"""
import json
import traceback
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from config import settings
from models import GenHistory as Gh, Prompt
from services.helpers import build_view_url, get_image_metadata
from shared import templates

router = APIRouter(tags=["历史"])

COMFYUI_API = settings.comfyui_api
OUTPUT_ROOT = settings.comfyui_root / "output"


# ---------------------------------------------------------------------------
# Pydantic
# ---------------------------------------------------------------------------

class BatchDeleteRequest(BaseModel):
    ids: list[int]


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _image_exists(filename: str, subfolder: str, img_type: str) -> bool:
    meta = get_image_metadata(filename, subfolder or "", img_type or "output")
    return bool(meta)


def _enrich_item(r, prompt_cache=None) -> dict:
    meta = get_image_metadata(r.filename, r.subfolder or "", r.img_type or "output")
    prompt_params = json.loads(r.prompt_params) if r.prompt_params else None

    # 补写逻辑：如果 prompt_params 为空且有 job_id，尝试从 job items 里找回
    if prompt_params is None and r.job_id:
        try:
            from models import GenJob
            job = GenJob.get_or_none(GenJob.id == r.job_id)
            if job and job.items:
                items = json.loads(job.items) if isinstance(job.items, str) else job.items
                for it in items:
                    if it.get("comfyui_prompt_id") == r.comfyui_prompt_id and it.get("prompt_params"):
                        # 补写到数据库，下次就不需要再查了
                        Gh.update(prompt_params=it["prompt_params"]).where(Gh.id == r.id).execute()
                        prompt_params = json.loads(it["prompt_params"]) if isinstance(it["prompt_params"], str) else it["prompt_params"]
                        break
        except Exception:
            pass

    item = {
        "id": r.id,
        "job_id": r.job_id,
        "prompt_id": r.prompt_id,
        "comfyui_prompt_id": r.comfyui_prompt_id,
        "filename": r.filename,
        "subfolder": r.subfolder,
        "img_type": r.img_type,
        "view_url": r.view_url,
        "preview": r.preview,
        "favorite": bool(r.favorite),
        "prompt_params": prompt_params,
        "created_at": str(r.created_at) if r.created_at else "",
        "source": r.source,
        "prompt_name": "",  # 默认空字符串
        **meta,
    }
    # 优先从缓存获取提示词名称
    if r.prompt_id and prompt_cache:
        item["prompt_name"] = prompt_cache.get(r.prompt_id, "")
    # 如果缓存中没有，直接从数据库查询
    if r.prompt_id and not item["prompt_name"]:
        try:
            from models import Prompt
            prompt = Prompt.get_or_none(Prompt.id == r.prompt_id)
            if prompt:
                item["prompt_name"] = prompt.name
        except Exception:
            pass
    return item


def _sync_comfyui_history() -> int:
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{COMFYUI_API}/history")
            resp.raise_for_status()
            hist = resp.json()
    except httpx.ConnectError:
        return 0
    except Exception:
        traceback.print_exc()
        return 0

    if not hist:
        return 0

    added = 0
    for pid, data in hist.items():
        outputs = data.get("outputs", {})
        # 尝试从 ComfyUI history 的 extra_data 提取 prompt_id
        extra = data.get("extra_data") or {}
        prompt_id = extra.get("prompt_id")

        for node_out in outputs.values():
            for img in node_out.get("images", []):
                try:
                    Gh.insert(
                        job_id=None,
                        prompt_id=prompt_id,
                        comfyui_prompt_id=pid,
                        filename=img["filename"],
                        subfolder=img.get("subfolder", ""),
                        img_type=img.get("type", "output"),
                        view_url=build_view_url(
                            img["filename"],
                            img.get("subfolder", ""),
                            img.get("type", "output"),
                        ),
                        preview="",
                        prompt_params=None,
                        favorite=False,
                        source="comfyui_sync",
                    ).on_conflict_ignore().execute()
                    added += 1
                except Exception:
                    pass
    return added


def _build_prompt_cache(rows) -> dict:
    prompt_ids = [r.prompt_id for r in rows if r.prompt_id]
    if not prompt_ids:
        return {}
    return {r.id: r.name for r in Prompt.select(Prompt.id, Prompt.name).where(Prompt.id << prompt_ids)}


# ---------------------------------------------------------------------------
# 查询（支持筛选 / 排序 / 搜索）
# ---------------------------------------------------------------------------

@router.get("/history")
def list_history(
    page: int = Query(1),
    page_size: int = Query(50),
    favorite: bool = Query(None),
    sort: str = Query("newest"),
    search: str = Query(""),
):
    q = Gh.select().where(Gh.is_deleted == False)
    if favorite is not None:
        q = q.where(Gh.favorite == favorite)

    if search:
        like = f"%{search}%"
        condition = (
            (Gh.filename ** like)
            | (Gh.subfolder ** like)
            | (Gh.comfyui_prompt_id ** like)
        )
        prompt_matches = [r.id for r in Prompt.select(Prompt.id).where(Prompt.name ** like)]
        if prompt_matches:
            condition = condition | (Gh.prompt_id << prompt_matches)
        q = q.where(condition)

    total = q.count()

    offset = (page - 1) * page_size
    q = q.order_by(Gh.id.desc()).offset(offset).limit(page_size)
    rows = list(q)

    deleted_ids = []
    alive = []
    for r in rows:
        if not _image_exists(r.filename, r.subfolder or "", r.img_type or "output"):
            deleted_ids.append(r.id)
            continue
        alive.append(r)

    if deleted_ids:
        Gh.delete().where(Gh.id.in_(deleted_ids)).execute()

    def _get_meta(item):
        return get_image_metadata(item.filename, item.subfolder or "", item.img_type or "output")

    if sort == "oldest":
        alive.sort(key=lambda r: r.id)
    elif sort == "size_asc":
        alive.sort(key=lambda r: _get_meta(r).get("file_size", 0) or 0)
    elif sort == "size_desc":
        alive.sort(key=lambda r: _get_meta(r).get("file_size", 0) or 0, reverse=True)
    elif sort == "res_asc":
        alive.sort(key=lambda r: (_get_meta(r).get("width", 0) or 0))
    elif sort == "res_desc":
        alive.sort(key=lambda r: (_get_meta(r).get("width", 0) or 0), reverse=True)

    cache = _build_prompt_cache(alive)
    result = [_enrich_item(r, cache) for r in alive]
    return {"items": result, "total": total, "page": page, "page_size": page_size}


# ---------------------------------------------------------------------------
# 同步
# ---------------------------------------------------------------------------

@router.api_route("/history_sync", methods=["GET", "POST"])
def sync_history(page_size: int = Query(500)):
    added = _sync_comfyui_history()
    data = list_history(page=1, page_size=page_size, favorite=None, sort="newest", search="")
    return {"added": added, "items": data["items"], "total": data["total"]}


# ---------------------------------------------------------------------------
# 单条删除
# ---------------------------------------------------------------------------

@router.delete("/history/{item_id}")
def delete_history_item(item_id: int):
    r = Gh.get_or_none(Gh.id == item_id)
    if r is None:
        raise HTTPException(404, "历史记录不存在")
    # 软删除：标记而非真删，防止 sync 重新导入
    Gh.update(is_deleted=True).where(Gh.id == item_id).execute()
    # 清理缩略图（按文件名前缀匹配）
    try:
        thumb_dir = settings.thumbnail_dir
        if r.filename:
            prefix = r.filename.replace("/", "_").replace("\\", "_").replace(":", "_")
            for f in thumb_dir.glob(f"{prefix}*"):
                f.unlink()
    except Exception:
        pass
    return {"success": True}


# ---------------------------------------------------------------------------
# 批量删除
# ---------------------------------------------------------------------------

@router.post("/history/batch_delete")
def batch_delete_history(body: BatchDeleteRequest):
    ids = body.ids
    if not ids:
        return {"success": True, "deleted": 0}
    cnt = Gh.update(is_deleted=True).where(Gh.id.in_(ids)).execute()
    # 批量清理缩略图
    try:
        thumb_dir = settings.thumbnail_dir
        for r in Gh.select().where(Gh.id.in_(ids)):
            if r.filename:
                prefix = r.filename.replace("/", "_").replace("\\", "_").replace(":", "_")
                for f in thumb_dir.glob(f"{prefix}*"):
                    f.unlink()
    except Exception:
        pass
    return {"success": True, "deleted": cnt}


# ---------------------------------------------------------------------------
# 收藏切换
# ---------------------------------------------------------------------------

@router.post("/history/{item_id}/favorite")
def toggle_favorite(item_id: int):
    r = Gh.get_or_none(Gh.id == item_id)
    if r is None:
        raise HTTPException(404, "历史记录不存在")
    new_val = not bool(r.favorite)
    Gh.update(favorite=new_val).where(Gh.id == item_id).execute()
    return {"success": True, "favorite": new_val}


# ---------------------------------------------------------------------------
# 下载图片
# ---------------------------------------------------------------------------

@router.get("/history/{item_id}/download")
def download_history_item(item_id: int):
    r = Gh.get_or_none(Gh.id == item_id)
    if r is None:
        raise HTTPException(404, "历史记录不存在")

    img_path = OUTPUT_ROOT / (r.subfolder or "") / r.filename
    if not img_path.exists():
        raise HTTPException(404, "图片文件不存在")

    # 推断 media_type
    suffix = (r.filename or "").lower().split(".")[-1]
    type_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "webp": "image/webp", "gif": "image/gif"}
    media = type_map.get(suffix, "application/octet-stream")

    return FileResponse(
        path=str(img_path),
        filename=r.filename,
        media_type=media,
    )


# ---------------------------------------------------------------------------
# 清空
# ---------------------------------------------------------------------------

@router.delete("/history")
def clear_history():
    Gh.update(is_deleted=True).execute()
    # 清理全部缩略图
    try:
        import shutil
        td = settings.thumbnail_dir
        if td.exists():
            shutil.rmtree(td)
            td.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return {"success": True}


# ====================================================================
# Phase 2: HTMX 端点 —— 返回历史画廊的 HTML 片段
# ====================================================================

@router.get("/history/html", response_class=HTMLResponse)
def history_list_html(
    request: Request,
    page: int = Query(1),
    page_size: int = Query(50),
    favorite: str = Query(""),
    sort: str = Query("newest"),
    search: str = Query(""),
):
    q = Gh.select().where(Gh.is_deleted == False)
    if favorite:
        q = q.where(Gh.favorite == (favorite == "1"))
    if search:
        like = f"%{search}%"
        condition = ((Gh.filename ** like) | (Gh.subfolder ** like) | (Gh.comfyui_prompt_id ** like))
        prompt_matches = [r.id for r in Prompt.select(Prompt.id).where(Prompt.name ** like)]
        if prompt_matches:
            condition = condition | (Gh.prompt_id << prompt_matches)
        q = q.where(condition)
    total = q.count()
    rows = q.order_by(Gh.id.desc()).offset((page - 1) * page_size).limit(page_size)
    items = []
    for r in rows:
        meta = get_image_metadata(r.filename, r.subfolder or "", r.img_type or "output")
        prompt_params = json.loads(r.prompt_params) if r.prompt_params else None
        prompt_name = ""
        if r.prompt_id:
            p = Prompt.get_or_none(Prompt.id == r.prompt_id)
            if p:
                prompt_name = p.name or ""
        items.append({
            "id": r.id, "job_id": r.job_id, "prompt_id": r.prompt_id,
            "comfyui_prompt_id": r.comfyui_prompt_id,
            "filename": r.filename, "subfolder": r.subfolder or "", "img_type": r.img_type or "output",
            "view_url": r.view_url, "favorite": bool(r.favorite),
            "prompt_params": prompt_params,
            "created_at": str(r.created_at) if r.created_at else "",
            "prompt_name": prompt_name,
            **meta,
        })
    return templates.TemplateResponse("history/list.jinja2", {
        "request": request, "items": items, "total": total,
        "page": page, "page_size": page_size, "sort": sort,
        "favorite": favorite, "search": search,
    })


# ====================================================================
# 新增：以历史图片为输入，使用指定工作流处理（超分/重绘等）
# ====================================================================

class ProcessImageRequest(BaseModel):
    workflow_path: str
    workflow_content: str | None = None
    orientation: str = "portrait"
    quality: str = "4K"


@router.post("/history/{item_id}/process")
def process_history_image(item_id: int, data: ProcessImageRequest):
    """将历史图片作为输入，用指定工作流处理（如超分、重绘等）"""
    r = Gh.get_or_none(Gh.id == item_id)
    if r is None:
        raise HTTPException(404, "历史记录不存在")

    # 1. 定位源图片
    from pathlib import Path
    from config import settings
    from services.workflow_parser import load_workflow, inject_prompt, inject_input_image
    from services.comfyui_client import push_prompt
    from routers.jobs import create_job, update_job_items

    if r.img_type == "input":
        src_dir = settings.comfyui_root / "input"
    else:
        src_dir = settings.comfyui_root / "output"
    src_path = src_dir / (r.subfolder or "") / r.filename if r.subfolder else src_dir / r.filename

    if not src_path.exists():
        raise HTTPException(404, f"图片文件不存在: {src_path}")

    # 2. 加载工作流
    workflow_path = data.workflow_path or ""
    if not workflow_path:
        raise HTTPException(400, "缺少工作流路径")
    try:
        api_wf = load_workflow(workflow_path, data.workflow_content)
    except Exception as e:
        raise HTTPException(400, f"工作流加载失败: {e}")

    # 3. 注入图片到 LoadImage 节点
    input_dir = settings.comfyui_root / "input"
    try:
        img_name = inject_input_image(api_wf, str(src_path), str(input_dir))
    except Exception as e:
        raise HTTPException(500, f"图片注入失败: {e}")

    # 4. 注入基础参数
    prompt_data = {
        "prompt": "", "negative_prompt": "",
        "seed": 0, "seed_override": 0,
        "orientation": data.orientation, "quality": data.quality,
    }
    inject_prompt(api_wf, prompt_data)

    # 5. 创建任务
    items = [{
        "prompt_id": r.prompt_id or 0, "seed": 0,
        "prompt_preview": f"处理图片: {r.filename}",
        "prompt_params": json.dumps({
            "source": "history_process",
            "history_id": item_id,
            "input_image": img_name,
            "original_filename": r.filename,
        }, ensure_ascii=False),
    }]
    job_id = create_job(
        "single", f"图片处理: {r.filename[:30]}", items,
        workflow_path, data.orientation, data.quality,
    )

    # 6. 推送 ComfyUI
    try:
        result = push_prompt(api_wf)
        comfy_pid = result.get("prompt_id", "")
        items[0]["comfyui_prompt_id"] = comfy_pid
        items[0]["status"] = "pending"
        update_job_items(job_id, items, status="running")
        return {"success": True, "job_id": job_id, "result": result}
    except Exception as e:
        update_job_items(job_id, items, status="error")
        raise HTTPException(500, f"推送 ComfyUI 失败: {e}")
