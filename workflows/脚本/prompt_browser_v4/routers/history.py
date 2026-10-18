"""历史记录"""
import json
import traceback
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from peewee import fn, SQL
from pydantic import BaseModel

from config import settings
from models import GenHistory as Gh, Prompt, PromptTag, ImageCategory, ImageTag, Category, Tag, inherit_prompt_taxonomy, backfill_image_taxonomy
from services.helpers import build_view_url, get_image_metadata, get_image_metadata_fast, _resolve_if_reparse, extract_model_from_comfy_prompt, compute_orientation
from services.thumbnail import _get_image_path
from shared import templates

router = APIRouter(tags=["历史"])

COMFYUI_API = settings.comfyui_api
OUTPUT_ROOT = _resolve_if_reparse(settings.comfyui_root / "output")


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


def _captured_at_expr():
    """真实出图时间；老数据没有 captured_at 时回退到入库时间。"""
    return fn.COALESCE(Gh.captured_at, Gh.created_at)


def _enrich_item(r, prompt_cache=None, meta=None, categories=None, tags=None) -> dict:
    if meta is None:
        meta = get_image_metadata(r.filename, r.subfolder or "", r.img_type or "output")
    prompt_params = json.loads(r.prompt_params) if r.prompt_params else None
    prompt_id = r.prompt_id  # 可能为 None（竞态条件导致）

    # 补写逻辑：如果 prompt_params / prompt_id 为空且有 job_id，尝试从 job items 里找回
    if (prompt_params is None or prompt_id is None) and r.job_id:
        try:
            from models import GenJob
            job = GenJob.get_or_none(GenJob.id == r.job_id)
            if job and job.items:
                items = json.loads(job.items) if isinstance(job.items, str) else job.items
                for it in items:
                    if it.get("comfyui_prompt_id") == r.comfyui_prompt_id:
                        # 补写 prompt_params
                        if prompt_params is None and it.get("prompt_params"):
                            Gh.update(prompt_params=it["prompt_params"]).where(Gh.id == r.id).execute()
                            prompt_params = json.loads(it["prompt_params"]) if isinstance(it["prompt_params"], str) else it["prompt_params"]
                        # 补写 prompt_id
                        if prompt_id is None and it.get("prompt_id"):
                            Gh.update(prompt_id=it["prompt_id"]).where(Gh.id == r.id).execute()
                            prompt_id = it["prompt_id"]
                            # 补回 prompt_id 后，继承来源提示词的分类/标签
                            try:
                                inherit_prompt_taxonomy(r.id, force=True)
                            except Exception:
                                pass
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
        "favorite": bool(r.favorite),
        "prompt_params": prompt_params,
        "created_at": str(r.created_at) if r.created_at else "",
        "captured_at": str(r.captured_at) if r.captured_at else "",
        "source": r.source,
        "prompt_name": "",  # 默认空字符串
        **meta,
    }
    # 优先从缓存获取提示词名称
    if prompt_id and prompt_cache:
        item["prompt_name"] = prompt_cache.get(prompt_id, "")
    # 如果缓存中没有，直接从数据库查询
    if prompt_id and not item["prompt_name"]:
        try:
            from models import Prompt
            prompt = Prompt.get_or_none(Prompt.id == prompt_id)
            if prompt:
                item["prompt_name"] = prompt.name
        except Exception:
            pass
    if categories is None:
        categories = list(ImageCategory.select().where(ImageCategory.image == r.id))
    if tags is None:
        tags = list(ImageTag.select().where(ImageTag.image == r.id))
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
    from services.thumbnail import _get_image_path

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
                # 不再跳过 prompt_browser_ 前缀的图片：当服务重启/刷新页面导致
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
                    Gh.insert(
                        job_id=None,
                        prompt_id=prompt_id,
                        comfyui_prompt_id=pid,
                        filename=filename,
                        subfolder=subfolder,
                        img_type=img_type,
                        view_url=build_view_url(filename, subfolder, img_type),
                        preview="",
                        prompt_params=pp,
                        favorite=False,
                        captured_at=captured,
                        source="comfyui_sync",
                    ).on_conflict(
                        # peewee 4.x 的正确写法是 on_conflict(conflict_target=..., update=...)；
                        # 原来的 on_conflict_do_update(..., set_=...) 是 3.x API，在本项目装的
                        # peewee 4.1 上必然抛 AttributeError，又被下面的 except Exception: pass 吞掉，
                        # 导致这条同步兜底路径其实从未写入过任何一条记录。
                        conflict_target=[Gh.filename, Gh.subfolder, Gh.img_type],
                        # 必须带 WHERE 才能匹配部分索引，且必须用 SQL 字面量（peewee 表达式会生成
                        # 带引号的 "is_deleted" = 0，SQLite 不认）
                        conflict_where=SQL("is_deleted=0"),
                        # 已被任务（job）写过参数的行不再被同步覆盖：job 写进去的是
                        # source=faceswap/composer 这类富参数（含组合来源、节点映射、种子），
                        # 同步只能从 ComfyUI history 反推出较弱的参数，覆盖即丢信息。
                        # job_id 为空的行（同步/磁盘扫描创建的）照旧会被更新，保持原有补全能力。
                        where=Gh.job_id.is_null(),
                        update={
                            Gh.comfyui_prompt_id: pid,
                            Gh.prompt_id: prompt_id,
                            Gh.view_url: build_view_url(filename, subfolder, img_type),
                            Gh.prompt_params: pp,
                            # 刻意不再把 created_at 刷成 CURRENT_TIMESTAMP：同步每 30 秒跑一次，
                            # 那会让所有已存在的图每半分钟被"刷新"成最新，画廊"最新"排序彻底失效。
                        },
                    ).execute()
                    added += 1
                    try:
                        nr = Gh.get_or_none(
                            (Gh.filename == filename)
                            & (Gh.subfolder == subfolder)
                            & (Gh.img_type == img_type)
                            & (Gh.is_deleted == False)
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
_job_index_built = False


def _build_job_index():
    """构建 filename → (job_id, prompt_id, prompt_text) 索引。
    仅当 _sync_disk_orphans 需要查找时才生成（避免每30秒全量扫描 GenJob）。"""
    global _job_index, _job_index_built
    if _job_index_built:
        return
    from models import GenJob, Prompt

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
    _job_index_built = True


def _sync_disk_orphans() -> int:
    """兜底：扫描磁盘 output 目录，将不在 DB 中的 .png 文件插入 gen_history。

    当 ComfyUI 的 /history API 中 outputs 已被清除（已完成的历史），或 prompt_browser_
    前缀文件因服务重启导致 job poller 丢失追踪时，sync 无法通过 API 发现这些图。
    此函数作为最后兜底，直接扫描磁盘。

    仅处理 output 目录下的直接文件（不递归 subfolder），因为 prompt_browser 出图
    都在 output 根目录（subfolder=""）。
    """
    try:
        output_dir = _resolve_if_reparse(settings.comfyui_root / "output")
        if not output_dir.exists():
            return 0
    except Exception:
        return 0

    # 收集 DB 中已有的所有 (filename, subfolder, img_type) 组合
    existing = set()
    for r in Gh.select(Gh.filename, Gh.subfolder, Gh.img_type).where(Gh.is_deleted == False).tuples():
        existing.add((r[0], r[1] or "", r[2] or "output"))

    added = 0
    try:
        for fpath in sorted(output_dir.iterdir(), key=lambda p: p.stat().st_mtime):
            if not fpath.is_file() or fpath.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                continue
            fname = fpath.name
            if (fname, "", "output") in existing:
                continue
            try:
                sz = fpath.stat().st_size
                # 尝试从 GenJob 匹配同名文件，恢复提示词关联
                job_id = None
                prompt_id = None
                prompt_text = ""
                if not _job_index:
                    _build_job_index()
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

                Gh.insert(
                    job_id=job_id,
                    prompt_id=prompt_id,
                    comfyui_prompt_id="",
                    filename=fname,
                    subfolder="",
                    img_type="output",
                    view_url=build_view_url(fname, "", "output"),
                    preview="",
                    prompt_params=pp,
                    favorite=False,
                    captured_at=captured,
                    source="disk_scan",
                ).execute()
                added += 1
            except Exception:
                pass
    except Exception:
        pass
    if added:
        print(f"[sync] disk scan: added {added} orphan images")
    return added


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


def _cleanup_thumbnails(filename: str, subfolder: str, img_type: str):
    """清理缩略图：按 (filename, subfolder, img_type) 精确清理，避免误删其他记录的缩略图"""
    try:
        thumb_dir = settings.thumbnail_dir
        safe_filename = filename.replace("/", "_").replace("\\", "_").replace(":", "_")
        safe_subfolder = (subfolder or "").replace("/", "_").replace("\\", "_").replace(":", "_")
        safe_type = (img_type or "output").replace("/", "_").replace("\\", "_").replace(":", "_")
        # 匹配模式：{filename}_{subfolder}_{img_type}_*
        prefix = f"{safe_filename}_{safe_subfolder}_{safe_type}_"
        for f in thumb_dir.glob(f"{prefix}*"):
            f.unlink()
    except Exception:
        pass


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
    category_id: int = Query(None),
    tag_ids: str = Query(""),
    source: str = Query(""),
    date: str = Query(""),
    model: str = Query(""),
    orientation: str = Query(""),
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

    if category_id is not None:
        q = q.join(ImageCategory).where(ImageCategory.category == category_id)
    if tag_ids:
        tid_list = [int(t.strip()) for t in tag_ids.split(",") if t.strip()]
        if tid_list:
            # 多标签取交集（图像必须同时拥有所有选中标签）
            for tid in tid_list:
                direct = Gh.id << ImageTag.select(ImageTag.image).where(ImageTag.tag == tid)
                via_prompt = Gh.prompt_id << PromptTag.select(PromptTag.prompt).where(PromptTag.tag == tid)
                q = q.where(direct | via_prompt)

    if source:
        q = q.where(Gh.source == source)
    if date:
        q = q.where(fn.strftime("%Y-%m", _captured_at_expr()) == date)
    if model:
        mq = fn.json_extract(Gh.prompt_params, "$.model")
        if model == "未记录":
            q = q.where((mq.is_null(True)) | (mq == "") | (mq == "unknown") | (mq == "null"))
        else:
            q = q.where(mq == model)

    if orientation:
        oq = fn.json_extract(Gh.prompt_params, "$.orientation")
        if orientation == "未记录":
            q = q.where((oq.is_null(True)) | (oq == "") | (oq == "unknown") | (oq == "null"))
        else:
            q = q.where(oq == orientation)

    total = q.count()

    offset = (page - 1) * page_size
    # 按"真实出图时间"排序：captured_at 优先，老数据回退 created_at。
    # 只按 created_at 排会变成按"导入批次"排（同步/扫描进来的图全部落在同一天）。
    q = q.order_by(_captured_at_expr().desc(), Gh.id.desc()).offset(offset).limit(page_size)
    rows = list(q)
    ids = [r.id for r in rows]

    # 批量预取 tags / categories，避免逐图 N+1 子查询
    tags_map = {}
    for t in ImageTag.select().where(ImageTag.image.in_(ids)):
        tags_map.setdefault(t.image_id, []).append(t)
    cats_map = {}
    for c in ImageCategory.select().where(ImageCategory.image.in_(ids)):
        cats_map.setdefault(c.image_id, []).append(c)

    alive = []
    meta_cache = {}
    missing_meta_ids = []
    for r in rows:
        # 性能优化：优先从 prompt_params JSON 取宽高（同步/入库时已写入），
        # file_size 用 os.stat 秒读，仅缺失时回退 PIL 打开
        meta = get_image_metadata_fast(
            r.filename, r.subfolder or "", r.img_type or "output",
            prompt_params=r.prompt_params,
        )
        if not meta:
            meta = {}
            missing_meta_ids.append(r.id)
        meta_cache[r.id] = meta
        alive.append(r)

    if missing_meta_ids:
        print(f"[history] 警告: {len(missing_meta_ids)} 张图的元数据读取失败（文件可能暂不可读），"
              f"已保留记录未删除")

    if sort == "oldest":
        alive.sort(key=lambda r: (r.captured_at or r.created_at, r.id))
    elif sort == "size_asc":
        alive.sort(key=lambda r: meta_cache[r.id].get("file_size", 0) or 0)
    elif sort == "size_desc":
        alive.sort(key=lambda r: meta_cache[r.id].get("file_size", 0) or 0, reverse=True)
    elif sort == "res_asc":
        alive.sort(key=lambda r: (meta_cache[r.id].get("width", 0) or 0))
    elif sort == "res_desc":
        alive.sort(key=lambda r: (meta_cache[r.id].get("width", 0) or 0), reverse=True)

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
):
    """历史画廊的统一筛选构造器（favorite/search/分类/标签）。

    `/history`、`/history/ids`、`/history/facets` 必须共用这一份，
    否则会出现"列表按分类筛了、全选却选到类外"的错位。
    """
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
    if category_id is not None:
        q = q.join(ImageCategory).where(ImageCategory.category == category_id)
    if tag_ids:
        tid_list = [int(t.strip()) for t in tag_ids.split(",") if t.strip()]
        if tid_list:
            # 多标签取交集（图像必须同时拥有所有选中标签）
            for tid in tid_list:
                direct = Gh.id << ImageTag.select(ImageTag.image).where(ImageTag.tag == tid)
                via_prompt = Gh.prompt_id << PromptTag.select(PromptTag.prompt).where(PromptTag.tag == tid)
                q = q.where(direct | via_prompt)
    return q


