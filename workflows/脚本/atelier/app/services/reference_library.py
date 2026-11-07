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

LIBRARIES: tuple[str, ...] = ("pose", "costume", "portrait", "hair", "costume-anime")

logger = logging.getLogger("atelier.reference")

#: 上游 2026-11-04 的四库条数基线；偏离 ±5% 说明数据换版或字段改名，值得告警。
BASELINE_COUNTS: dict[str, int] = {
    "pose": 1439,
    "costume": 1407,
    "portrait": 1499,
    "hair": 489,
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
    "hair": "发型库",
    "costume-anime": "外链服装",
}

#: 姿势库的来源注册表（只服务 `pose`，不是新的对外库）。
#: 每个来源有自己的根目录与元数据格式；合并只在内存里发生，不落盘。
POSE_SOURCE_UPSTREAM = "upstream"
POSE_SOURCE_PSL = "pose-studio-lite"
PSL_ID_PREFIX = "psl-"


@dataclass(frozen=True)
class PoseSource:
    key: str
    label: str
    root: Path
    metadata: Path
    kind: str  # "upstream" | "psl"
    id_prefix: str
    has_depth: bool
    baseline: int | None


POSE_SOURCE_BASELINES = {
    POSE_SOURCE_UPSTREAM: 1439,
    POSE_SOURCE_PSL: 280,
}

#: 服装库的第二来源：角色创作库精选 60 件（本地只读包，带署名）。
COSTUME_SOURCE_UPSTREAM = "upstream"
COSTUME_SOURCE_CHARACTER = "character-ref"
COSTUME_CHARACTER_LABEL = "角色创作库 @62656456"
COSTUME_CHARACTER_SITE = "https://62656456.github.io/character-reference-library/"


@dataclass(frozen=True)
class CostumeSource:
    key: str
    label: str
    root: Path
    metadata: Path
    baseline: int | None


COSTUME_SOURCE_BASELINES = {
    COSTUME_SOURCE_UPSTREAM: 1407,
    # 精选包按批扩充（60 → 120 → …），不设固定基线，避免每次扩库都报“偏离基线”。
    COSTUME_SOURCE_CHARACTER: None,
}

#: 发型库（角色创作库全量包）来源标识。
HAIR_SOURCE_KEY = "character-ref"
HAIR_LABEL = COSTUME_CHARACTER_LABEL
HAIR_CACHE_KEY = ("__hair__", "hair")

#: 姿势库 canonical 分类（三轴：来源 / 分级 / 构图；类型与风格独立）。
COMPOSITION_FULL = "full"
COMPOSITION_UPPER = "upper"
COMPOSITION_PAIR = "pair"
COMPOSITION_UNKNOWN = "unknown"

UPSTREAM_POSE_TYPE = {
    "站姿": "站立",
    "坐姿": "坐姿",
    "跪立": "跪姿",
    "跪立・四肢着地": "跪姿",
    "趴卧": "躺卧",
    "侧坐・女孩坐": "坐姿",
    "蹲姿": "蹲姿",
    "前倾": "前倾",
    "后仰・挺背": "后仰",
    "扭身": "扭转",
    "特殊": "特殊",
}
UPSTREAM_UPPER_STYLE = {
    "可爱系": "可爱",
    "挤胸・强调事业线系": "胸线强调",
    "性感・大胆系": "性感",
}
PSL_POSE_TYPE = {
    "站立": "站立",
    "站姿": "站立",
    "站立贴近": "站立",
    "坐姿": "坐姿",
    "侧坐・少女坐": "坐姿",
    "跪姿": "跪姿",
    "跪姿・爬姿": "跪姿",
    "躺姿": "躺卧",
    "躺卧": "躺卧",
    "侧卧": "躺卧",
    "蹲姿": "蹲姿",
    "前倾": "前倾",
    "后仰": "后仰",
    "扭转": "扭转",
    "特殊": "特殊",
}
PSL_UPPER_STYLE = {
    "可爱系": "可爱",
    "胸线强调系": "胸线强调",
    "性感系": "性感",
}
#: PSL 双人档的分类混了「身体姿态」和「体位」；归一成与上游同名的体位词，
#: 原始 facet 仍保留在 `facet` / 搜索串里。
PSL_PAIR_POSITION = {
    "站立": "立位",
    "坐姿": "坐位",
    "躺卧": "卧姿",
    "侧卧": "卧姿",
    "站立贴近": "立位贴身",
    "坐着贴近": "坐位贴身",
    "面对面坐": "面对面坐位",
    "背向坐": "背向坐位",
    "坐在上方": "骑乘位",
    "前后位置": "后入位",
    "正对卧位": "正常位（传教士）",
    "贴脸系": "贴脸系",
    "特殊": "特殊",
}


