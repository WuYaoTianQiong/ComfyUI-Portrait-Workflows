"""AI 参考图库 · 只读适配层。

上游 `ai-pose-gallery-zh` 是素材与元数据层，atelier 只读不写：
- 四份 JSON 中文键**逐库不同**（pose/costume/portrait/costume-anime），
  这里为每库维护一张显式映射表，绝不做"统一字段"假设；
- 图片路径只取 JSON 里的相对路径字段，**不拼扩展名**
  （pose 是 `.jpg`/`.png`，其余是 `.webp`）；
- 图片解析后必须落在 `reference_root` 之内，越界一律拒绝；
- 上游 `检索` 字段已是预拼好的全字段检索串，直接子串匹配即可；
- 敏感名单从配置读取，前后端都不硬编码。

缓存按文件 mtime 失效：上游 `git pull` 或手工换图后不需要重启 atelier。
"""
from __future__ import annotations

import json
import logging
import mimetypes
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.config import settings
from app.services.paths import (
    IMAGE_EXTENSIONS,
    _relative_parts,
    _resolve_if_reparse,
    is_inside_dir,
    strip_extended_prefix,
)

LIBRARIES: tuple[str, ...] = ("pose", "costume", "portrait", "costume-anime")

logger = logging.getLogger("atelier.reference")

#: 上游 2026-11-04 的四库条数基线；偏离 ±5% 说明数据换版或字段改名，值得告警。
BASELINE_COUNTS: dict[str, int] = {
    "pose": 1439,
    "costume": 1407,
    "portrait": 1499,
    "costume-anime": 440,
}
BASELINE_TOLERANCE = 0.05

LIBRARY_FILES: dict[str, str] = {
    "pose": "data/pose-zh.json",
    "costume": "data/costume-zh.json",
    "portrait": "data/portrait-zh.json",
    "costume-anime": "data/costume-anime-zh.json",
}

LIBRARY_LABELS: dict[str, str] = {
    "pose": "姿势库",
    "costume": "服装库",
    "portrait": "人像库",
    "costume-anime": "外链服装",
}

#: 每库字段映射（中文键 → DTO 字段）。`None` 表示该库没有这个字段。
#: `subtitle` / `nsfw` / `remote` / `depth` 有库专属逻辑，在 `_to_record` 里处理。
FIELD_MAP: dict[str, dict[str, str | None]] = {
    "pose": {
        "name": "姿势名称",
        "group": "体系",
        "facet": "分类",
        "angle": "角度",
        "thumb": "缩略图",
        "image": "原图",
        "search": "检索",
    },
    "costume": {
        "name": "服装名称",
        "group": "分类",
        "facet": None,
        "angle": None,
        "thumb": "缩略图",
        "image": "原图",
        "search": "检索",
    },
    "portrait": {
        "name": "标题",
        "group": "分区",
        "facet": "发长",
        "angle": None,
        "thumb": "缩略图",
        "image": "原图",
        "search": "检索",
    },
    "costume-anime": {
        "name": "服装名称",
        "group": "一级分类",
        "facet": "分类",
        "angle": None,
        "thumb": "缩略图",
        "image": "原图",
        "search": "检索",
    },
}

IMAGE_KINDS: tuple[str, ...] = ("thumb", "image", "depth", "depth_thumb")


class ReferenceImageError(Exception):
    """图片解析失败：`status_code` 直接映射到 HTTP 状态码。"""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class _CacheEntry:
    mtime_ns: int
    items: list[dict[str, Any]]
    #: id → 记录：图片/详情端点每张图都要按 id 取记录，线性扫全库会随页大小放大
    by_id: dict[str, dict[str, Any]]


_LOCK = threading.RLock()
_CACHE: dict[tuple[str, str], _CacheEntry] = {}


# ---------------------------------------------------------------------------
# 路径与加载
# ---------------------------------------------------------------------------


def reference_root() -> Path:
    """参考库真实根目录；junction 先解析，避免 Windows WinError 448。"""
    return strip_extended_prefix(_resolve_if_reparse(settings.reference_dir))


def _library_path(library: str) -> Path:
    return reference_root() / LIBRARY_FILES[library]