@router.get("/history/facets")
def history_facets(
    favorite: bool = Query(None),
    search: str = Query(""),
    category_id: int = Query(None),
    tag_ids: str = Query(""),
):
    """分面计数：基于 favorite/search/category/tag 当前筛选（不含分面维度自身），
    返回 source / date(年-月) / model 各取值的数量。"""
    sub = _filtered_history_query(favorite, search, category_id, tag_ids).select(Gh.id).distinct()
    q0 = Gh.select().where(Gh.id.in_(sub))
    src_rows = q0.select(Gh.source, fn.COUNT(Gh.id).alias("c")).group_by(Gh.source)
    sources = {r.source: r.c for r in src_rows}
    d_rows = q0.select(
        fn.strftime("%Y-%m", _captured_at_expr()).alias("d"), fn.COUNT(Gh.id).alias("c")
    ).group_by(fn.strftime("%Y-%m", _captured_at_expr()))
    dates = {r.d: r.c for r in d_rows}
    m_expr = fn.json_extract(Gh.prompt_params, "$.model")
    m_rows = q0.select(m_expr.alias("m"), fn.COUNT(Gh.id).alias("c")).group_by(m_expr)
    models = {}
    for r in m_rows:
        m = r.m
        if m in (None, "", "null", "unknown"):
            m = "未记录"
        models[m] = models.get(m, 0) + r.c
    o_expr = fn.json_extract(Gh.prompt_params, "$.orientation")
    o_rows = q0.select(o_expr.alias("o"), fn.COUNT(Gh.id).alias("c")).group_by(o_expr)
    orients = {}
    for r in o_rows:
        o = r.o
        if o in (None, "", "null", "unknown"):
            o = "未记录"
        orients[o] = orients.get(o, 0) + r.c
    return {"source": sources, "date": dates, "model": models, "orientation": orients}



