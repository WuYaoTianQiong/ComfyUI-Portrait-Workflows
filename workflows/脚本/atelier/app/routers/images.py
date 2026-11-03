"""图片（原 `history` 路由）—— 画廊列表 / 分面 / 同步 / 批量操作 / 标签分类关联。"""
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from app.schemas import (
    FacetsResponse,
    HistoryIdsResponse,
    HistoryListResponse,
    ImageDetailResponse,
    ImageRunInfo,
)
from fastapi.responses import FileResponse
from peewee import fn
from pydantic import BaseModel

from app.config import settings
from app.models import Image, GenJob, Prompt, EntityTag, ImageCategory, Category, Tag, inherit_prompt_taxonomy, backfill_image_taxonomy
from app.services.comfyui_client import get_history_for_prompt
from app.services.image_meta import (
    compute_orientation,
    extract_model_from_comfy_prompt,
    extract_run_params,
    extract_run_times,
    get_image_metadata,
    get_image_metadata_fast,
    read_embedded_run_params,
)
from app.services.job_state import to_utc_iso
from app.services.paths import _resolve_if_reparse, build_view_url, resolve_image_path
from app.services.output_location import (
    OutputLocationError,
    apply_output_subfolder,
    expand_subfolder,
)
from app.services.thumbnail import _get_image_path, clear_thumbnails_for

router = APIRouter(tags=["图片"])

COMFYUI_API = settings.comfyui_api

# 历史同步 / 磁盘扫描互斥：HTTP 手动同步与 writer 定时同步可能同时触发。
# `_job_index` 是模块级缓存，两边同时写会读到半成品，同时入库也可能重复。
_sync_lock = threading.Lock()
# 目录 mtime 缓存：未变化的子目录不再逐层 scandir；每 10 分钟强制全量一次。
_dir_mtimes: dict[str, float] = {}
_last_full_scan = -1e9
_FULL_SCAN_INTERVAL = 600.0


# ---------------------------------------------------------------------------
# Pydantic
# ---------------------------------------------------------------------------

class BatchDeleteRequest(BaseModel):
    ids: list[int]
    # 默认只软删记录，物理删原图必须由前端显式勾选并传 true
    delete_files: bool = False


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _image_exists(filename: str, subfolder: str, img_type: str) -> bool:
    meta = get_image_metadata(filename, subfolder or "", img_type or "output")
    return bool(meta)


def _captured_at_expr():
    """真实出图时间；老数据没有 captured_at 时回退到入库时间。"""
    return fn.COALESCE(Image.captured_at, Image.created_at)


def _enrich_item(r, prompt_cache=None, meta=None, categories=None, tags=None) -> dict:
    if meta is None:
        meta = get_image_metadata(r.filename, r.subfolder or "", r.img_type or "output")
    prompt_params = json.loads(r.prompt_params) if r.prompt_params else None
    prompt_id = r.prompt_id  # 可能为 None（竞态条件导致）

    # 只读补全：prompt_params / prompt_id 缺失时，从关联任务的 items 里**临时**取出来给前端显示。
    # B3 之前这里会顺手 Image.update(...) 并继承分类 —— 也就是"读一次画廊就写一次库"，
    # 和 GET /api/jobs 的副作用是同一类问题。真正的补写现在只发生在入库路径
    # （job_state._insert_history_for_item / 同步 / 磁盘扫描）。
    if (prompt_params is None or prompt_id is None) and r.job_id:
        try:
            job = GenJob.get_or_none(GenJob.id == r.job_id)
            if job and job.items:
                items = json.loads(job.items) if isinstance(job.items, str) else job.items
                for it in items:
                    if it.get("comfyui_prompt_id") == r.comfyui_prompt_id:
                        if prompt_params is None and it.get("prompt_params"):
                            raw = it["prompt_params"]
                            prompt_params = json.loads(raw) if isinstance(raw, str) else raw
                        if prompt_id is None and it.get("prompt_id"):
                            prompt_id = it["prompt_id"]
                        break
        except Exception:
            pass

    item = {
        "id": r.id,
        "job_id": r.job_id,
        "prompt_id": prompt_id,
        "comfyui_prompt_id": r.comfyui_prompt_id,
        "filename": r.filename,
        "subfolder": r.subfolder,
        "img_type": r.img_type,
        "view_url": r.view_url,
        "preview": r.preview,
        "is_favorite": bool(r.is_favorite),
        "prompt_params": prompt_params,
        "created_at": str(r.created_at) if r.created_at else "",
        "captured_at": str(r.captured_at) if r.captured_at else "",
        "source": r.source,
        "prompt_name": "",  # 默认空字符串
        # 文件缺失：以巡检写的派生列为准，同时兼容"刚被删、巡检还没跑到"的情况
        # （meta 为空 = 路径 stat 失败 = 取不到图）。只用于展示与筛选，不参与删除。
        "missing": bool(r.missing_since) or not meta,
        **meta,
    }
    # 优先从缓存获取提示词名称
    if prompt_id and prompt_cache:
        item["prompt_name"] = prompt_cache.get(prompt_id, "")
    # 如果缓存中没有，直接从数据库查询
    if prompt_id and not item["prompt_name"]:
        try:
            prompt = Prompt.get_or_none(Prompt.id == prompt_id)
            if prompt:
                item["prompt_name"] = prompt.name
        except Exception:
            pass
    if categories is None:
        categories = list(ImageCategory.select().where(ImageCategory.image == r.id))
    if tags is None:
        tags = list(
            EntityTag.select().where(
                (EntityTag.entity_type == "image") & (EntityTag.entity_id == r.id)
            )
        )
    item["categories"] = [
        {"id": c.category.id, "name": c.category.name, "color": c.category.color}
        for c in categories
    ]
    item["tags"] = [
        {"id": t.tag.id, "name": t.tag.name, "color": t.tag.color}
        for t in tags
    ]
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

    # 用于判断"文件是否还在磁盘上"（ComfyUI 的 /history 会长期保留已删除图片的条目）
    from app.services.thumbnail import _get_image_path

    added = 0
    skipped = 0
    for pid, data in hist.items():
        outputs = data.get("outputs", {})
        # 尝试从 ComfyUI history 的 extra_data 提取 prompt_id
        extra = data.get("extra_data") or {}
        prompt_id = extra.get("prompt_id")

        for node_out in outputs.values():
            for img in node_out.get("images", []):
                filename = img.get("filename", "")
                # 不再跳过 atelier_ 前缀的图片：当服务重启/刷新页面导致
                # job poller 丢失追踪状态时，这些图片将永远无法入库。sync 作为兜底
                # 手段应当正常处理它们（upsert 确保不会覆盖 job poller 已写入的
                # prompt_id/job_id 等字段）。
                try:
                    subfolder = img.get("subfolder", "")
                    img_type = img.get("type", "output")
                    # ComfyUI 的 /history 会长期保留「文件已被手动删除」的条目。照单建记录
                    # 会让画廊堆满坏图：缩略图一律 404、控制台刷屏、点进去也看不到东西。
                    # 所以先确认文件真的在磁盘上，不在就跳过。
                    # （旧代码这里因为 upsert 报错被 except 吞掉，恰好掩盖了这个问题；
                    #   修好写入之后才暴露出来。）
                    img_path = _get_image_path(filename, subfolder, img_type)
                    if img_path is None:
                        skipped += 1
                        continue
                    try:
                        from datetime import datetime

                        captured = datetime.fromtimestamp(img_path.stat().st_mtime)
                    except OSError:
                        captured = None
                    pp = _build_prompt_params_from_comfy(data, filename, subfolder, img_type)
                    upsert_image(
                        {
                            "job_id": None,
                            "prompt_id": prompt_id,
                            "comfyui_prompt_id": pid,
                            "filename": filename,
                            "subfolder": subfolder,
                            "img_type": img_type,
                            "view_url": build_view_url(filename, subfolder, img_type),
                            "preview": "",
                            "prompt_params": pp,
                            "is_favorite": False,
                            "captured_at": captured,
                            "source": "comfyui_sync",
                        },
                        {
                            Image.comfyui_prompt_id: pid,
                            Image.prompt_id: prompt_id,
                            Image.view_url: build_view_url(filename, subfolder, img_type),
                            Image.prompt_params: pp,
                            # 刻意不再把 created_at 刷成 CURRENT_TIMESTAMP：同步每 30 秒跑一次，
                            # 那会让所有已存在的图每半分钟被"刷新"成最新，画廊"最新"排序彻底失效。
                        },
                        only_when_job_null=True,
                    )
                    added += 1
                    try:
                        nr = Image.get_or_none(
                            (Image.filename == filename)
                            & (Image.subfolder == subfolder)
                            & (Image.img_type == img_type)
                            & (Image.is_deleted == False)
                        )
                        if nr:
                            inherit_prompt_taxonomy(nr.id)
                    except Exception:
                        pass
                except Exception:
                    pass

    if skipped:
        print(f"[sync] 跳过 {skipped} 条「文件已不存在」的 ComfyUI 历史记录（避免画廊出现坏图）")
    return added


