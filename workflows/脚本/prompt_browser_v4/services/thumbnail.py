"""缩略图生成与缓存"""
from pathlib import Path
from typing import Optional

from PIL import Image

from config import settings
from services.helpers import _resolve_if_reparse

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
    base_dir = _resolve_if_reparse(base_dir)
    # 子目录本身也可能是 junction，逐段解析避免 WinError 448 误判为文件缺失
    cur = base_dir
    if subfolder:
        for part in subfolder.replace("\\", "/").split("/"):
            if not part:
                continue
            cur = cur / part
            cur = _resolve_if_reparse(cur)
    img_path = cur / filename
    return img_path if img_path.exists() else None


def generate_thumbnail(
    filename: str,
    subfolder: str = "",
    img_type: str = "output",
    size: int = 300,
) -> Optional[Path]:
    """生成缩略图，返回缓存路径。原图不存在则返回 None。

    缓存键使用 st_mtime_ns（纳秒修改时间）标识文件版本，而非原方案
    的 st_size（字节数）。两张不同内容的图碰巧压缩到相同字节数就会
    命中同一个缓存键 → 返回旧缩略图（串图），反复跑相同提示词时极易
    触发。用纳秒级 mtime 可确保每次文件覆写产生不同缓存键。
    """
    img_path = _get_image_path(filename, subfolder, img_type)
    if img_path is None:
        return None

    file_stat = img_path.stat()
    # 用 st_size + st_mtime_ns 共同标识文件版本，二者同时碰撞的概率极低
    cache_key = f"{filename}_{subfolder}_{img_type}_{file_stat.st_size}_{file_stat.st_mtime_ns}_{size}"
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
