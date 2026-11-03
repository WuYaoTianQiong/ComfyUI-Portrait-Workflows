"""缩略图生成与缓存"""
from pathlib import Path
from typing import Optional

from PIL import Image as PILImage

from app.config import settings
from app.services import image_formats  # noqa: F401  注册 HEIC/HEIF 解码
from app.services.paths import resolve_image_path

THUMBNAIL_DIR = settings.thumbnail_dir


def _get_image_path(filename: str, subfolder: str, img_type: str) -> Optional[Path]:
    """兼容入口：统一走 `paths.resolve_image_path`（含越界校验与 temp 口径）。"""
    return resolve_image_path(filename, subfolder, img_type)


def clear_thumbnails_for(filename: str, subfolder: str = "", img_type: str = "output") -> int:
    """删除某张图的缩略图缓存；返回删除数量。"""
    safe_filename = (filename or "").replace("/", "_").replace("\\", "_").replace(":", "_")
    safe_subfolder = (subfolder or "").replace("/", "_").replace("\\", "_").replace(":", "_")
    safe_type = (img_type or "output").replace("/", "_").replace("\\", "_").replace(":", "_")
    prefix = f"{safe_filename}_{safe_subfolder}_{safe_type}_"
    deleted = 0
    try:
        for path in THUMBNAIL_DIR.glob(prefix + "*"):
            path.unlink(missing_ok=True)
            deleted += 1
    except OSError:
        pass
    return deleted


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
        with PILImage.open(img_path) as img:
            img.thumbnail((size, size), PILImage.LANCZOS)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.save(str(thumb_path), "WEBP", quality=80)
        return thumb_path
    except Exception:
        return None
