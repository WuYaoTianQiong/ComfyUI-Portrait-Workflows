"""媒体读取 —— 图片/缩略图服务 + 本地文件夹浏览。

两部分都是"把一个媒体文件读出来给前端"，所以同属一个资源文件：
  · `/api/media/*`    画廊/工作台对**任意历史图片**的读取（本地直读 → 代理 ComfyUI → 落盘）
  · `/api/browser/*`  磁盘任意目录的列表与缩略图（图像编辑页选素材用）

P3 之前前者是裸动词 `/api/media/image`、`/api/media/thumbnail`，后者是 `/api/browser/*`
（`routers/fsbrowse.py`，已并入本文件）。

文件浏览只监听 127.0.0.1，供本机使用。按需求不做路径白名单（要能"自由打开想要的
文件夹"），但所有路径都必须真实存在，异常一律转成 4xx，避免暴露成 500 堆栈。
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from PIL import Image as PILImage, ImageOps

from app.config import settings
from app.services import assets
from app.services.asset_store import AssetStore, ComfyAssetRef
from app.services.image_formats import is_heif
from app.services.paths import (
    IMAGE_EXTENSIONS,
    _resolve_if_reparse,
    is_safe_image_ref,
    missing_image_response,
    resolve_local_image,
)

router = APIRouter(tags=["媒体与文件浏览"])

IMAGE_EXT = IMAGE_EXTENSIONS
MAX_ITEMS = 800          # 单个目录最多返回多少个子目录 / 图片，避免超大目录把前端卡死
ASSETS = AssetStore()


# ---------------------------------------------------------------------------
# /api/media/* —— 历史图片与缩略图
# ---------------------------------------------------------------------------


def _asset_response(payload: assets.AssetPayload):
    if payload.kind == "missing":
        return missing_image_response()
    headers = {"Cache-Control": payload.cache_control}
    if payload.kind == "file" and payload.path is not None:
        return FileResponse(
            str(payload.path), media_type=payload.media_type, headers=headers,
        )
    return StreamingResponse(
        iter([payload.data or b""]), media_type=payload.media_type, headers=headers,
    )


def _load_asset(loader):
    try:
        return loader()
    except assets.AssetTimeoutError as e:
        raise HTTPException(504, str(e)) from None
    except assets.AssetFetchError as e:
        raise HTTPException(500, str(e)) from None


@router.get("/media/image")
def proxy_image(
    filename: str = Query(...),
    subfolder: str = Query(""),
    type: str = Query("output"),
):
    if not is_safe_image_ref(filename, subfolder, type):
        raise HTTPException(400, "非法的图片路径")
    payload = _load_asset(
        lambda: ASSETS.resolve(ComfyAssetRef(filename, subfolder, type))
    )
    return _asset_response(payload)


@router.get("/media/thumbnail")
def serve_thumbnail(
    filename: str = Query(...),
    subfolder: str = Query(""),
    type: str = Query("output"),
    size: int = Query(300),
    v: str = Query(None),  # cache-busting 版本号，仅用于生成不同 URL，不参与处理逻辑
):
    if not is_safe_image_ref(filename, subfolder, type):
        raise HTTPException(400, "非法的图片路径")
    payload = _load_asset(
        lambda: ASSETS.thumbnail(ComfyAssetRef(filename, subfolder, type), size)
    )
    return _asset_response(payload)


@router.post("/media/thumbnail/clear")
def clear_thumbnail_cache():
    """清空所有缩略图缓存文件。下次访问时自动按新缓存键重新生成。"""
    td = settings.thumbnail_dir
    count = 0
    if td.exists():
        # 只删缩略图本身；rmtree 会连带清掉同目录下的浏览器缓存。
        for path in td.glob("*.webp"):
            path.unlink(missing_ok=True)
            count += 1
    return {"success": True, "deleted": count}


# ---------------------------------------------------------------------------
# /api/browser/* —— 本地文件夹浏览（原 routers/fsbrowse.py）
# ---------------------------------------------------------------------------


def _natural(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def _list_drives() -> list[str]:
    try:
        import ctypes

        mask = ctypes.windll.kernel32.GetLogicalDrives()
        return [f"{c}:\\" for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ") if mask & (1 << i)]
    except Exception:
        return []


def _roots() -> list[dict]:
    """快速跳转入口：ComfyUI 常用目录 + 项目根 + 用户目录 + 所有盘符"""
    out: list[dict] = []
    candidates = [
        ("ComfyUI/output", settings.output_dir),
        ("ComfyUI/input", settings.input_dir),
        ("ComfyUI/temp", settings.temp_dir),
        ("工作流目录", settings.library_root),
    ]
    for name, p in candidates:
        try:
            if p.is_dir():
                out.append({"name": name, "path": str(p)})
        except OSError:
            continue
    home = Path.home()
    try:
        if home.is_dir():
            out.append({"name": "用户目录", "path": str(home)})
    except OSError:
        pass
    for d in _list_drives():
        out.append({"name": d, "path": d})
    return out


@router.get("/browser/list")
def browser_list(path: str = Query("")):
    """列出目录内容。path 为空时返回盘符列表（作为浏览起点）。"""
    roots = _roots()
    if not path.strip():
        return {
            "path": "", "parent": "", "roots": roots, "truncated": False,
            "dirs": [{"name": d, "path": d} for d in _list_drives()],
            "images": [],
        }

    raw = Path(path)
    try:
        base = _resolve_if_reparse(raw) if raw.is_dir() else raw
    except OSError:
        base = raw
    # os.readlink 解析 junction 后返回的是 \\?\F:\... 形式，对用户毫无意义，
    # 去掉前缀再对外展示（否则路径栏里会显示 \\?\F:\ComfyUI_Migration\input）。
    base = Path(str(base).replace("\\\\?\\", ""))
    if not base.is_dir():
        raise HTTPException(400, f"不是有效目录: {path}")

    dirs: list[dict] = []
    images: list[dict] = []
    truncated = False
    try:
        with os.scandir(base) as it:
            for entry in it:
                try:
                    if entry.is_dir():
                        if len(dirs) < MAX_ITEMS:
                            dirs.append({"name": entry.name,
                                         "path": os.path.join(str(base), entry.name)})
                        else:
                            truncated = True
                    elif entry.is_file() and Path(entry.name).suffix.lower() in IMAGE_EXT:
                        if len(images) < MAX_ITEMS:
                            st = entry.stat()
                            images.append({"name": entry.name,
                                           "path": os.path.join(str(base), entry.name),
                                           "size": st.st_size, "mtime": int(st.st_mtime)})
                        else:
                            truncated = True
                except OSError:
                    continue
    except OSError as e:
        raise HTTPException(400, f"读取目录失败: {e}")

    dirs.sort(key=lambda d: _natural(d["name"]))
    images.sort(key=lambda i: _natural(i["name"]))
    return {
        "path": str(base),
        "parent": str(base.parent) if base.parent != base else "",
        "dirs": dirs, "images": images, "roots": roots, "truncated": truncated,
    }


def _thumb_cache_path(p: Path, size: int) -> Path:
    try:
        mtime = int(p.stat().st_mtime)
    except OSError:
        mtime = 0
    key = hashlib.md5(f"{p}|{mtime}|{size}".encode("utf-8")).hexdigest()
    return settings.thumbnail_dir / f"fs_{key}.webp"


@router.get("/browser/thumb")
def browser_thumb(path: str = Query(...), size: int = Query(300)):
    """任意图片文件的缩略图（带磁盘缓存，按 路径+mtime+尺寸 做键）"""
    p = resolve_local_image(path)
    if p is None:
        return missing_image_response()
    size = max(64, min(int(size), 1024))
    cache = _thumb_cache_path(p, size)
    if not cache.is_file():
        try:
            settings.thumbnail_dir.mkdir(parents=True, exist_ok=True)
            with PILImage.open(p) as im:
                im.thumbnail((size, size), PILImage.LANCZOS)
                if im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")
                im.save(cache, "WEBP", quality=80)
        except Exception:
            # 坏图/不支持格式：给占位图，别让网格里出现裂图
            return missing_image_response()
    return FileResponse(str(cache), media_type="image/webp",
                        headers={"Cache-Control": "no-cache"})


def _preview_cache_path(p: Path) -> Path:
    """HEIC 预览缓存：浏览器不能直接显示 HEIC，转成同尺寸 WebP 后缓存。"""
    try:
        mtime = int(p.stat().st_mtime)
    except OSError:
        mtime = 0
    key = hashlib.md5(f"{p}|{mtime}|preview".encode("utf-8")).hexdigest()
    return settings.thumbnail_dir / f"view_{key}.webp"


@router.get("/browser/image")
def browser_image(path: str = Query(...)):
    """任意图片文件的原图（只接受图片扩展名，避免变成任意文件读取）。

    HEIC/HEIF（包括改名成 .jpg 的）浏览器无法直接渲染，这里返回转换后的 WebP。
    """
    p = resolve_local_image(path)
    if p is None:
        return missing_image_response()
    if is_heif(p):
        cache = _preview_cache_path(p)
        if not cache.is_file():
            try:
                settings.thumbnail_dir.mkdir(parents=True, exist_ok=True)
                with PILImage.open(p) as raw:
                    image = ImageOps.exif_transpose(raw)
                    if image.mode not in ("RGB", "RGBA", "L"):
                        image = image.convert("RGB")
                    image.save(cache, "WEBP", quality=90)
            except Exception:
                return missing_image_response()
        return FileResponse(str(cache), media_type="image/webp",
                            headers={"Cache-Control": "no-cache"})
    return FileResponse(str(p), headers={"Cache-Control": "no-cache"})