@router.get("/history/ids", response_model=dict)
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
):
    """返回当前筛选条件下所有（未删除）历史记录的 id 列表，供\"全选全部\"批量操作使用（不分页）。"""
    q = _filtered_history_query(
        favorite=True if favorite == "1" else (False if favorite == "0" else None),
        search=search,
        category_id=category_id,
        tag_ids=tag_ids,
    )
    if source:
        q = q.where(Gh.source == source)
    if date:
        q = q.where(fn.strftime("%Y-%m", _captured_at_expr()) == date)
    if model:
        mq = fn.json_extract(Gh.prompt_params, "$.model")
        if model == "未记录":
            q = q.where((mq.is_null(True)) | (mq == "") | (mq == "unknown") | (mq == "null"))
        else:
            q = q.where(mq == model)
    if orientation:
        oq = fn.json_extract(Gh.prompt_params, "$.orientation")
        if orientation == "未记录":
            q = q.where((oq.is_null(True)) | (oq == "") | (oq == "unknown") | (oq == "null"))
        else:
            q = q.where(oq == orientation)
    ids = [r.id for r in q.select(Gh.id).distinct()]
    return {"ids": ids, "total": len(ids)}


# ---------------------------------------------------------------------------
# 同步
# ---------------------------------------------------------------------------