#: 姿势可用性备注（2026-11-07 40 + 28 样本实测，见验证文档 §13.7 / §13.9）。
#: 键为完整条目 ID；有备注即 `usable=False`：仍可手动选择，但列表降权、随机候选排除。
POSE_USABILITY_NOTES: dict[str, str] = {
    "psl-D046": "姿势不跟随：3/3 样本被模型改成并排站",
    "psl-D042": "姿势跟随不稳定：2/4 样本未复现单脚后踢",
}


def _pose_usability(item_id: str) -> tuple[bool, str]:
    note = POSE_USABILITY_NOTES.get(item_id, "")
    return (not note, note)


def _upstream_composition(group: str) -> str:
    if "双人" in group:
        return COMPOSITION_PAIR
    if "上半身" in group:
        return COMPOSITION_UPPER
    if "全身" in group:
        return COMPOSITION_FULL
    return COMPOSITION_UNKNOWN


def _upstream_pose_type_style(
    group: str, facet: str, composition: str
) -> tuple[str, str]:
    """上游「体系 + 分类」→ canonical pose_type/style。"""
    if composition == COMPOSITION_UPPER:
        return "上半身", UPSTREAM_UPPER_STYLE.get(facet, "未分类")
    if composition == COMPOSITION_PAIR:
        return facet or "未分类", "性感"
    pose_type = UPSTREAM_POSE_TYPE.get(facet, "未分类")
    if pose_type == "特殊":
        return pose_type, "特殊"
    return pose_type, ("性感" if "性感" in group else "标准")


def _psl_composition(obj: dict[str, Any]) -> str:
    """PSL `series` 是构图真源；tags 只做兜底。"""
    series = str(obj.get("series") or "").strip()
    tags = {str(tag) for tag in (obj.get("tags") or [])}
    if series == "duo" or "双人" in tags:
        return COMPOSITION_PAIR
    if series == "upper" or "半身" in tags:
        return COMPOSITION_UPPER
    if series in ("std", "sexy") or "全身" in tags:
        return COMPOSITION_FULL
    return COMPOSITION_UNKNOWN


def _psl_pose_type_style(
    obj: dict[str, Any], composition: str
) -> tuple[str, str]:
    """PSL `facet` + `category` → canonical pose_type/style。"""
    facet = str(obj.get("facet") or "").strip()
    series = str(obj.get("series") or "").strip()
    nsfw = bool(obj.get("nsfw"))
    if composition == COMPOSITION_PAIR:
        return PSL_PAIR_POSITION.get(facet, facet or "未分类"), (
            "性感" if nsfw else "标准"
        )
    if composition == COMPOSITION_UPPER:
        return "上半身", PSL_UPPER_STYLE.get(facet, "未分类")
    pose_type = PSL_POSE_TYPE.get(facet, "未分类")
    if pose_type == "特殊":
        return pose_type, "特殊"
    if series == "sexy" or nsfw:
        return pose_type, "性感"
    if facet == "可爱系":
        return pose_type, "可爱"
    if facet == "胸线强调系":
        return pose_type, "胸线强调"
    return pose_type, "标准"

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
    "hair": {
        "name": "标题",
        "group": "分区",
        "facet": "视图",
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

IMAGE_KINDS: tuple[str, ...] = ("thumb", "image", "depth", "depth_thumb", "front", "back")


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
    if library == "hair":
        return _text(obj, "视图")
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
    nsfw = _is_nsfw(library, obj, group)

    #: canonical 三轴字段；非 pose 库保持空串，前端按旧字段展示。
    source = ""
    composition = ""
    pose_type = ""
    style = ""
    if library == "pose":
        source = POSE_SOURCE_UPSTREAM
        composition = _upstream_composition(group)
        pose_type, style = _upstream_pose_type_style(group, facet, composition)

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
        "source": source,
        "source_label": "",
        "composition": composition,
        "pose_type": pose_type,
        "style": style,
    }
    search_text = " ".join(
        part
        for part in [
            _search_text(library, obj, fields),
            composition,
            pose_type,
            style,
        ]
        if part
    )

    thumb_upstream = _text(obj, mapping["thumb"])
    image_upstream = _text(obj, mapping["image"])
    back_rel = _text(obj, "背面") if library == "hair" else ""
    front_rel = _text(obj, "正面") if library == "hair" else ""
    hair_usable = bool(obj.get("可用于发型槽")) if library == "hair" else False
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

    usable, usable_note = _pose_usability(item_id) if library == "pose" else (True, "")
    return {
        **fields,
        "thumb_url": thumb_url,
        "image_url": image_url,
        "depth_url": depth_url,
        "depth_thumb_url": depth_thumb_url,
        #: 仅 pose：可用性标记；非姿势库恒为 True / 空串
        "usable": usable,
        "usable_note": usable_note,
        "hot": bool(obj.get("热门", False)),
        "featured": bool(obj.get("精选", False)),
        "nsfw": nsfw,
        "has_depth": library == "pose",
        "remote": remote,
        #: 仅 costume-anime 映射上游「来源地址」；其他库恒 None
        "source_url": (_text(obj, "来源地址") or None) if remote else None,
        #: 仅 hair：正/背面裁切端点与是否可用于第 4 槽
        "hair_front_url": _image_url(library, item_id, "front") if front_rel else None,
        "hair_back_url": _image_url(library, item_id, "back") if back_rel else None,
        "hair_usable": hair_usable,
        #: 与后端过滤一致的预拼检索串（小写前的原文），前端「检索」字段直接取此值
        "search_text": search_text,
        "_search": search_text.lower(),
        "_thumb_rel": thumb_rel,
        "_image_rel": image_rel,
        "_front_rel": front_rel,
        "_back_rel": back_rel,
        #: 外链原始 URL（仅服务端内部使用，`_public` 不会下发）
        "_remote_thumb": thumb_upstream or image_upstream,
        "_remote_image": image_upstream or None,
    }