# 从 GenJob.items 按文件名查找提示词关联的缓存
_job_index = {}
# 缓存版本签名：(done 任务数, 最大 updated_at)。旧实现用布尔标记，建好一次就永不过期，
# 服务起来之后新出的图全都匹配不到来源提示词（索引里压根没有它们的文件名）。
_job_index_version = None


def _job_index_signature():
    """gen_jobs 的变化签名。查询很便宜（走 status 索引 + 聚合），每轮同步算一次。"""
    try:
        row = (
            GenJob.select(
                fn.COUNT(GenJob.id).alias("c"),
                fn.MAX(GenJob.updated_at).alias("m"),
            )
            .where(GenJob.status == "done")
            .first()
        )
        return (row.c, str(row.m))
    except Exception:
        return None


def _build_job_index():
    """构建 filename → (job_id, prompt_id, prompt_text) 索引。

    仅当 _sync_disk_orphans 需要查找时才生成（避免每 30 秒全量扫描 GenJob），
    并按 gen_jobs 的变化签名自动失效重建。
    """
    global _job_index, _job_index_version
    signature = _job_index_signature()
    if _job_index_version is not None and signature == _job_index_version:
        return

    prompt_map = {}
    for p in Prompt.select():
        prompt_map[p.id] = p

    idx = {}
    for j in GenJob.select().where(GenJob.status == 'done'):
        items = json.loads(j.items) if j.items else []
        for it in items:
            pid = it.get('prompt_id')
            prompt_text = ""
            if pid:
                p = prompt_map.get(int(pid)) if pid else None
                if p:
                    prompt_text = p.prompt or ""
            # 收集 items 中每张图片的文件名
            for img in it.get('images', []):
                fn = img.get('filename', '')
                if fn and fn not in idx:
                    idx[fn] = (j.id, pid, prompt_text)
    _job_index = idx
    _job_index_version = signature


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _iter_output_images(root: Path, max_depth: int = 4, force: bool = False):
    """递归遍历 output 下的图片，产出 (path, 相对 subfolder)。

    限制深度并跳过隐藏目录，避免误扫备份树或深目录；subfolder 始终用 `/`。
    未变化的子目录默认跳过（目录 mtime 缓存），force=True 时全量重扫。
    """
    stack: list[tuple[Path, str, int]] = [(root, "", 0)]
    while stack:
        cur, rel, depth = stack.pop()
        try:
            with os.scandir(cur) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if depth < max_depth and not entry.name.startswith("."):
                        try:
                            mtime = entry.stat(follow_symlinks=False).st_mtime
                        except OSError:
                            mtime = 0.0
                        if not force and _dir_mtimes.get(entry.path) == mtime:
                            continue
                        _dir_mtimes[entry.path] = mtime
                        child_rel = f"{rel}/{entry.name}".strip("/")
                        stack.append((Path(entry.path), child_rel, depth + 1))
                elif entry.is_file(follow_symlinks=False):
                    if Path(entry.name).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                        yield Path(entry.path), rel
            except OSError:
                continue


