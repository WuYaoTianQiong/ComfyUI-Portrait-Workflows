"""缩略图生成与缓存"""
from pathlib import Path
from typing import Optional

from PIL import Image

from config import settings

THUMBNAIL_DIR = settings.thumbnail_dir


def _get_image_path(filename: str, subfolder: str, img_type: str) -> Optional[Path]:
    if not filename:
        return None
    if img_type == "input":
        base_dir = settings.comfyui_root / "input"
    elif img_type == "temp":
        base_dir = settings.comfyui_root / "temp"
    else:
        base_dir = settings.comfyui_root / "output"
    if subfolder:
        img_path = base_dir / subfolder / filename
    else:
        img_path = base_dir / filename
    return img_path if img_path.exists() else None


def generate_thumbnail(
    filename: str,
    subfolder: str = "",
    img_type: str = "output",
    size: int = 300,
) -> Optional[Path]:
    """生成缩略图，返回缓存路径。原图不存在则返回 None。"""
    img_path = _get_image_path(filename, subfolder, img_type)
    if img_path is None:
        return None

    file_stat = img_path.stat()
    cache_key = f"{filename}_{subfolder}_{file_stat.st_size}_{size}"
    safe_key = cache_key.replace("/", "_").replace("\\", "_").replace(":", "_")
    thumb_path = THUMBNAIL_DIR / f"{safe_key}.webp"

    if thumb_path.exists():
        return thumb_path

    try:
        with Image.open(img_path) as img:
            img.thumbnail((size, size), Image.LANCZOS)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.save(str(thumb_path), "WEBP", quality=80)
        return thumb_path
    except Exception:
        return None
