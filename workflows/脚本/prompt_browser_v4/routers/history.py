"""历史记录"""
import json
import traceback
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config import settings
from models import GenHistory as Gh, Prompt
from services.helpers import build_view_url, get_image_metadata

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
        "prompt_params": json.loads(r.prompt_params) if r.prompt_params else None,
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
    limit: int = Query(200),
    favorite: bool = Query(None),
    sort: str = Query("newest"),
    search: str = Query(""),
):
    q = Gh.select()
    if favorite is not None:
        q = q.where(Gh.favorite == favorite)

    if search:
        like = f"%{search}%"
        # 搜索文件名、子目录、ComfyUI prompt_id
        condition = (
            (Gh.filename ** like)
            | (Gh.subfolder ** like)
            | (Gh.comfyui_prompt_id ** like)
        )
        # 同时搜索关联的 prompt 名称
        prompt_matches = [r.id for r in Prompt.select(Prompt.id).where(Prompt.name ** like)]
        if prompt_matches:
            condition = condition | (Gh.prompt_id << prompt_matches)
        q = q.where(condition)

    # 先按 ID 粗排，Python 层再做精细排序
    q = q.order_by(Gh.id.desc()).limit(limit)
    rows = list(q)

    # 过滤已不存在的文件
    deleted_ids = []
    alive = []
    for r in rows:
        if not _image_exists(r.filename, r.subfolder or "", r.img_type or "output"):
            deleted_ids.append(r.id)
            continue
        alive.append(r)

    if deleted_ids:
        Gh.delete().where(Gh.id.in_(deleted_ids)).execute()

    # Python 层二次排序
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
    # "newest" 已是默认（id desc）

    cache = _build_prompt_cache(alive)
    result = [_enrich_item(r, cache) for r in alive]
    return {"items": result}


# ---------------------------------------------------------------------------
# 同步
# ---------------------------------------------------------------------------

@router.api_route("/history_sync", methods=["GET", "POST"])
def sync_history(limit: int = Query(200)):
    added = _sync_comfyui_history()
    items = list_history(limit=limit, favorite=None, sort="newest", search="")["items"]
    return {"added": added, "items": items}


# ---------------------------------------------------------------------------
# 单条删除
# ---------------------------------------------------------------------------

@router.delete("/history/{item_id}")
def delete_history_item(item_id: int):
    r = Gh.get_or_none(Gh.id == item_id)
    if r is None:
        raise HTTPException(404, "历史记录不存在")
    r.delete_instance()
    return {"success": True}


# ---------------------------------------------------------------------------
# 批量删除
# ---------------------------------------------------------------------------

@router.post("/history/batch_delete")
def batch_delete_history(body: BatchDeleteRequest):
    ids = body.ids
    if not ids:
        return {"success": True, "deleted": 0}
    cnt = Gh.delete().where(Gh.id.in_(ids)).execute()
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
    Gh.delete().execute()
    return {"success": True}