def _sync_disk_orphans(force: bool = False) -> int:
    """兜底：递归扫描 output 目录，将不在 DB 中的图片插入 gen_history。

    当 ComfyUI 的 /history API 中 outputs 已被清除（已完成的历史），或 atelier_
    前缀文件因服务重启导致 job poller 丢失追踪时，sync 无法通过 API 发现这些图。
    此函数作为最后兜底，直接扫描磁盘。

    支持 output 下的相对子目录（出图归档后仍然可用）；subfolder 与入库键一致。
    """
    try:
        output_dir = _resolve_if_reparse(settings.output_dir)
        if not output_dir.exists():
            return 0
    except Exception:
        return 0

    # 收集 DB 中已有的所有 (filename, subfolder, img_type) 组合
    existing = set()
    for r in Image.select(Image.filename, Image.subfolder, Image.img_type).where(Image.is_deleted == False).tuples():
        existing.add((r[0], r[1] or "", r[2] or "output"))

    _build_job_index()
    added = 0
    try:
        candidates = list(_iter_output_images(output_dir, force=force))
        candidates.sort(key=lambda item: _safe_mtime(item[0]))
        for fpath, subfolder in candidates:
            fname = fpath.name
            if (fname, subfolder, "output") in existing:
                continue
            try:
                sz = fpath.stat().st_size
                # 尝试从 GenJob 匹配同名文件，恢复提示词关联
                job_id = None
                prompt_id = None
                prompt_text = ""
                match = _job_index.get(fname)
                if match:
                    job_id, prompt_id, prompt_text = match

                pp_fields = {"width": 0, "height": 0, "file_size": sz, "source": "disk_scan"}
                if prompt_text:
                    pp_fields["prompt"] = prompt_text
                pp = json.dumps(pp_fields)
                try:
                    from datetime import datetime

                    captured = datetime.fromtimestamp(fpath.stat().st_mtime)
                except OSError:
                    captured = None

                Image.insert(
                    job_id=job_id,
                    prompt_id=prompt_id,
                    comfyui_prompt_id="",
                    filename=fname,
                    subfolder=subfolder,
                    img_type="output",
                    view_url=build_view_url(fname, subfolder, "output"),
                    preview="",
                    prompt_params=pp,
                    is_favorite=False,
                    captured_at=captured,
                    source="disk_scan",
                ).execute()
                existing.add((fname, subfolder, "output"))
                added += 1
            except Exception:
                pass
    except Exception:
        pass
    if added:
        print(f"[sync] disk scan: added {added} orphan images")
    return added


def sync_all(force: bool = False) -> int:
    """同步 ComfyUI 历史 + 磁盘兜底；同一时刻只允许一个执行者。

    HTTP 手动同步与 writer 定时同步共用此入口；拿不到锁说明已有扫描在跑，
    本次直接返回 0，避免重复入库与 `_job_index` 半成品。
    """
    global _last_full_scan
    now = time.monotonic()
    force = force or (now - _last_full_scan >= _FULL_SCAN_INTERVAL)
    if not _sync_lock.acquire(blocking=False):
        return 0
    try:
        added = _sync_comfyui_history()
        added += _sync_disk_orphans(force=force)
        if force:
            _last_full_scan = now
        return added
    finally:
        _sync_lock.release()


def _build_prompt_params_from_comfy(data: dict, filename: str = "", subfolder: str = "", img_type: str = "output") -> str | None:
    """从 ComfyUI history 条目构造 prompt_params JSON（含 model，可选宽高/orientation）。

    用于 _sync_comfyui_history 在同步新图时即写入模型与方向，不依赖文件是否仍在磁盘；
    若传入图片定位参数，则进一步从实际像素尺寸补写 width/height/orientation。
    """
    pp: dict = {}
    try:
        prompt_dict = data.get("prompt")
        if prompt_dict:
            model = extract_model_from_comfy_prompt(prompt_dict)
            if model:
                pp["model"] = model
    except Exception:
        pass
    # 从实际出图文件补宽高 / orientation（文件缺失时退化为仅 model）
    if filename:
        try:
            meta = get_image_metadata(filename, subfolder, img_type)
            w, h = meta.get("width"), meta.get("height")
            if w and h:
                pp["width"] = w
                pp["height"] = h
                o = compute_orientation(w, h)
                if o:
                    pp["orientation"] = o
        except Exception:
            pass
    if not pp:
        return None
    return json.dumps(pp, ensure_ascii=False)


def _build_prompt_cache(rows) -> dict:
    prompt_ids = [r.prompt_id for r in rows if r.prompt_id]
    if not prompt_ids:
        return {}
    return {r.id: r.name for r in Prompt.select(Prompt.id, Prompt.name).where(Prompt.id << prompt_ids)}


def _delete_source_file(filename: str, subfolder: str, img_type: str) -> bool:
    """删除这条记录对应的原图文件；文件不在或删除失败返回 False。

    路径走 `_get_image_path`：它已按 img_type 定位到 output/input/temp 根目录、
    逐段解析 Windows junction，并且只在文件真实存在时返回路径 —— 因此这里不会
    因为相对路径串味而删到 ComfyUI 目录之外的东西。
    """
    path = _get_image_path(filename or "", subfolder or "", img_type or "output")
    if path is None:
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def _cleanup_thumbnails(filename: str, subfolder: str, img_type: str):
    """清理缩略图：按 (filename, subfolder, img_type) 精确清理，避免误删其他记录的缩略图"""
    clear_thumbnails_for(filename, subfolder, img_type)


# ---------------------------------------------------------------------------
# 查询（支持筛选 / 排序 / 搜索）
# ---------------------------------------------------------------------------

