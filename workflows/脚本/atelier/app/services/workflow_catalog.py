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
    load_workflow,
    detect_workflow_caps,
    detect_workflow_params,
)

logger = logging.getLogger(__name__)

#: 已废弃但仍在磁盘上的工作流目录（也参与列表与默认值挑选）
DEPRECATED_DIR = settings.library_root / "废弃工作流"

#: 能力探测缓存：路径 → (mtime, caps, params)。文件没改动就不重复解析。
_meta_cache: dict[str, tuple[float, dict[str, bool], dict]] = {}


def search_dirs() -> list[Path]:
    """参与扫描的目录：库根 → 废弃目录。"""
    return [settings.library_root, DEPRECATED_DIR]


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


def get_workflow_meta(path: Path) -> tuple[dict[str, bool], dict]:
    """返回某工作流的注入能力与参数描述；解析失败时返回空 dict（schema 默认全 True）。"""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}, {}
    cached = _meta_cache.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1], cached[2]
    try:
        workflow = load_workflow(str(path))
        caps = detect_workflow_caps(workflow)
        params = detect_workflow_params(workflow)
    except Exception as exc:
        logger.debug("探测工作流能力失败 %s：%s", path.name, exc)
        caps, params = {}, {}
    _meta_cache[str(path)] = (mtime, caps, params)
    return caps, params


def find_default_workflow() -> str:
    """默认工作流：优先文件名带「文生图」，否则第一个可用工作流。"""
    candidates: list[str] = []
    for directory in search_dirs():
        if not directory.exists():
            continue
        for file in sorted(directory.glob("*.json")):
            try:
                if is_valid_workflow(file):
                    candidates.append(str(file))
            except Exception:
                continue
    for candidate in candidates:
        if "文生图" in candidate:
            return candidate
    return candidates[0] if candidates else ""


def list_valid_workflows() -> list[dict]:
    """扫描全部可用工作流，附 caps/params 与 mtime。"""
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
            caps, params = get_workflow_meta(file)
            results.append({
                "path": path,
                "name": file.name,
                "mtime": file.stat().st_mtime,
                "caps": caps,
                "params": params,
            })
    return results