@router.api_route("/history_sync", methods=["GET", "POST"])
def sync_history(page_size: int = Query(500)):
    added = _sync_comfyui_history()
    added += _sync_disk_orphans()
    # 注意：list_history 是 FastAPI 路由函数，直接 Python 调用时未显式传入的参数
    # 会拿到 Query(...) 默认对象（FieldInfo）而非真正的 None/""，
    # 会导致 `if category_id is not None` / `tag_ids.split` 等分支误触发并 500。
    # 因此这里必须显式传入全部参数的真实默认值。
    data = list_history(
        page=1, page_size=page_size, favorite=None, sort="newest", search="",
        category_id=None, tag_ids="", source="", date="", model="", orientation="",
    )
    return {"added": added, "items": data["items"], "total": data["total"]}


# ---------------------------------------------------------------------------
# 清理文件已被手动删除的记录
# ---------------------------------------------------------------------------

@router.post("/history/cleanup_missing")
def cleanup_missing_files():
    """扫描所有未删除的历史记录，将对应文件已不存在的记录标记为软删除，
    同时清理残留的缩略图缓存。用于手动从磁盘删除图片后的数据库同步。"""
    from services.thumbnail import _get_image_path

    rows = list(Gh.select().where(Gh.is_deleted == False))
    missing: list[Gh] = []
    for r in rows:
        path = _get_image_path(r.filename, r.subfolder or "", r.img_type or "output")
        if path is None:
            missing.append(r)
            _cleanup_thumbnails(r.filename or "", r.subfolder or "", r.img_type or "output")

    if missing:
        ids = [r.id for r in missing]
        Gh.update(is_deleted=True).where(Gh.id.in_(ids)).execute()

    return {"success": True, "cleaned": len(missing), "total": len(rows)}


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
    # 清理缩略图
    _cleanup_thumbnails(r.filename or "", r.subfolder or "", r.img_type or "output")
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
    for r in Gh.select().where(Gh.id.in_(ids)):
        _cleanup_thumbnails(r.filename or "", r.subfolder or "", r.img_type or "output")
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
    category_id: str = Query(""),
    tag_ids: str = Query(""),
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
    if category_id:
        q = q.join(ImageCategory).where(ImageCategory.category == category_id)
    if tag_ids:
        tid_list = [int(t.strip()) for t in tag_ids.split(",") if t.strip()]
        if tid_list:
            # 多标签取交集（图像必须同时拥有所有选中标签）
            for tid in tid_list:
                direct = Gh.id << ImageTag.select(ImageTag.image).where(ImageTag.tag == tid)
                via_prompt = Gh.prompt_id << PromptTag.select(PromptTag.prompt).where(PromptTag.tag == tid)
                q = q.where(direct | via_prompt)
    total = q.count()
    rows = list(q.order_by(_captured_at_expr().desc(), Gh.id.desc()).offset((page - 1) * page_size).limit(page_size))

    # 不再自动删除记录：图片文件暂不可读（junction 抖动/文件被锁/解码失败）并不代表
    # 该历史记录应被删除。旧逻辑在此硬删，曾多次误删正常图片（表现为“刷新页面后
    # 操作历史丢失”）。改为：保留数据库记录，仅以空元数据呈现，绝不在列表/同步路径上
    # 静默销毁用户数据。真正的清理请走显式删除接口。
    alive = []
    for r in rows:
        alive.append(r)

    items = []
    for r in alive:
        meta = get_image_metadata_fast(
            r.filename, r.subfolder or "", r.img_type or "output",
            prompt_params=r.prompt_params,
        )
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