@router.get("/images", response_model=HistoryListResponse)
def list_history(
    page: int = Query(1),
    page_size: int = Query(50),
    favorite: bool = Query(None),
    sort: str = Query("newest"),
    search: str = Query(""),
    category_id: int = Query(None),
    tag_ids: str = Query(""),
    source: str = Query(""),
    date: str = Query(""),
    model: str = Query(""),
    orientation: str = Query(""),
    missing: bool = Query(None),
    tag_match: str = Query("all", description="多标签语义：all=交集, any=并集"),
    ids: str = Query("", description="逗号分隔的历史 id，只取这些记录"),
):
    # 筛选构造统一走 _filtered_history_query + _apply_facet_filters：
    # 这两个函数是 /images、/images/ids、/images/facets、/images/cleanup_missing
    # 的唯一来源，避免"列表筛了、全选却选到范围外"这类错位。
    q = _filtered_history_query(favorite, search, category_id, tag_ids, missing, tag_match)
    q = _apply_facet_filters(q, source, date, model, orientation)

    # 按 id 精确取图：图像编辑页要用它把已选目标图的文件名/缩略图取回来配遮罩
    # （list_history 也会被 sync_history 内部直接调用，此时 ids 可能是默认 Query 对象）
    if isinstance(ids, str) and ids:
        wanted = [int(x) for x in ids.split(",") if x.strip().isdigit()]
        if wanted:
            q = q.where(Image.id.in_(wanted))

    total = q.count()
    offset = (page - 1) * page_size

    def _page_meta(row) -> dict:
        # 性能优化：优先从 prompt_params JSON 取宽高（同步/入库时已写入），
        # file_size 用 os.stat 秒读，仅缺失时回退 PIL 打开
        return (
            get_image_metadata_fast(
                row.filename, row.subfolder or "", row.img_type or "output",
                prompt_params=row.prompt_params,
            )
            or {}
        )

    # 排序必须发生在分页之前：旧实现先 offset/limit 再在内存里排，
    # size/res/oldest 只能排当前页，跨页顺序是错的。
    if sort in ("size_asc", "size_desc", "res_asc", "res_desc"):
        all_rows = list(q.order_by(_captured_at_expr().desc(), Image.id.desc()))
        all_meta = {r.id: _page_meta(r) for r in all_rows}
        if sort.startswith("size_"):
            key = lambda r: (all_meta[r.id].get("file_size", 0) or 0, r.id)
        else:
            key = lambda r: (all_meta[r.id].get("width", 0) or 0, r.id)
        all_rows.sort(key=key, reverse=sort.endswith("_desc"))
        rows = all_rows[offset:offset + page_size]
        meta_cache = {r.id: all_meta[r.id] for r in rows}
        missing_meta = sum(1 for meta in all_meta.values() if not meta)
    else:
        # newest / oldest 可以直接下推 SQL；按“真实出图时间”排序：
        # captured_at 优先，老数据回退 created_at。
        if sort == "oldest":
            order = (_captured_at_expr().asc(), Image.id.asc())
        else:
            order = (_captured_at_expr().desc(), Image.id.desc())
        rows = list(q.order_by(*order).offset(offset).limit(page_size))
        meta_cache = {r.id: _page_meta(r) for r in rows}
        missing_meta = sum(1 for meta in meta_cache.values() if not meta)

    ids = [r.id for r in rows]

    # 批量预取 tags / categories，避免逐图 N+1 子查询
    tags_map = {}
    for t in EntityTag.select().where(
        (EntityTag.entity_type == "image") & (EntityTag.entity_id.in_(ids))
    ):
        tags_map.setdefault(t.entity_id, []).append(t)
    cats_map = {}
    for c in ImageCategory.select().where(ImageCategory.image.in_(ids)):
        cats_map.setdefault(c.image_id, []).append(c)

    if missing_meta:
        print(f"[history] 警告: {missing_meta} 张图的元数据读取失败（文件可能暂不可读），"
              f"已保留记录未删除")

    alive = rows
    cache = _build_prompt_cache(alive)
    result = [
        _enrich_item(r, cache, meta_cache.get(r.id, {}), cats_map.get(r.id), tags_map.get(r.id))
        for r in alive
    ]
    return {"items": result, "total": total, "page": page, "page_size": page_size}


def _filtered_history_query(
    favorite: bool | None = None,
    search: str = "",
    category_id: int | None = None,
    tag_ids: str = "",
    missing: bool | None = None,
    tag_match: str = "all",
):
    """历史画廊的统一筛选构造器（favorite/search/分类/标签/缺失）。

    `/images`、`/images/ids`、`/images/facets` 必须共用这一份，
    否则会出现"列表按分类筛了、全选却选到类外"的错位。

    `tag_match` 决定多标签的语义：`all` = 交集（同时满足），`any` = 并集（任一满足）。
    """
    q = Image.select().where(Image.is_deleted == False)
    if favorite is not None:
        q = q.where(Image.is_favorite == favorite)
    if missing is not None:
        q = q.where(Image.missing_since.is_null(not missing))
    if search:
        like = f"%{search}%"
        condition = (
            (Image.filename ** like)
            | (Image.subfolder ** like)
            | (Image.comfyui_prompt_id ** like)
        )
        prompt_matches = [r.id for r in Prompt.select(Prompt.id).where(Prompt.name ** like)]
        if prompt_matches:
            condition = condition | (Image.prompt_id << prompt_matches)
        q = q.where(condition)
    if category_id is not None:
        q = q.join(ImageCategory).where(ImageCategory.category == category_id)
    if tag_ids:
        tid_list = [int(t.strip()) for t in tag_ids.split(",") if t.strip()]
        if tid_list:
            # 单个标签的命中范围 = 直接打在图片上 ∪ 经来源提示词继承，统一查 entity_tags
            def _hit(tid):
                direct = Image.id << EntityTag.select(EntityTag.entity_id).where(
                    (EntityTag.entity_type == "image") & (EntityTag.tag == tid)
                )
                via_prompt = Image.prompt_id << EntityTag.select(EntityTag.entity_id).where(
                    (EntityTag.entity_type == "prompt") & (EntityTag.tag == tid)
                )
                return direct | via_prompt

            if tag_match == "any":
                # 并集：命中任意一个标签即可（一次 IN 查询，不需要逐个 AND）
                direct = Image.id << EntityTag.select(EntityTag.entity_id).where(
                    (EntityTag.entity_type == "image") & (EntityTag.tag.in_(tid_list))
                )
                via_prompt = Image.prompt_id << EntityTag.select(EntityTag.entity_id).where(
                    (EntityTag.entity_type == "prompt") & (EntityTag.tag.in_(tid_list))
                )
                q = q.where(direct | via_prompt)
            else:
                # 交集：图片必须同时拥有所有选中标签
                for tid in tid_list:
                    q = q.where(_hit(tid))
    return q


def _apply_facet_filters(q, source: str = "", date: str = "", model: str = "", orientation: str = ""):
    """source / date / model / orientation 四个分面筛选。

    `/images`、`/images/ids`、`/images/cleanup_missing` 共用这一份。
    这三处原先各自内联了一遍同样的 if 分支，加一个筛选项就要改三处，
    并且已经出现过"列表筛了、全选却选到范围外"的错位。
    """
    if source:
        q = q.where(Image.source == source)
    if date:
        q = q.where(fn.strftime("%Y-%m", _captured_at_expr()) == date)
    if model:
        mq = fn.json_extract(Image.prompt_params, "$.model")
        if model == "未记录":
            q = q.where((mq.is_null(True)) | (mq == "") | (mq == "unknown") | (mq == "null"))
        else:
            q = q.where(mq == model)
    if orientation:
        oq = fn.json_extract(Image.prompt_params, "$.orientation")
        if orientation == "未记录":
            q = q.where((oq.is_null(True)) | (oq == "") | (oq == "unknown") | (oq == "null"))
        else:
            q = q.where(oq == orientation)
    return q


