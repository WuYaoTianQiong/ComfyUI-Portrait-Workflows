"""工作流目录扫描 —— 哪些 json 是可用的 ComfyUI 工作流、它们有哪些可注入能力。

`routers/comfyui.py`（`/api/workflows`）与 `routers/system.py`（`/api/system/config`
要报默认工作流）都需要这套判定，抽到服务层，避免路由之间互相 import 私有函数。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.config import settings
from app.services.workflow_parser import (
    is_video_workflow,
    load_workflow,
    detect_workflow_caps,
    detect_workflow_params,
)

logger = logging.getLogger(__name__)

#: 历史归档目录：**不参与自动扫描**；用户可在「分类与标签 → 工作流」手动上传任意目录的 JSON。
ARCHIVE_DIR = settings.library_root / "历史工作流"
# 兼容旧引用
DEPRECATED_DIR = ARCHIVE_DIR

#: 探测缓存：路径 → (mtime, caps, params, media_kind)。文件没改动就不重复解析。
_meta_cache: dict[str, tuple[float, dict[str, bool], dict, str]] = {}


def search_dirs() -> list[Path]:
    """自动扫描目录：只扫库根目录。

    其他位置（历史工作流 / 任意磁盘目录）走前端「上传自定义工作流」，
    内容存在本机 localStorage，出图时随请求带给后端。
    """
    return [settings.library_root]


def is_valid_workflow(filepath: Path) -> bool:
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


def _load_meta(path: Path) -> tuple[float, dict[str, bool], dict, str]:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return 0.0, {}, {}, "image"
    cached = _meta_cache.get(str(path))
    if cached and cached[0] == mtime:
        return cached
    try:
        workflow = load_workflow(str(path))
        caps = detect_workflow_caps(workflow)
        params = detect_workflow_params(workflow)
        media_kind = "video" if is_video_workflow(workflow) else "image"
    except Exception as exc:
        logger.debug("探测工作流能力失败 %s：%s", path.name, exc)
        caps, params, media_kind = {}, {}, "image"
    _meta_cache[str(path)] = (mtime, caps, params, media_kind)
    return _meta_cache[str(path)]


def get_workflow_meta(path: Path) -> tuple[dict[str, bool], dict]:
    """返回某工作流的注入能力与参数描述；解析失败时返回空 dict（schema 默认全 True）。"""
    _, caps, params, _ = _load_meta(path)
    return caps, params


def get_workflow_media_kind(path: Path) -> str:
    """返回 `image` / `video`；视频工作流默认不进入 Atelier 工作流下拉。"""
    return _load_meta(path)[3]


def find_default_workflow(include_video: bool = False) -> str:
    """默认工作流：优先文件名带「文生图」，否则第一个可用工作流。"""
    candidates = [w["path"] for w in list_valid_workflows(include_video=include_video)]
    for candidate in candidates:
        if "文生图" in candidate:
            return candidate
    return candidates[0] if candidates else ""


def list_valid_workflows(include_video: bool = False) -> list[dict]:
    """扫描库根目录的可用工作流，附 caps/params/media_kind 与 mtime。

    `include_video=False`（默认）时跳过含 SaveVideo / VideoCombine 的工作流：
    画廊只处理图片，视频工作流请直接在 ComfyUI 里跑。
    历史工作流/其他目录不自动扫描，走前端手动上传。
    """
    results: list[dict] = []
    seen: set[str] = set()
    for directory in search_dirs():
        if not directory.exists():
            continue
        for file in directory.glob("*.json"):
            if not is_valid_workflow(file):
                continue
            path = str(file)
            if path in seen:
                continue
            seen.add(path)
            mtime, caps, params, media_kind = _load_meta(file)
            if media_kind == "video" and not include_video:
                continue
            results.append({
                "path": path,
                "name": file.name,
                "mtime": mtime,
                "caps": caps,
                "params": params,
                "media_kind": media_kind,
            })
    return results