def _mtime_ns(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def _text(obj: dict[str, Any], key: str | None, default: str = "") -> str:
    if not key:
        return default
    value = obj.get(key, default)
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        return "、".join(str(v) for v in value if v)
    return str(value).strip()


def _tags(obj: dict[str, Any]) -> list[str]:
    value = obj.get("标签")
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def _subtitle(library: str, obj: dict[str, Any]) -> str:
    if library == "pose":
        parts = [_text(obj, "姿势编号"), _text(obj, "角度")]
        return " · ".join(p for p in parts if p)
    if library == "portrait":
        return _text(obj, "发型名称")
    if library == "costume-anime":
        return _text(obj, "日文名称")
    return ""


def _is_nsfw(library: str, obj: dict[str, Any], group: str) -> bool:
    if library == "pose":
        return group in settings.nsfw_pose_systems
    if library == "costume":
        return group in settings.nsfw_costume_categories
    if library == "costume-anime":
        return bool(obj.get("敏感"))
    # portrait 上游不标敏感
    return False


def _search_text(library: str, obj: dict[str, Any], fields: dict[str, str]) -> str:
    raw = _text(obj, FIELD_MAP[library]["search"])
    if raw:
        return raw
    pieces = [
        fields["id"],
        fields["name"],
        fields["subtitle"],
        fields["group"],
        fields["facet"],
        fields["angle"],
    ]
    pieces.extend(_tags(obj))
    pieces.append(_text(obj, "关键词"))
    return " ".join(p for p in pieces if p)


def _image_url(library: str, item_id: str, kind: str) -> str:
    return (
        f"/api/reference/items/{quote(library, safe='')}/"
        f"{quote(item_id, safe='')}/image?kind={kind}"
    )


def _depth_thumb_exists(item_id: str) -> bool:
    """姿势库的深度缩略图是派生文件，缺失时 DTO 给 None（不退回原深度图）。"""
    if not item_id or item_id in (".", ".."):
        return False
    if "/" in item_id or "\\" in item_id or ":" in item_id:
        return False
    try:
        return (reference_root() / "thumbs" / "depth" / f"{item_id}.webp").is_file()
    except OSError:
        return False


def _to_record(library: str, obj: dict[str, Any]) -> dict[str, Any] | None:
    item_id = _text(obj, "id")
    if not item_id:
        return None

    mapping = FIELD_MAP[library]
    group = _text(obj, mapping["group"])
    facet = _text(obj, mapping["facet"])
    angle = _text(obj, mapping["angle"])
    name = _text(obj, mapping["name"])
    subtitle = _subtitle(library, obj)
    remote = library == "costume-anime"
    #: 姿势编号单独暴露给前端（`subtitle` 仍是 `编号 · 角度`，兼容旧调用方）
    number = _text(obj, "姿势编号") if library == "pose" else ""

    fields = {
        "id": item_id,
        "library": library,
        "name": name,
        "subtitle": subtitle,
        "number": number,
        "group": group,
        "facet": facet,
        "angle": angle,
        "tags": _tags(obj),
        "keywords": _text(obj, "关键词"),
    }
    search_text = _search_text(library, obj, fields)

    thumb_upstream = _text(obj, mapping["thumb"])
    image_upstream = _text(obj, mapping["image"])
    thumb_rel = "" if remote else thumb_upstream
    image_rel = "" if remote else image_upstream
    if remote:
        # 外链条目对外只暴露后端图片端点，上游 URL 仅作为服务端内部字段保留：
        # - 缩略图缺失时回退 image 端点；
        # - 两者都缺时给 None，避免前端 `<img src="">` 请求当前页面。
        thumb_url = _image_url(library, item_id, "thumb") if (thumb_upstream or image_upstream) else None
        image_url = _image_url(library, item_id, "image") if image_upstream else None
        depth_url: str | None = None
        depth_thumb_url: str | None = None
    else:
        thumb_url = _image_url(library, item_id, "thumb")
        image_url = _image_url(library, item_id, "image")
        depth_url = _image_url(library, item_id, "depth") if library == "pose" else None
        depth_thumb_url = (
            _image_url(library, item_id, "depth_thumb")
            if library == "pose" and _depth_thumb_exists(item_id)
            else None
        )

    return {
        **fields,
        "thumb_url": thumb_url,
        "image_url": image_url,
        "depth_url": depth_url,
        "depth_thumb_url": depth_thumb_url,
        "hot": bool(obj.get("热门", False)),
        "featured": bool(obj.get("精选", False)),
        "nsfw": _is_nsfw(library, obj, group),
        "remote": remote,
        #: 仅 costume-anime 映射上游「来源地址」；其他库恒 None
        "source_url": (_text(obj, "来源地址") or None) if remote else None,
        #: 与后端过滤一致的预拼检索串（小写前的原文），前端「检索」字段直接取此值
        "search_text": search_text,
        "_search": search_text.lower(),
        "_thumb_rel": thumb_rel,
        "_image_rel": image_rel,
        #: 外链原始 URL（仅服务端内部使用，`_public` 不会下发）
        "_remote_thumb": thumb_upstream or image_upstream,
        "_remote_image": image_upstream or None,
    }


def _log_loaded_count(library: str, count: int) -> None:
    """成功打 info；空库或明显偏离上游基线打 warning，避免"0 条且可用"无从排查。"""
    baseline = BASELINE_COUNTS.get(library)
    if count == 0:
        logger.warning("参考库 %s 加载到 0 条，请检查上游数据文件", library)
        return
    if baseline and abs(count - baseline) > baseline * BASELINE_TOLERANCE:
        logger.warning(
            "参考库 %s 条数 %d 偏离基线 %d（±%d%%），请检查上游字段是否改名",
            library,
            count,
            baseline,
            int(BASELINE_TOLERANCE * 100),
        )
        return
    logger.info("参考库 %s 加载完成：%d 条", library, count)


def _load(library: str) -> list[dict[str, Any]]:
    """按 mtime 缓存加载单库；文件缺失或 JSON 损坏时降级为空列表。"""
    if library not in LIBRARY_FILES:
        return []
    path = _library_path(library)
    mtime = _mtime_ns(path)
    key = (str(path), library)
    if mtime is None:
        logger.warning("参考库 %s 数据文件不存在：%s", library, path)
        return []
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and cached.mtime_ns == mtime:
            return cached.items

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("参考库 %s 读取/解析失败：%s", library, exc)
        return []
    if not isinstance(raw, list):
        logger.warning("参考库 %s 顶层不是数组，已忽略：%s", library, path)
        return []

    items: list[dict[str, Any]] = []
    for obj in raw:
        if not isinstance(obj, dict):
            continue
        record = _to_record(library, obj)
        if record is not None:
            items.append(record)

    _log_loaded_count(library, len(items))
    with _LOCK:
        _CACHE[key] = _CacheEntry(
            mtime_ns=mtime,
            items=items,
            by_id={record["id"]: record for record in items},
        )
    return items


def log_library_summary() -> None:
    """启动时打印四库条数（同时把 JSON 缺失/损坏以 warning 暴露）。"""
    parts = [f"{LIBRARY_LABELS[lib]}={len(_load(lib))}" for lib in LIBRARIES]
    logger.info("参考库加载概况：%s", "，".join(parts))


def clear_cache() -> None:
    """测试与热更新用：清空 mtime 缓存。"""
    with _LOCK:
        _CACHE.clear()


# ---------------------------------------------------------------------------
# 可见性 / 过滤
# ---------------------------------------------------------------------------


def _visible(record: dict[str, Any]) -> bool:
    return settings.reference_allow_nsfw or not record["nsfw"]


def _visible_items(library: str) -> list[dict[str, Any]]:
    return [r for r in _load(library) if _visible(r)]


def _public(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if not k.startswith("_")}


def _match_nsfw(record: dict[str, Any], nsfw: bool | None) -> bool:
    """allow_nsfw 开启后 `nsfw` 参数才生效；关闭时参数被忽略（不是 403）。"""
    if not settings.reference_allow_nsfw or nsfw is None:
        return True
    return record["nsfw"] is nsfw


def _facet_values(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    counter = Counter(r[key] for r in items if r.get(key))
    return [
        {"value": value, "count": count}
        for value, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


# ---------------------------------------------------------------------------
# 对外查询
# ---------------------------------------------------------------------------


def library_stats() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for library in LIBRARIES:
        all_items = _load(library)
        visible = [r for r in all_items if _visible(r)]
        path = _library_path(library)
        try:
            available = path.is_file()
        except OSError:
            available = False
        out.append(
            {
                "library": library,
                "label": LIBRARY_LABELS[library],
                "total": len(all_items),
                "local": sum(1 for r in all_items if not r["remote"]),
                "remote": sum(1 for r in all_items if r["remote"]),
                "visible": len(visible),
                "available": available,
                "allow_nsfw": settings.reference_allow_nsfw,
                "groups": _facet_values(visible, "group"),
                "facets": _facet_values(visible, "facet"),
                "angles": _facet_values(visible, "angle"),
            }
        )
    return out


def query_items(
    library: str,
    search: str = "",
    group: str = "",
    facet: str = "",
    angle: str = "",
    nsfw: bool | None = None,
    page: int = 1,
    page_size: int | None = None,
) -> dict[str, Any]:
    """分页查询；响应结构与全站一致：`{items,total,page,page_size}`。"""
    size = page_size or settings.reference_page_size
    size = max(1, min(size, 200))
    page = max(1, page)

    items = _visible_items(library)
    needle = (search or "").strip().lower()
    if needle:
        items = [r for r in items if needle in r["_search"]]
    if group:
        items = [r for r in items if r["group"] == group]
    if facet:
        items = [r for r in items if r["facet"] == facet]
    if angle:
        items = [r for r in items if r["angle"] == angle]
    items = [r for r in items if _match_nsfw(r, nsfw)]

    total = len(items)
    start = (page - 1) * size
    return {
        "items": [_public(r) for r in items[start:start + size]],
        "total": total,
        "page": page,
        "page_size": size,
    }


def get_item(library: str, item_id: str) -> dict[str, Any] | None:
    record = _find_record(library, item_id)
    if record is None or not _visible(record):
        return None
    return _public(record)


def resolve_remote_url(library: str, item_id: str, kind: str) -> str | None:
    """取外链条目的上游原始图片 URL（仅服务端内部使用，不下发前端）。

    - `thumb`：缩略图缺失时回退原图（对应 DTO 的 thumb 回退规则）；
    - `image`：仅原图；缺失返回 None；
    - `depth` / `depth_thumb`：外链库不缓存派生图，返回 None。
    """
    if library != "costume-anime" or kind not in ("thumb", "image"):
        return None
    record = _find_record(library, item_id)
    if record is None or not record.get("remote"):
        return None
    return record.get("_remote_thumb") if kind == "thumb" else record.get("_remote_image")


def _find_record(library: str, item_id: str) -> dict[str, Any] | None:
    if library not in LIBRARY_FILES or not item_id:
        return None
    _load(library)  # 确保缓存已按 mtime 填充
    key = (str(_library_path(library)), library)
    with _LOCK:
        entry = _CACHE.get(key)
        return entry.by_id.get(item_id) if entry else None


# ---------------------------------------------------------------------------
# 图片解析（root 包含校验）
# ---------------------------------------------------------------------------


def _safe_image_path(rel: str) -> Path:
    """把 JSON 里的相对路径解析成真实文件；越界 400、缺失 404。"""
    parts = _relative_parts(rel)
    if parts is None:
        raise ReferenceImageError(400, "非法的图片路径")
    if not parts:
        raise ReferenceImageError(404, "图片不存在")

    cur = reference_root()
    for part in parts:
        cur = strip_extended_prefix(_resolve_if_reparse(cur / part))

    if not is_inside_dir(reference_root(), cur):
        raise ReferenceImageError(400, "图片路径越界")
    if cur.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ReferenceImageError(404, "图片不存在")
    try:
        if not cur.is_file():
            raise ReferenceImageError(404, "图片不存在")
    except OSError:
        raise ReferenceImageError(404, "图片不存在") from None
    return cur


def resolve_image(library: str, item_id: str, kind: str) -> Path:
    """按 kind 解析本地图片；`remote`/NSFW 不可见/不支持的类型分别返回 400/404。"""
    if kind not in IMAGE_KINDS:
        raise ReferenceImageError(404, "不支持的图片类型")
    record = _find_record(library, item_id)
    if record is None or not _visible(record):
        raise ReferenceImageError(404, "参考条目不存在")
    if record["remote"]:
        # 外链库没有本地深度图：按 §3.3「kind 未命中 → 404」处理，不与"外链不提供本地图"混用。
        if kind in ("depth", "depth_thumb"):
            raise ReferenceImageError(404, "该库没有深度图")
        raise ReferenceImageError(400, "外链条目不提供本地图片")

    if kind == "depth":
        if library != "pose":
            raise ReferenceImageError(404, "该库没有深度图")
        rel = f"img/depth/{item_id}.webp"
    elif kind == "depth_thumb":
        if library != "pose":
            raise ReferenceImageError(404, "该库没有深度缩略图")
        rel = f"thumbs/depth/{item_id}.webp"
    elif kind == "thumb":
        rel = record["_thumb_rel"]
    else:
        rel = record["_image_rel"]

    if not rel:
        raise ReferenceImageError(404, "图片不存在")
    return _safe_image_path(rel)


def media_type_for(path: Path) -> str:
    mt, _ = mimetypes.guess_type(str(path))
    return mt or "application/octet-stream"