@router.get("/images/facets", response_model=FacetsResponse)
def history_facets(
    favorite: bool = Query(None),
    search: str = Query(""),
    category_id: int = Query(None),
    tag_ids: str = Query(""),
    missing: bool = Query(None),
    tag_match: str = Query("all"),
):
    """分面计数：基于 favorite/search/category/tag/missing 当前筛选（不含分面维度自身），
    返回 source / date(年-月) / model 各取值的数量。"""
    sub = _filtered_history_query(
        favorite, search, category_id, tag_ids, missing, tag_match
    ).select(Image.id).distinct()
    q0 = Image.select().where(Image.id.in_(sub))
    src_rows = q0.select(Image.source, fn.COUNT(Image.id).alias("c")).group_by(Image.source)
    sources = {r.source: r.c for r in src_rows}
    d_rows = q0.select(
        fn.strftime("%Y-%m", _captured_at_expr()).alias("d"), fn.COUNT(Image.id).alias("c")
    ).group_by(fn.strftime("%Y-%m", _captured_at_expr()))
    dates = {r.d: r.c for r in d_rows}
    m_expr = fn.json_extract(Image.prompt_params, "$.model")
    m_rows = q0.select(m_expr.alias("m"), fn.COUNT(Image.id).alias("c")).group_by(m_expr)
    models = {}
    for r in m_rows:
        m = r.m
        if m in (None, "", "null", "unknown"):
            m = "未记录"
        models[m] = models.get(m, 0) + r.c
    o_expr = fn.json_extract(Image.prompt_params, "$.orientation")
    o_rows = q0.select(o_expr.alias("o"), fn.COUNT(Image.id).alias("c")).group_by(o_expr)
    orients = {}
    for r in o_rows:
        o = r.o
        if o in (None, "", "null", "unknown"):
            o = "未记录"
        orients[o] = orients.get(o, 0) + r.c
    return {"source": sources, "date": dates, "model": models, "orientation": orients}



@router.get("/images/ids", response_model=HistoryIdsResponse)
def history_ids(
    favorite: str = Query(""),
    sort: str = Query("newest"),
    search: str = Query(""),
    category_id: int = Query(None),
    tag_ids: str = Query(""),
    source: str = Query(""),
    date: str = Query(""),
    model: str = Query(""),
    orientation: str = Query(""),
    missing: str = Query(""),
    tag_match: str = Query("all"),
):
    """返回当前筛选条件下所有（未删除）历史记录的 id 列表，供\"全选全部\"批量操作使用（不分页）。"""
    q = _filtered_history_query(
        favorite=True if favorite == "1" else (False if favorite == "0" else None),
        search=search,
        category_id=category_id,
        tag_ids=tag_ids,
        missing=True if missing == "1" else None,
        tag_match=tag_match,
    )
    q = _apply_facet_filters(q, source, date, model, orientation)
    ids = [r.id for r in q.select(Image.id).distinct()]
    return {"ids": ids, "total": len(ids)}


# ---------------------------------------------------------------------------
# 同步
# ---------------------------------------------------------------------------

# 两个方法写成两个装饰器（而不是 api_route(methods=[...])）：
# 多方法路由会让 FastAPI 生成重复的 operationId，OpenAPI 导出时会告警。
@router.get("/images/sync")
@router.post("/images/sync")
def sync_history(page_size: int = Query(500)):
    added = sync_all(force=True)
    # 注意：list_history 是 FastAPI 路由函数，直接 Python 调用时未显式传入的参数
    # 会拿到 Query(...) 默认对象（FieldInfo）而非真正的 None/""，
    # 会导致 `if category_id is not None` / `tag_ids.split` 等分支误触发并 500。
    # 因此这里必须显式传入全部参数的真实默认值。
    data = list_history(
        page=1, page_size=page_size, favorite=None, sort="newest", search="",
        category_id=None, tag_ids="", source="", date="", model="", orientation="",
        missing=None, tag_match="all",
    )
    return {"added": added, "items": data["items"], "total": data["total"]}


# ---------------------------------------------------------------------------
# 清理文件已被手动删除的记录
# ---------------------------------------------------------------------------

# 熔断阈值：命中比例超过一半、且样本量不小的时候，几乎只能说明路径解析出了问题
# （output 盘没挂、从 junction 启动导致 comfyui_root 指错），而不是真的"图都没了"。
_GUARD_RATIO = 0.5
_GUARD_MIN_TOTAL = 20


@router.post("/images/cleanup_missing")
def cleanup_missing_files(
    dry_run: bool = Query(True, description="true=只预览将清理哪些，不写库"),
    confirm: bool = Query(False, description="dry_run=false 时必须显式传 true"),
    favorite: bool = Query(None),
    search: str = Query(""),
    category_id: int = Query(None),
    tag_ids: str = Query(""),
    source: str = Query(""),
    date: str = Query(""),
    model: str = Query(""),
    orientation: str = Query(""),
    tag_match: str = Query("all"),
):
    """把「图片文件已不在磁盘」的记录标记为软删除（可逆，不动磁盘文件）。

    默认 dry_run：只返回将清理多少条 + 样本文件名，不写库。
    真正执行要同时传 `dry_run=false&confirm=true`。

    筛选参数与画廊一致，避免"看着筛过的列表点清理，却清掉了范围外的记录"。
    """
    from app.services.thumbnail import _get_image_path

    q = _filtered_history_query(favorite, search, category_id, tag_ids, tag_match=tag_match)
    q = _apply_facet_filters(q, source, date, model, orientation)
    rows = list(q)
    missing = [
        r for r in rows
        if _get_image_path(r.filename or "", r.subfolder or "", r.img_type or "output") is None
    ]
    total = len(rows)
    will_clean = len(missing)
    guarded = total >= _GUARD_MIN_TOTAL and will_clean / total > _GUARD_RATIO
    samples = [
        {
            "id": r.id,
            "filename": r.filename or "",
            "subfolder": r.subfolder or "",
            "img_type": r.img_type or "output",
        }
        for r in missing[:10]
    ]

    if guarded:
        return {
            "success": False,
            "dry_run": dry_run,
            "total": total,
            "will_clean": will_clean,
            "samples": samples,
            "guarded": True,
            "message": (
                f"疑似路径解析异常：{will_clean}/{total} 条记录找不到文件，"
                f"已阻止执行。请先确认 ComfyUI output 目录是否可访问。"
            ),
        }

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "total": total,
            "will_clean": will_clean,
            "samples": samples,
            "guarded": False,
            "message": "",
        }

    if not confirm:
        return {
            "success": False,
            "dry_run": False,
            "total": total,
            "will_clean": will_clean,
            "samples": samples,
            "guarded": False,
            "message": "未执行：dry_run=false 时必须同时传 confirm=true",
        }

    if missing:
        ids = [r.id for r in missing]
        Image.update(is_deleted=True).where(Image.id.in_(ids)).execute()
        # 只清理这些记录自己的缩略图缓存，绝不整体清空（那会让幸存图片全部重算）
        for r in missing:
            _cleanup_thumbnails(r.filename or "", r.subfolder or "", r.img_type or "output")

    return {
        "success": True,
        "dry_run": False,
        "total": total,
        "cleaned": will_clean,
        "guarded": False,
        "message": "",
    }