@router.post("/history/backfill_taxonomy")
def backfill_taxonomy():
    """为所有带 prompt_id 且尚未分类的图片批量补齐来源提示词的分类/标签。"""
    done = backfill_image_taxonomy()
    return {"success": True, "backfilled": done}


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
    src_dir = _resolve_if_reparse(src_dir)
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


# ======== Phase 5: 图片分类 / 标签管理 ========
@router.post("/history/{item_id}/categories/{cat_id}")
def add_image_category(item_id: int, cat_id: int):
    r = Gh.get_or_none(Gh.id == item_id)
    if r is None:
        raise HTTPException(404, "历史记录不存在")
    c = Category.get_or_none(Category.id == cat_id)
    if c is None:
        raise HTTPException(404, "分类不存在")
    _, created = ImageCategory.get_or_create(image=item_id, category=cat_id)
    return {"success": True, "created": created}


@router.delete("/history/{item_id}/categories/{cat_id}")
def remove_image_category(item_id: int, cat_id: int):
    pc = ImageCategory.get_or_none((ImageCategory.image == item_id) & (ImageCategory.category == cat_id))
    if pc is None:
        raise HTTPException(404, "关联关系不存在")
    pc.delete_instance()
    return {"success": True}


@router.post("/history/{item_id}/tags/{tag_id}")
def add_image_tag(item_id: int, tag_id: int):
    r = Gh.get_or_none(Gh.id == item_id)
    if r is None:
        raise HTTPException(404, "历史记录不存在")
    t = Tag.get_or_none(Tag.id == tag_id)
    if t is None:
        raise HTTPException(404, "标签不存在")
    _, created = ImageTag.get_or_create(image=item_id, tag=tag_id)
    if created:
        Tag.update(usage_count=Tag.usage_count + 1).where(Tag.id == tag_id).execute()
    return {"success": True, "created": created}


@router.delete("/history/{item_id}/tags/{tag_id}")
def remove_image_tag(item_id: int, tag_id: int):
    it = ImageTag.get_or_none((ImageTag.image == item_id) & (ImageTag.tag == tag_id))
    if it is None:
        raise HTTPException(404, "关联关系不存在")
    it.delete_instance()
    Tag.update(usage_count=Tag.usage_count - 1).where(Tag.id == tag_id).execute()
    return {"success": True}


@router.post("/history/{item_id}/inherit")
def inherit_image_taxonomy(item_id: int):
    r = Gh.get_or_none(Gh.id == item_id)
    if r is None:
        raise HTTPException(404, "历史记录不存在")
    added = inherit_prompt_taxonomy(item_id, force=True)
    return {"success": True, "added": added}