def _pose_sources() -> list[PoseSource]:
    """当前可用的姿势来源；第二来源缺失时只返回上游，行为与合并前一致。"""
    root = reference_root()
    sources = [
        PoseSource(
            key=POSE_SOURCE_UPSTREAM,
            label="原图库",
            root=root,
            metadata=root / LIBRARY_FILES["pose"],
            kind="upstream",
            id_prefix="",
            has_depth=True,
            baseline=POSE_SOURCE_BASELINES[POSE_SOURCE_UPSTREAM],
        )
    ]
    extra = settings.pose_extra_dir
    if extra is not None:
        extra = Path(extra).expanduser().absolute()
        sources.append(
            PoseSource(
                key=POSE_SOURCE_PSL,
                label=POSE_SOURCE_PSL,
                root=extra,
                metadata=extra / "meta.json",
                kind="psl",
                id_prefix=PSL_ID_PREFIX,
                has_depth=False,
                baseline=POSE_SOURCE_BASELINES[POSE_SOURCE_PSL],
            )
        )
    return sources


def _psl_to_record(source: PoseSource, obj: dict[str, Any]) -> dict[str, Any] | None:
    """`pose-studio-lite/meta.json` 条目 → 与上游同形的姿势 DTO。

    该来源没有深度图；`depth_url` / `depth_thumb_url` 恒 None。
    """
    raw_id = str(obj.get("id") or "").strip()
    if not raw_id:
        return None
    item_id = f"{source.id_prefix}{raw_id}"
    name = str(obj.get("name") or "").strip()
    group = f"{source.label}・{str(obj.get('group') or '').strip()}".rstrip("・")
    facet = str(obj.get("facet") or "").strip()
    angle = str(obj.get("angle_zh") or obj.get("angle") or "").strip()
    tags = [str(tag).strip() for tag in (obj.get("tags") or []) if str(tag).strip()]
    composition = _psl_composition(obj)
    pose_type, style = _psl_pose_type_style(obj, composition)
    search_text = " ".join(
        part
        for part in [
            str(obj.get("search") or ""),
            item_id,
            name,
            raw_id,
            source.label,
            group,
            facet,
            composition,
            pose_type,
            style,
            angle,
            *tags,
        ]
        if part
    )
    thumb_rel = str(obj.get("thumb") or obj.get("file") or "").strip()
    image_rel = str(obj.get("file") or "").strip()
    subtitle = " · ".join(part for part in [raw_id, angle] if part)
    usable, usable_note = _pose_usability(item_id)
    return {
        "id": item_id,
        "library": "pose",
        "name": name,
        "subtitle": subtitle,
        "number": raw_id,
        "group": group,
        "facet": facet,
        "angle": angle,
        "tags": tags,
        "keywords": "",
        "source": source.key,
        "source_label": source.label,
        "composition": composition,
        "pose_type": pose_type,
        "style": style,
        "thumb_url": _image_url("pose", item_id, "thumb"),
        "image_url": _image_url("pose", item_id, "image"),
        "depth_url": None,
        "depth_thumb_url": None,
        "hot": False,
        "featured": False,
        "nsfw": bool(obj.get("nsfw")),
        "has_depth": False,
        "remote": False,
        "source_url": None,
        #: 姿势可用性标记：不参与筛选，只做列表降权 / 随机排除 / UI 提示
        "usable": usable,
        "usable_note": usable_note,
        "search_text": search_text,
        "_search": search_text.lower(),
        "_thumb_rel": thumb_rel,
        "_image_rel": image_rel,
    }