# ---------------------------------------------------------------------------
# 单条删除
# ---------------------------------------------------------------------------

@router.delete("/images/{item_id}")
def delete_history_item(
    item_id: int,
    delete_files: bool = Query(False, description="true=同时删除磁盘上的原图文件（不可恢复）"),
):
    r = Image.get_or_none(Image.id == item_id)
    if r is None:
        raise HTTPException(404, "历史记录不存在")
    # 先删物理文件再落库标记：即便文件删成功而入库失败，记录也还能靠
    # /images/cleanup_missing 重新对齐，而不是留下"文件还在、记录已删"的孤儿图。
    files_deleted = 0
    if delete_files and _delete_source_file(
        r.filename or "", r.subfolder or "", r.img_type or "output"
    ):
        files_deleted = 1
    # 软删除：标记而非真删，防止 sync 重新导入
    Image.update(is_deleted=True).where(Image.id == item_id).execute()
    # 清理缩略图
    _cleanup_thumbnails(r.filename or "", r.subfolder or "", r.img_type or "output")
    return {"success": True, "files_deleted": files_deleted}


# ---------------------------------------------------------------------------
# 批量删除
# ---------------------------------------------------------------------------

@router.post("/images/batch_delete")
def batch_delete_history(body: BatchDeleteRequest):
    ids = body.ids
    if not ids:
        return {"success": True, "deleted": 0, "files_deleted": 0}
    # 先取出行快照，避免依赖 update 之后的查询结果
    rows = list(Image.select().where(Image.id.in_(ids)))
    cnt = Image.update(is_deleted=True).where(Image.id.in_(ids)).execute()
    files_deleted = 0
    for r in rows:
        # 批量清理缩略图
        _cleanup_thumbnails(r.filename or "", r.subfolder or "", r.img_type or "output")
        if body.delete_files and _delete_source_file(
            r.filename or "", r.subfolder or "", r.img_type or "output"
        ):
            files_deleted += 1
    return {"success": True, "deleted": cnt, "files_deleted": files_deleted}


# ---------------------------------------------------------------------------
# 收藏切换
# ---------------------------------------------------------------------------

@router.post("/images/{item_id}/favorite")
def toggle_favorite(item_id: int):
    r = Image.get_or_none(Image.id == item_id)
    if r is None:
        raise HTTPException(404, "历史记录不存在")
    new_val = not bool(r.is_favorite)
    Image.update(is_favorite=new_val).where(Image.id == item_id).execute()
    return {"success": True, "is_favorite": new_val}


# ---------------------------------------------------------------------------
# 下载图片
# ---------------------------------------------------------------------------

@router.get("/images/{item_id}/download")
def download_history_item(item_id: int):
    r = Image.get_or_none(Image.id == item_id)
    if r is None:
        raise HTTPException(404, "历史记录不存在")

    img_path = resolve_image_path(
        r.filename or "", r.subfolder or "", r.img_type or "output"
    )
    if img_path is None:
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
# 单张图的完整出图参数（灯箱「查看提示词信息」用）
# ---------------------------------------------------------------------------

def _workflow_display_name(path: str) -> str:
    raw = (path or "").strip()
    if not raw:
        return ""
    if raw.startswith("custom://"):
        return raw[len("custom://"):] or "自定义工作流"
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    return name[:-5] if name.lower().endswith(".json") else name


def _job_extra(job) -> dict:
    raw = getattr(job, "extra", None) if job is not None else None
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return raw if isinstance(raw, dict) else {}


def _fill_missing(base: dict, values: dict) -> None:
    for key, value in (values or {}).items():
        if value in (None, ""):
            continue
        if base.get(key) in (None, ""):
            base[key] = value


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@router.get("/images/{item_id}/detail", response_model=ImageDetailResponse)
def image_detail(item_id: int):
    """补全单张图的出图上下文：任务（工作流/质量/比例）+ 实际采样参数 + 耗时。

    参数来源按可信度补空：任务记录的 prompt_params（提交/完成时写入）
    → ComfyUI history（实际执行值）→ PNG 内嵌 prompt（老图也能读出来）。
    """
    r = Image.get_or_none((Image.id == item_id) & (Image.is_deleted == False))
    if r is None:
        raise HTTPException(404, "历史记录不存在")

    item = _enrich_item(r)
    params = dict(item.get("prompt_params") or {})
    job = GenJob.get_or_none(GenJob.id == r.job_id) if r.job_id else None
    extra = _job_extra(job)

    pid = r.comfyui_prompt_id or ""
    if pid:
        entry = (get_history_for_prompt(pid) or {}).get(pid)
        if isinstance(entry, dict):
            _fill_missing(params, extract_run_params(entry.get("prompt")))
            _fill_missing(params, extract_run_times(entry))
    if not params.get("steps") or not params.get("sampler"):
        _fill_missing(
            params,
            read_embedded_run_params(r.filename or "", r.subfolder or "", r.img_type or "output"),
        )

    run = ImageRunInfo(
        workflow_path=(job.workflow_path or "") if job else "",
        workflow_name=_workflow_display_name(job.workflow_path if job else ""),
        quality=(job.quality or "") if job else "",
        aspect_ratio=str(extra.get("aspect_ratio") or params.get("aspect_ratio") or ""),
        output_subfolder=str(extra.get("output_subfolder") or ""),
        submitted_at=to_utc_iso(job.created_at) if job else "",
        started_at=str(params.get("started_at") or ""),
        finished_at=str(params.get("finished_at") or ""),
        duration_seconds=_as_float(params.get("duration_seconds")),
        steps=_as_int(params.get("steps")),
        cfg_scale=_as_float(params.get("cfg_scale")),
        sampler=str(params.get("sampler") or ""),
        scheduler=str(params.get("scheduler") or ""),
        seed=_as_int(params.get("seed")),
        denoise=_as_float(params.get("denoise")),
        model=str(params.get("model") or ""),
    )
    return {
        **item,
        "job_type": (job.job_type or "") if job else "",
        "job_status": (job.status or "") if job else "",
        "job_title": (job.title or "") if job else "",
        "run": run,
    }


