"""原子碎片库跨源实验采样（P4）。

只读 `tools/atomic_pilot/fragments.json`，不写数据库、不改生产随机池。
兼容规则：场景 group / 服装 style / 光线 temp / 姿势 facet / 取景 framing。
"""

from __future__ import annotations

import json
import random
import threading
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.costume_policy import costume_covers_lower, has_explicit_content
from app.services.fragment_syntax import FRAGMENT_TYPES

BANK_PATH = settings.app_root / "tools" / "atomic_pilot" / "fragments.json"
MIN_PER_TYPE = 20
POSE_FACET = {"stand", "walk", "sit", "lean", "kneel"}

_LOCK = threading.RLock()
_CACHE: dict[str, Any] = {}


class AtomicPilotUnavailable(RuntimeError):
    """原子库缺失、校验失败或没有兼容组合。"""


def _load_bank() -> dict[str, Any]:
    path = BANK_PATH
    try:
        mtime = path.stat().st_mtime_ns
    except OSError as exc:
        raise AtomicPilotUnavailable(f"原子库不存在：{path}") from exc
    with _LOCK:
        if _CACHE.get("mtime") == mtime:
            return _CACHE["data"]

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AtomicPilotUnavailable(f"原子库读取失败：{exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("fragments"), list):
        raise AtomicPilotUnavailable("原子库顶层结构不合法")

    by_type: dict[str, list[dict[str, Any]]] = {ftype: [] for ftype in FRAGMENT_TYPES}
    by_id: dict[str, dict[str, Any]] = {}
    for item in raw["fragments"]:
        if not isinstance(item, dict):
            continue
        ftype = item.get("type")
        content = (item.get("content") or "").strip()
        fid = item.get("id")
        if ftype not in by_type or not content or not isinstance(fid, str):
            continue
        if "【" in content or "\\n" in content or has_explicit_content(content):
            raise AtomicPilotUnavailable(f"原子库条目不合规：{fid}")
        if ftype == "人物服饰" and not costume_covers_lower(content):
            raise AtomicPilotUnavailable(f"原子库服装未覆盖下装：{fid}")
        by_type[ftype].append(item)
        by_id[fid] = item

    for ftype, items in by_type.items():
        if len(items) < MIN_PER_TYPE:
            raise AtomicPilotUnavailable(
                f"原子库 {ftype} 只有 {len(items)} 条，至少需要 {MIN_PER_TYPE} 条"
            )

    data = {
        "version": raw.get("version", 0),
        "by_type": by_type,
        "by_id": by_id,
    }
    with _LOCK:
        _CACHE.update({"mtime": mtime, "data": data})
    return data


def _pick(rng: random.Random, pool: list[dict[str, Any]], predicate) -> dict[str, Any] | None:
    candidates = [item for item in pool if predicate(item)]
    return rng.choice(candidates) if candidates else None


def sample_combo(seed: int | None = None) -> dict[str, Any]:
    data = _load_bank()
    by_type = data["by_type"]
    rng = random.Random(seed) if seed is not None else random.Random()

    scenes = by_type["场景环境"]
    lights = by_type["光影色调"]
    outfits = by_type["人物服饰"]
    styles = by_type["画风技术"]
    poses = by_type["姿态动作"]
    views = by_type["拍摄视角"]
    faces = by_type["人物面部"]
    bodies = by_type["人物身材"]

    for _ in range(300):
        scene = rng.choice(scenes)
        light = _pick(
            rng, lights,
            lambda x: scene["meta"]["group"] in x["meta"]["scene_fit"]
            and x["meta"]["temp"] in scene["meta"]["light_fit"],
        )
        outfit = _pick(
            rng, outfits,
            lambda x: scene["meta"]["group"] in x["meta"]["scene_fit"]
            and set(x["meta"]["style"]) & set(scene["meta"]["style_fit"]),
        )
        if outfit is None:
            continue
        style = _pick(
            rng, styles,
            lambda x: scene["meta"]["group"] in x["meta"]["scene_fit"]
            and set(x["meta"]["style_fit"]) & set(outfit["meta"]["style"]),
        )
        pose = rng.choice(poses)
        view = _pick(
            rng, views,
            lambda x: pose["meta"]["facet"] in x["meta"]["pose_fit"]
            and x["meta"]["framing"] in pose["meta"]["view_fit"],
        )
        if not all((light, outfit, style, view)):
            continue
        face = rng.choice(faces)
        body = rng.choice(bodies)
        chosen = {
            "人物面部": face, "人物身材": body, "人物服饰": outfit,
            "姿态动作": pose, "拍摄视角": view, "场景环境": scene,
            "光影色调": light, "画风技术": style,
        }
        combo_id = "·".join(
            chosen[key]["id"] for key in ("场景环境", "人物服饰", "姿态动作", "拍摄视角")
        )
        return {
            "bank_version": int(data["version"]),
            "combo_id": combo_id,
            "fragments": [
                {"type": ftype, "content": chosen[ftype]["content"]}
                for ftype in FRAGMENT_TYPES
            ],
            "pose_facet": pose["meta"]["facet"],
            "labels": {
                "face": face["id"], "body": body["id"], "outfit": outfit["id"],
                "pose": pose["id"], "view": view["id"], "scene": scene["id"],
                "light": light["id"], "style": style["id"],
            },
            "warning": "跨源实验：建议人工复核",
        }

    raise AtomicPilotUnavailable("原子库没有可用的兼容组合")