def _log_source_count(source: PoseSource, count: int) -> None:
    """逐来源校验条数；合并总数不能再用单一基线判断。"""
    if count == 0:
        logger.warning("姿势来源 %s 加载到 0 条：%s", source.label, source.metadata)
        return
    if source.baseline and abs(count - source.baseline) > source.baseline * BASELINE_TOLERANCE:
        logger.warning(
            "姿势来源 %s 条数 %d 偏离基线 %d（±%d%%），请检查字段是否改名",
            source.label,
            count,
            source.baseline,
            int(BASELINE_TOLERANCE * 100),
        )
        return
    logger.info("姿势来源 %s 加载完成：%d 条", source.label, count)


def _load_pose_source(source: PoseSource) -> list[dict[str, Any]]:
    """加载单个姿势来源并缓存；图片根/深度能力/来源标记随记录下发。"""
    if source.root is None:
        return []
    mtime = _mtime_ns(source.metadata)
    if mtime is None:
        if source.kind == "upstream":
            logger.warning("姿势来源 %s 数据文件不存在：%s", source.label, source.metadata)
        else:
            logger.info("姿势来源 %s 未安装，已跳过：%s", source.label, source.metadata)
        return []
    key = (str(source.metadata), f"pose-source:{source.key}")
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and cached.mtime_ns == mtime:
            return cached.items

    try:
        raw = json.loads(source.metadata.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("姿势来源 %s 读取/解析失败：%s", source.label, exc)
        return []
    rows = raw.get("items") if source.kind == "psl" and isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        logger.warning("姿势来源 %s 顶层结构不是数组/items：%s", source.label, source.metadata)
        return []

    records: list[dict[str, Any]] = []
    for obj in rows:
        if not isinstance(obj, dict):
            continue
        record = (
            _psl_to_record(source, obj)
            if source.kind == "psl"
            else _to_record("pose", obj)
        )
        if record is None:
            continue
        record["_root"] = source.root
        record["_has_depth"] = source.has_depth
        record["_source"] = source.key
        record["_source_label"] = source.label
        records.append(record)

    _log_source_count(source, len(records))
    with _LOCK:
        _CACHE[key] = _CacheEntry(
            mtime_ns=mtime,
            items=records,
            by_id={record["id"]: record for record in records},
        )
    return records


def _load_pose_merged() -> list[dict[str, Any]]:
    """合并所有姿势来源；任一来源 mtime 变化即重建合并缓存。"""
    sources = _pose_sources()
    stamps = tuple(
        (str(source.metadata), _mtime_ns(source.metadata)) for source in sources
    )
    key = ("__pose_merged__", "pose")
    stamp = hash(stamps)
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and cached.mtime_ns == stamp:
            return cached.items

    items: list[dict[str, Any]] = []
    for source in sources:
        items.extend(_load_pose_source(source))

    with _LOCK:
        _CACHE[key] = _CacheEntry(
            mtime_ns=stamp,
            items=items,
            by_id={record["id"]: record for record in items},
        )
    return items


def _costume_sources() -> list[CostumeSource]:
    """当前可用的服装来源；角色创作库 60 件未安装时只加载上游。"""
    root = reference_root()
    sources = [
        CostumeSource(
            key=COSTUME_SOURCE_UPSTREAM,
            label="",
            root=root,
            metadata=root / LIBRARY_FILES["costume"],
            baseline=COSTUME_SOURCE_BASELINES[COSTUME_SOURCE_UPSTREAM],
        )
    ]
    extra = settings.costume_character_dir
    if extra is not None:
        extra = Path(extra).expanduser().absolute()
        sources.append(
            CostumeSource(
                key=COSTUME_SOURCE_CHARACTER,
                label=COSTUME_CHARACTER_LABEL,
                root=extra,
                metadata=extra / "meta.json",
                baseline=COSTUME_SOURCE_BASELINES[COSTUME_SOURCE_CHARACTER],
            )
        )
    return sources


def _log_costume_source(source: CostumeSource, count: int) -> None:
    if count == 0:
        logger.warning("服装来源 %s 加载到 0 条：%s", source.key, source.metadata)
        return
    if source.baseline and abs(count - source.baseline) > source.baseline * BASELINE_TOLERANCE:
        logger.warning(
            "服装来源 %s 条数 %d 偏离基线 %d（±%d%%），请检查字段是否改名",
            source.key,
            count,
            source.baseline,
            int(BASELINE_TOLERANCE * 100),
        )
        return
    logger.info("服装来源 %s 加载完成：%d 条", source.key, count)


def _load_costume_source(source: CostumeSource) -> list[dict[str, Any]]:
    mtime = _mtime_ns(source.metadata)
    if mtime is None:
        if source.key == COSTUME_SOURCE_UPSTREAM:
            logger.warning("服装来源 %s 数据文件不存在：%s", source.key, source.metadata)
        else:
            logger.info("服装来源 %s 未安装，已跳过：%s", source.key, source.metadata)
        return []
    key = (str(source.metadata), f"costume-source:{source.key}")
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and cached.mtime_ns == mtime:
            return cached.items

    try:
        raw = json.loads(source.metadata.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("服装来源 %s 读取/解析失败：%s", source.key, exc)
        return []
    if not isinstance(raw, list):
        logger.warning("服装来源 %s 顶层不是数组：%s", source.key, source.metadata)
        return []

    records: list[dict[str, Any]] = []
    for obj in raw:
        if not isinstance(obj, dict):
            continue
        record = _to_record("costume", obj)
        if record is None:
            continue
        record["_root"] = source.root
        record["_source"] = source.key
        record["source"] = source.key
        if source.key == COSTUME_SOURCE_CHARACTER:
            record["source_label"] = source.label
            record["source_url"] = COSTUME_CHARACTER_SITE
        else:
            record["source_label"] = ""
        records.append(record)

    _log_costume_source(source, len(records))
    with _LOCK:
        _CACHE[key] = _CacheEntry(
            mtime_ns=mtime,
            items=records,
            by_id={record["id"]: record for record in records},
        )
    return records


def _load_costume_merged() -> list[dict[str, Any]]:
    sources = _costume_sources()
    stamps = tuple(
        (str(source.metadata), _mtime_ns(source.metadata)) for source in sources
    )
    key = ("__costume_merged__", "costume")
    stamp = hash(stamps)
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and cached.mtime_ns == stamp:
            return cached.items

    items: list[dict[str, Any]] = []
    for source in sources:
        items.extend(_load_costume_source(source))

    with _LOCK:
        _CACHE[key] = _CacheEntry(
            mtime_ns=stamp,
            items=items,
            by_id={record["id"]: record for record in items},
        )
    return items


def _hair_pack() -> Path | None:
    extra = settings.hair_character_dir
    if extra is None:
        return None
    return Path(extra).expanduser().absolute()


def _load_hair_pack() -> list[dict[str, Any]]:
    """加载角色创作库发型全量包；未安装时返回空列表。"""
    pack = _hair_pack()
    if pack is None:
        return []
    metadata = pack / "meta.json"
    mtime = _mtime_ns(metadata)
    if mtime is None:
        logger.info("发型来源未安装，已跳过：%s", metadata)
        return []
    with _LOCK:
        cached = _CACHE.get(HAIR_CACHE_KEY)
        if cached and cached.mtime_ns == mtime:
            return cached.items

    try:
        raw = json.loads(metadata.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("发型来源读取/解析失败：%s", exc)
        return []
    if not isinstance(raw, list):
        logger.warning("发型来源顶层不是数组：%s", metadata)
        return []

    records: list[dict[str, Any]] = []
    for obj in raw:
        if not isinstance(obj, dict):
            continue
        record = _to_record("hair", obj)
        if record is None:
            continue
        record["_root"] = pack
        record["_source"] = HAIR_SOURCE_KEY
        record["source"] = HAIR_SOURCE_KEY
        record["source_label"] = HAIR_LABEL
        record["source_url"] = COSTUME_CHARACTER_SITE
        records.append(record)

    _log_loaded_count("hair", len(records))
    with _LOCK:
        _CACHE[HAIR_CACHE_KEY] = _CacheEntry(
            mtime_ns=mtime,
            items=records,
            by_id={record["id"]: record for record in records},
        )
    return records


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
    """按 mtime 缓存加载单库；文件缺失或 JSON 损坏时降级为空列表。

    `pose` 是唯一的多来源库：上游 + pose-studio-lite，在内存里合并。
    """
    if library not in LIBRARIES:
        return []
    if library == "pose":
        return _load_pose_merged()
    if library == "costume":
        return _load_costume_merged()
    if library == "hair":
        return _load_hair_pack()
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
        source_stats: list[dict[str, Any]] | None = None
        if library == "pose":
            available = False
            source_stats = []
            for source in _pose_sources():
                try:
                    source_available = source.metadata.is_file()
                except OSError:
                    source_available = False
                available = available or source_available
                source_stats.append(
                    {
                        "key": source.key,
                        "label": source.label,
                        "total": len(_load_pose_source(source)),
                        "available": source_available,
                        "has_depth": source.has_depth,
                    }
                )
        elif library == "costume":
            available = False
            source_stats = []
            for source in _costume_sources():
                try:
                    source_available = source.metadata.is_file()
                except OSError:
                    source_available = False
                available = available or source_available
                source_stats.append(
                    {
                        "key": source.key,
                        "label": source.label or "原图库",
                        "total": len(_load_costume_source(source)),
                        "available": source_available,
                        "has_depth": False,
                    }
                )
        elif library == "hair":
            pack = _hair_pack()
            try:
                available = bool(pack and (pack / "meta.json").is_file())
            except OSError:
                available = False
            source_stats = [
                {
                    "key": HAIR_SOURCE_KEY,
                    "label": HAIR_LABEL,
                    "total": len(all_items),
                    "available": available,
                    "has_depth": False,
                }
            ]
        else:
            path = _library_path(library)
            try:
                available = path.is_file()
            except OSError:
                available = False
        entry: dict[str, Any] = {
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
        if source_stats is not None:
            entry["sources"] = source_stats
        out.append(entry)
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
    if library not in LIBRARIES or not item_id:
        return None
    _load(library)  # 确保缓存已按 mtime 填充
    if library == "pose":
        key = ("__pose_merged__", "pose")
    elif library == "costume":
        key = ("__costume_merged__", "costume")
    elif library == "hair":
        key = HAIR_CACHE_KEY
    else:
        key = (str(_library_path(library)), library)
    with _LOCK:
        entry = _CACHE.get(key)
        return entry.by_id.get(item_id) if entry else None


# ---------------------------------------------------------------------------
# 图片解析（root 包含校验）
# ---------------------------------------------------------------------------


def _safe_image_path(rel: str, root: Path | None = None) -> Path:
    """把 JSON 里的相对路径解析成真实文件；越界 400、缺失 404。

    `root` 是该条目所属来源的根（pose 多来源时必须逐来源校验），默认上游根。
    """
    parts = _relative_parts(rel)
    if parts is None:
        raise ReferenceImageError(400, "非法的图片路径")
    if not parts:
        raise ReferenceImageError(404, "图片不存在")

    base = Path(root) if root is not None else reference_root()
    cur = base
    for part in parts:
        cur = strip_extended_prefix(_resolve_if_reparse(cur / part))

    if not is_inside_dir(base, cur):
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
        if library != "pose" or not record.get("_has_depth"):
            raise ReferenceImageError(404, "该来源没有深度图")
        rel = f"img/depth/{record['id']}.webp"
    elif kind == "depth_thumb":
        if library != "pose" or not record.get("_has_depth"):
            raise ReferenceImageError(404, "该来源没有深度缩略图")
        rel = f"thumbs/depth/{record['id']}.webp"
    elif kind == "thumb":
        rel = record["_thumb_rel"]
    elif kind in ("front", "back"):
        if library != "hair":
            raise ReferenceImageError(404, "该库没有正/背面图")
        rel = record.get(f"_{kind}_rel") or ""
    else:
        rel = record["_image_rel"]

    if not rel:
        raise ReferenceImageError(404, "图片不存在")
    return _safe_image_path(rel, record.get("_root"))


def media_type_for(path: Path) -> str:
    mt, _ = mimetypes.guess_type(str(path))
    return mt or "application/octet-stream"