class RevealRequest(BaseModel):
    id: int | None = None
    filename: str = ""
    subfolder: str = ""
    img_type: str = "output"


def _reveal_path(img_path: Path) -> dict:
    if sys.platform != "win32":
        return {"success": False, "path": str(img_path), "message": "仅支持 Windows"}
    subprocess.Popen(["explorer", "/select,", str(img_path)])
    return {"success": True, "path": str(img_path)}


@router.post("/images/reveal")
def reveal_image_ref(req: RevealRequest):
    """按 id 或 (filename, subfolder, type) 在资源管理器中定位原图。

    任务/结果中心里的图可能还没入库（没有 id），所以提供按文件名定位的入口；
    路径仍走 `resolve_image_path`，越界与不存在的文件都会被拒绝。
    """
    if req.id is not None:
        r = Image.get_or_none(Image.id == req.id)
        if r is None:
            raise HTTPException(404, "历史记录不存在")
        filename, subfolder, img_type = r.filename or "", r.subfolder or "", r.img_type or "output"
    else:
        filename, subfolder, img_type = req.filename, req.subfolder, req.img_type or "output"
    img_path = resolve_image_path(filename, subfolder, img_type)
    if img_path is None:
        raise HTTPException(404, "图片文件不存在")
    return _reveal_path(img_path)


@router.post("/images/{item_id}/reveal")
def reveal_history_item(item_id: int):
    """在资源管理器中定位这条出图记录对应的原图。"""
    r = Image.get_or_none(Image.id == item_id)
    if r is None:
        raise HTTPException(404, "历史记录不存在")
    img_path = resolve_image_path(
        r.filename or "", r.subfolder or "", r.img_type or "output"
    )
    if img_path is None:
        raise HTTPException(404, "图片文件不存在")
    return _reveal_path(img_path)


# ---------------------------------------------------------------------------
# 清空
# ---------------------------------------------------------------------------

@router.delete("/images")
def clear_history(confirm: bool = Query(False)):
    live = Image.select().where(Image.is_deleted == False).count()
    if not confirm:
        return {
            "success": False,
            "total": live,
            "message": "未执行：这是全库软删除，必须显式传 confirm=true",
        }
    Image.update(is_deleted=True).execute()
    # 清理全部缩略图
    try:
        import shutil
        td = settings.thumbnail_dir
        if td.exists():
            shutil.rmtree(td)
            td.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return {"success": True, "total": live}


@router.post("/images/backfill_taxonomy")
def backfill_taxonomy():
    """为所有带 prompt_id 且尚未分类的图片批量补齐来源提示词的分类/标签。"""
    done = backfill_image_taxonomy()
    return {"success": True, "backfilled": done}


class ProcessImageRequest(BaseModel):
    workflow_path: str
    workflow_content: str | None = None
    orientation: str = "portrait"
    quality: str = "4K"
    aspect_ratio: str = ""
    output_subfolder: str = ""


class CleanupBoxModel(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int


class CleanupRequest(BaseModel):
    mode: str = "seals"  # seals / text / all / manual（带 boxes 时）
    padding: int = 6
    boxes: list[CleanupBoxModel] | None = None


@router.post("/images/{item_id}/process")
def process_history_image(item_id: int, data: ProcessImageRequest):
    """将历史图片作为输入，用指定工作流处理（如超分、重绘等）"""
    r = Image.get_or_none(Image.id == item_id)
    if r is None:
        raise HTTPException(404, "历史记录不存在")

    # 1. 定位源图片
    from pathlib import Path
    from app.config import settings
    from app.services.workflow_parser import load_workflow, inject_prompt, inject_input_image
    from app.services.comfyui_client import push_prompt
    from app.routers.jobs import build_job_extra, create_job, update_job_items

    src_path = resolve_image_path(
        r.filename or "", r.subfolder or "", r.img_type or "output"
    )
    if src_path is None:
        raise HTTPException(404, "图片文件不存在")

    # 2. 加载工作流
    workflow_path = data.workflow_path or ""
    if not workflow_path:
        raise HTTPException(400, "缺少工作流路径")
    try:
        expand_subfolder(
            data.output_subfolder, workflow_path=workflow_path, job_id=0,
            quality=data.quality, orientation=data.orientation,
        )
    except OutputLocationError as e:
        raise HTTPException(400, str(e))
    try:
        api_wf = load_workflow(workflow_path, data.workflow_content)
    except Exception as e:
        raise HTTPException(400, f"工作流加载失败: {e}")

    # 3. 注入图片到 LoadImage 节点
    input_dir = settings.input_dir
    try:
        img_name = inject_input_image(api_wf, str(src_path), str(input_dir))
    except Exception as e:
        raise HTTPException(500, f"图片注入失败: {e}")

    # 4. 注入基础参数
    prompt_data = {
        "prompt": "", "negative_prompt": "",
        "seed": 0, "seed_override": 0,
        "orientation": data.orientation, "quality": data.quality,
        "aspect_ratio": data.aspect_ratio,
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
        extra=build_job_extra(
            workflow_path, data.workflow_content, data.output_subfolder,
            source="history_process", aspect_ratio=data.aspect_ratio,
        ),
    )
    subfolder = expand_subfolder(
        data.output_subfolder, workflow_path=workflow_path, job_id=job_id,
        quality=data.quality, orientation=data.orientation,
    )
    apply_output_subfolder(api_wf, subfolder)

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


# ---------------------------------------------------------------------------
# 后期清理：红印章 / 文字检测与擦除
# ---------------------------------------------------------------------------

_CLEANUP_MODES = {"seals", "text", "all"}


def _cleanup_source(item_id: int) -> tuple[Image, Path]:
    row = Image.get_or_none(Image.id == item_id)
    if row is None:
        raise HTTPException(404, "历史记录不存在")
    src = resolve_image_path(row.filename or "", row.subfolder or "", row.img_type or "output")
    if src is None:
        raise HTTPException(404, "图片文件不存在")
    return row, Path(src)


@router.get("/images/cleanup/capabilities")
def cleanup_capabilities():
    """红印章擦除依赖 opencv；文字 OCR 依赖可选安装的 RapidOCR。"""
    from app.services.text_cleanup import capabilities

    return capabilities()


@router.post("/images/{item_id}/cleanup/detect")
def detect_cleanup_regions(item_id: int, data: CleanupRequest):
    """只检测不擦除：返回红印章/文本框，供后续选择性清理。"""
    mode = (data.mode or "seals").lower()
    if mode not in _CLEANUP_MODES:
        raise HTTPException(400, f"未知清理模式: {mode}")
    _row, src = _cleanup_source(item_id)
    from app.services.text_cleanup import detect_boxes

    try:
        boxes = detect_boxes(src, mode)
    except (RuntimeError, FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e))
    return {
        "success": True,
        "mode": mode,
        "count": len(boxes),
        "boxes": [b.as_dict() for b in boxes],
    }


