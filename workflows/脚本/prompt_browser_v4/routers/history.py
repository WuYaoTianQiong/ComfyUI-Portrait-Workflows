"""历史记录"""
import traceback
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Query

from config import settings
from models import GenHistory, GenHistory as Gh, Prompt
from services.helpers import build_view_url, get_image_metadata

router = APIRouter(tags=["历史"])

COMFYUI_API = settings.comfyui_api


def _image_exists(filename: str, subfolder: str, img_type: str) -> bool:
    """检查图片文件是否实际存在"""
    meta = get_image_metadata(filename, subfolder or "", img_type or "output")
    return bool(meta)  # get_image_metadata 文件不存在时返回 {}


def _enrich_item(r, prompt_cache=None) -> dict:
    """将 DB 行转为前端字典，含图片元数据和提示词名称"""
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
        "created_at": str(r.created_at) if r.created_at else "",
        "source": r.source,
        **meta,  # width, height, file_size
    }
    if r.prompt_id and prompt_cache:
        item["prompt_name"] = prompt_cache.get(r.prompt_id, "")
    return item


def _sync_comfyui_history() -> int:
    """从 ComfyUI /history 同步生成结果到本地历史表"""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{COMFYUI_API}/history")
            resp.raise_for_status()
            hist = resp.json()
    except httpx.ConnectError:
        return 0  # ComfyUI 未启动，静默跳过
    except Exception:
        traceback.print_exc()
        return 0

    if not hist:
        return 0

    added = 0
    for pid, data in hist.items():
        outputs = data.get("outputs", {})
        for node_out in outputs.values():
            for img in node_out.get("images", []):
                try:
                    Gh.insert(
                        job_id=None,
                        prompt_id=None,
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
                        source="comfyui_sync",
                    ).on_conflict_ignore().execute()
                    added += 1
                except Exception:
                    pass  # 单条插入失败不阻塞整体同步
    return added


def _build_prompt_cache(rows) -> dict:
    """从查询结果中收集 prompt_id，批量查询名称并返回 id→name 映射"""
    prompt_ids = [r.prompt_id for r in rows if r.prompt_id]
    if not prompt_ids:
        return {}
    return {r.id: r.name for r in Prompt.select(Prompt.id, Prompt.name).where(Prompt.id << prompt_ids)}


@router.get("/history")
def list_history(limit: int = Query(50)):
    rows = (
        GenHistory
        .select()
        .order_by(GenHistory.id.desc())
        .limit(limit)
    )
    cache = _build_prompt_cache(rows)
    items = []
    deleted_ids = []
    for r in rows:
        if not _image_exists(r.filename, r.subfolder or "", r.img_type or "output"):
            deleted_ids.append(r.id)
            continue
        items.append(_enrich_item(r, cache))
    # 批量删除已不存在的图片记录
    if deleted_ids:
        GenHistory.delete().where(GenHistory.id.in_(deleted_ids)).execute()
    return {"items": items}


@router.api_route("/history_sync", methods=["GET", "POST"])
def sync_history(limit: int = Query(50)):
    added = _sync_comfyui_history()
    rows = (
        GenHistory
        .select()
        .order_by(GenHistory.id.desc())
        .limit(limit)
    )
    cache = _build_prompt_cache(rows)
    return {"added": added, "items": [_enrich_item(r, cache) for r in rows]}


@router.delete("/history/{item_id}")
def delete_history_item(item_id: int):
    r = GenHistory.get_or_none(GenHistory.id == item_id)
    if r is None:
        raise HTTPException(404, "历史记录不存在")
    r.delete_instance()
    return {"success": True}


@router.delete("/history")
def clear_history():
    GenHistory.delete().execute()
    return {"success": True}
