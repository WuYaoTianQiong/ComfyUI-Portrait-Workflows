"""共享工具函数 —— 消除跨模块重复代码"""
import traceback
from pathlib import Path
from urllib.parse import quote

from config import settings


def build_view_url(filename: str, subfolder: str, img_type: str) -> str:
    """构建图片代理 URL（供 history/jobs 共用）"""
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
        img_path = base_dir / (subfolder or "") / filename if subfolder else base_dir / filename
        if not img_path.exists():
            return {}
        file_size = img_path.stat().st_size
        from PIL import Image
        with Image.open(img_path) as img:
            width, height = img.size
        return {"width": width, "height": height, "file_size": file_size}
    except Exception:
        return {}
