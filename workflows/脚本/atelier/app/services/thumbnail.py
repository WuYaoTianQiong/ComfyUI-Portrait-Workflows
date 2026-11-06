"""缩略图生成与缓存"""
import queue
import threading
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


# ---------------------------------------------------------------------------
# 缩略图预热：同步/出图入库后后台生成 600px 缩略图。
#
# 画廊首屏按需生成时，一页 60 张冷缓存实测约 1.2s（6 并发），而且会跟列表请求
# 抢 PIL/磁盘。入库时提前铺好，用户切到画廊时直接命中文件缓存。
# 单守护线程 + 有界队列：不阻塞同步线程，文件再多也只按顺序慢慢铺。
# ---------------------------------------------------------------------------

_PREWARM_QUEUE: queue.Queue[tuple[str, str, str, int]] = queue.Queue(maxsize=500)
_PREWARM_LOCK = threading.Lock()
_PREWARM_WORKER: threading.Thread | None = None


def prewarm_thumbnail(
    filename: str,
    subfolder: str = "",
    img_type: str = "output",
    size: int = 600,
) -> None:
    """把一张图排进缩略图预热队列；不等待、不抛异常。"""
    global _PREWARM_WORKER
    if not filename or not settings.thumbnail_prewarm:
        return
    with _PREWARM_LOCK:
        if _PREWARM_WORKER is None or not _PREWARM_WORKER.is_alive():
            _PREWARM_WORKER = threading.Thread(
                target=_prewarm_loop, daemon=True, name="thumb-prewarm"
            )
            _PREWARM_WORKER.start()
    try:
        _PREWARM_QUEUE.put_nowait((filename, subfolder or "", img_type or "output", size))
    except queue.Full:
        # 预热是优化项，队列满了就放弃这一张，等下次同步再补
        pass


def _prewarm_loop() -> None:
    while True:
        filename, subfolder, img_type, size = _PREWARM_QUEUE.get()
        try:
            generate_thumbnail(filename, subfolder, img_type, size)
        except Exception:
            pass
        finally:
            _PREWARM_QUEUE.task_done()
