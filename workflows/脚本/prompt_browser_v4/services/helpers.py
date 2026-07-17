"""共享工具函数 —— 消除跨模块重复代码"""
import os
import traceback
from pathlib import Path
from urllib.parse import quote

from config import settings


def _resolve_if_reparse(p: Path) -> Path:
    """Windows 跨卷 junction/symlink 会被 Python 的 exists()/stat()/realpath
    判定为“不受信任的装入点”(WinError 448/22)，导致缩略图与本地图片代理 404。

    若路径本身是重解析点（junction），用 os.readlink 解析到真实目标后再访问，
    彻底绕开 junction 上的信任校验；普通目录则原样返回。
    """
    try:
        target = os.readlink(p)
        if target:
            return Path(target)
    except (OSError, ValueError):
        pass
    return p


def build_view_url(filename: str, subfolder: str, img_type: str) -> str:
    """构建图片访问 URL（优先直读静态文件）"""
    if not subfolder and img_type in ("output", "input", "temp"):
        # 直接返回静态文件 URL，绕过 Python FileResponse
        return f"/{img_type}/{quote(filename)}"
    return (
        f"/api/image"
        f"?filename={quote(filename)}"
        f"&subfolder={quote(subfolder or '')}"
        f"&type={quote(img_type or 'output')}"
    )


def get_image_metadata(filename: str, subfolder: str, img_type: str) -> dict:
    """读取图片文件的分辨率和大小"""
    if not filename:
        return {}
    try:
        if img_type == "input":
            base_dir = settings.comfyui_root / "input"
        else:
            base_dir = settings.comfyui_root / "output"
        base_dir = _resolve_if_reparse(base_dir)
        # 子目录本身也可能是 junction（如 image/2026-07-04），逐段解析，避免 Windows
        # 跨卷 junction 上 exists()/stat() 抛 WinError 448 被误判为文件缺失
        cur = base_dir
        if subfolder:
            for part in subfolder.replace("\\", "/").split("/"):
                if not part:
                    continue
                cur = cur / part
                cur = _resolve_if_reparse(cur)
        img_path = cur / filename
        if not img_path.exists():
            return {}
        file_size = img_path.stat().st_size
        from PIL import Image
        with Image.open(img_path) as img:
            width, height = img.size
        return {"width": width, "height": height, "file_size": file_size}
    except Exception:
        return {}


def compute_orientation(width, height):
    """根据像素宽高返回方向分面值：横图 / 竖图 / 方图；宽高缺失返回 None。"""
    if not width or not height:
        return None
    # 容忍 2% 以内的取整误差，避免近似正方形被误判
    if abs(width - height) <= max(width, height) * 0.02:
        return "方图"
    return "横图" if width > height else "竖图"


import json


# ComfyUI 中用于加载主模型的节点类型（其 checkpoint/unet 名称输入键）
CHECKPOINT_NODE_TYPES = {
    "CheckpointLoaderSimple",
    "CheckpointLoaderGGUF",
    "unCLIPCheckpointLoader",
    "CheckpointLoaderNF4",
    "diffusersModelLoader",
    "UNETLoader",
}


def _extract_model_from_workflow(wf) -> str | None:
    """从 ComfyUI workflow/prompt 结构提取主模型名（checkpoint 文件名）。

    兼容三种格式：
      - prompt 字典：{node_id: {class_type, inputs}}
      - workflow 字典：{nodes: [{type, widgets_values, inputs}]}
      - 外层含 {"prompt": {...}} 的封装
    """
    if not wf or not isinstance(wf, dict):
        return None
    # 情形1：prompt 字典 {node_id: {class_type, inputs}}
    if all(
        (isinstance(k, (str, int)) and str(k).lstrip("-").isdigit())
        for k in (list(wf.keys())[:1] or ["_"])
    ):
        for node in wf.values():
            if not isinstance(node, dict):
                continue
            ct = node.get("class_type") or node.get("type")
            if ct in CHECKPOINT_NODE_TYPES:
                inp = node.get("inputs", {}) or {}
                name = inp.get("ckpt_name") or inp.get("unet_name") or inp.get("model_name")
                if name:
                    return name
    # 情形2：workflow 字典 {nodes: [...]}
    nodes = wf.get("nodes")
    if nodes is not None:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            ct = node.get("type") or node.get("class_type")
            if ct in CHECKPOINT_NODE_TYPES:
                wv = node.get("widgets_values")
                if isinstance(wv, list) and wv and isinstance(wv[0], str):
                    return wv[0]
                inp = node.get("inputs", {}) or {}
                name = inp.get("ckpt_name") or inp.get("unet_name") or inp.get("model_name")
                if name:
                    return name
    # 情形3：{"prompt": {...}} 封装
    if "prompt" in wf and isinstance(wf["prompt"], dict):
        return _extract_model_from_workflow(wf["prompt"])
    return None


def extract_model_name(filename: str, subfolder: str, img_type: str) -> str | None:
    """从出图 PNG 的元数据（workflow/prompt text chunk）提取主模型名；找不到返回 None。

    复用 get_image_metadata 的图片定位逻辑（settings.comfyui_root + junction 解析）。
    """
    if not filename:
        return None
    try:
        base_dir = settings.comfyui_root / ("input" if img_type == "input" else "output")
        base_dir = _resolve_if_reparse(base_dir)
        img_path = base_dir / (subfolder or "") / filename if subfolder else base_dir / filename
        if not img_path.exists():
            return None
        from PIL import Image
        with Image.open(img_path) as img:
            info = dict(img.info)
        for key in ("workflow", "prompt"):
            raw = info.get(key)
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            model = _extract_model_from_workflow(data)
            if model:
                return model
    except Exception:
        return None
    return None


def extract_model_from_comfy_prompt(prompt_dict) -> str | None:
    """从 ComfyUI history API 的 prompt 字典（{node_id: {class_type, inputs}}）提取模型名。"""
    return _extract_model_from_workflow(prompt_dict)