@router.post("/images/{item_id}/cleanup")
def cleanup_history_image(item_id: int, data: CleanupRequest):
    """擦除红印章或文字，生成一张新图；原图不覆盖。"""
    row, src = _cleanup_source(item_id)
    from app.services.text_cleanup import (
        CleanupBox,
        cleanup_image,
        detect_boxes,
        red_pixels_in_boxes,
    )

    if data.boxes:
        mode = "manual"
        boxes = [
            CleanupBox(b.x1, b.y1, b.x2, b.y2, "manual")
            for b in data.boxes
            if b.x2 > b.x1 and b.y2 > b.y1
        ]
        if not boxes:
            raise HTTPException(400, "选区无效")
    else:
        mode = (data.mode or "seals").lower()
        if mode not in _CLEANUP_MODES:
            raise HTTPException(400, f"未知清理模式: {mode}")
        try:
            boxes = detect_boxes(src, mode)
        except (RuntimeError, FileNotFoundError, ValueError) as e:
            raise HTTPException(400, str(e))
        if not boxes:
            return {
                "success": False,
                "removed": 0,
                "message": "未检测到红印章或文字，未生成新图",
            }

    # 输出跟原图同子目录；原图不在 output 下时落到 output/cleanup。
    try:
        rel = src.resolve().relative_to(settings.output_dir.resolve())
        subdir = rel.parent
    except ValueError:
        subdir = Path("cleanup")
    subfolder = "" if str(subdir) == "." else subdir.as_posix()
    out_dir = settings.output_dir / (subdir if subfolder else "")
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{src.stem}_clean_{mode}_{int(time.time() * 1000)}.png"
    out_path = out_dir / filename

    try:
        removed, used = cleanup_image(
            src, out_path, mode, padding=max(0, min(50, int(data.padding))), boxes=boxes,
        )
        remaining_red = red_pixels_in_boxes(out_path, used)
    except (RuntimeError, OSError, FileNotFoundError) as e:
        raise HTTPException(500, str(e))

    view_url = build_view_url(filename, subfolder, "output")
    prompt_params = json.dumps({
        "source": "cleanup",
        "source_image_id": item_id,
        "source_filename": row.filename or "",
        "mode": mode,
        "removed": removed,
        "boxes": [b.as_dict() for b in used],
    }, ensure_ascii=False)
    image_id = Image.insert(
        job_id=None,
        prompt_id=None,
        comfyui_prompt_id="",
        filename=filename,
        subfolder=subfolder,
        img_type="output",
        view_url=view_url,
        preview="",
        prompt_params=prompt_params,
        is_favorite=False,
        captured_at=datetime.now(),
        source="cleanup",
    ).execute()
    return {
        "success": True,
        "image_id": image_id,
        "filename": filename,
        "subfolder": subfolder,
        "view_url": view_url,
        "mode": mode,
        "removed": removed,
        "remaining_red": remaining_red,
        "warning": (
            "选区内仍有红色残留，选区可能太小；可放大选区再清理一次"
            if mode == "manual" and remaining_red > 20 else ""
        ),
    }


# ======== Phase 5: 图片分类 / 标签管理 ========
@router.post("/images/{item_id}/categories/{cat_id}")
def add_image_category(item_id: int, cat_id: int):
    r = Image.get_or_none(Image.id == item_id)
    if r is None:
        raise HTTPException(404, "历史记录不存在")
    c = Category.get_or_none(Category.id == cat_id)
    if c is None:
        raise HTTPException(404, "分类不存在")
    _, created = ImageCategory.get_or_create(image=item_id, category=cat_id)
    return {"success": True, "created": created}


@router.delete("/images/{item_id}/categories/{cat_id}")
def remove_image_category(item_id: int, cat_id: int):
    pc = ImageCategory.get_or_none((ImageCategory.image == item_id) & (ImageCategory.category == cat_id))
    if pc is None:
        raise HTTPException(404, "关联关系不存在")
    pc.delete_instance()
    return {"success": True}


@router.post("/images/{item_id}/tags/{tag_id}")
def add_image_tag(item_id: int, tag_id: int):
    r = Image.get_or_none(Image.id == item_id)
    if r is None:
        raise HTTPException(404, "历史记录不存在")
    t = Tag.get_or_none(Tag.id == tag_id)
    if t is None:
        raise HTTPException(404, "标签不存在")
    _, created = EntityTag.get_or_create(
        entity_type="image", entity_id=item_id, tag=tag_id
    )
    if created:
        Tag.update(usage_count=Tag.usage_count + 1).where(Tag.id == tag_id).execute()
    return {"success": True, "created": created}


@router.delete("/images/{item_id}/tags/{tag_id}")
def remove_image_tag(item_id: int, tag_id: int):
    it = EntityTag.get_or_none(
        (EntityTag.entity_type == "image")
        & (EntityTag.entity_id == item_id)
        & (EntityTag.tag == tag_id)
    )
    if it is None:
        raise HTTPException(404, "关联关系不存在")
    it.delete_instance()
    Tag.update(usage_count=Tag.usage_count - 1).where(Tag.id == tag_id).execute()
    return {"success": True}


@router.post("/images/{item_id}/inherit")
def inherit_image_taxonomy(item_id: int):
    r = Image.get_or_none(Image.id == item_id)
    if r is None:
        raise HTTPException(404, "历史记录不存在")
    added = inherit_prompt_taxonomy(item_id, force=True)
    return {"success": True, "added": added}
