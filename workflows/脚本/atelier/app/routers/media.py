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
import mimetypes
import os
import re
import shutil
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from PIL import Image as PILImage

from app.config import settings
from app.services.paths import (
    _resolve_if_reparse,
    image_base_dir,
    missing_image_response,
    resolve_image_path,
)
from app.services.thumbnail import generate_thumbnail

router = APIRouter(tags=["媒体与文件浏览"])

COMFYUI_API = settings.comfyui_api

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
MAX_ITEMS = 800          # 单个目录最多返回多少个子目录 / 图片，避免超大目录把前端卡死


# ---------------------------------------------------------------------------
# /api/media/* —— 历史图片与缩略图
# ---------------------------------------------------------------------------


@router.get("/media/image")
def proxy_image(
    filename: str = Query(...),
    subfolder: str = Query(""),
    type: str = Query("output"),
):
    # 优先读本地文件（ComfyUI 离线也能用）
    local = resolve_image_path(filename, subfolder, type)
    if local:
        mt, _ = mimetypes.guess_type(str(local))
        return FileResponse(
            str(local),
            media_type=mt or "image/png",
            headers={"Cache-Control": "no-cache"},
        )

    # 本地没有，代理到 ComfyUI（带超时，避免阻塞整个服务）
    url = (
        f"{COMFYUI_API}/view"
        f"?filename={quote(filename)}"
        f"&subfolder={quote(subfolder)}"
        f"&type={quote(type)}"
    )
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(url)
            if resp.status_code in (400, 404):
                # 本地没有 + ComfyUI 也没有 = 文件真的没了 → 给占位图，不再刷 404
                return missing_image_response()
            resp.raise_for_status()
            content = resp.content
            media_type = resp.headers.get("Content-Type", "image/png")
    except httpx.ConnectError:
        # ComfyUI 没开，本地也没有这个文件 → 同样属于"取不到图"
        return missing_image_response()
    except httpx.TimeoutException:
        raise HTTPException(504, "获取图片超时（ComfyUI 响应过慢）")
    except Exception as e:
        raise HTTPException(500, f"获取图片失败: {e}")

    # 把代理回来的图片落盘到本地，下次直接走本地路径，不再代理
    _cache_proxied_image(filename, subfolder, type, content)

    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Cache-Control": "no-cache"},
    )


def _cache_proxied_image(filename: str, subfolder: str, img_type: str, content: bytes) -> None:
    """将代理获取到的图片保存到 ComfyUI 本地目录，便于后续直接读取。"""
    try:
        target_dir = image_base_dir(img_type) / (subfolder or "")
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / filename).write_bytes(content)
    except Exception:
        # 落盘失败不影响本次返回
        pass


def _fetch_remote_image(filename: str, subfolder: str, img_type: str) -> bytes | None:
    """从 ComfyUI /view 代理取回原图字节（带超时，失败返回 None）。"""
    url = (
        f"{COMFYUI_API}/view"
        f"?filename={quote(filename)}"
        f"&subfolder={quote(subfolder)}"
        f"&type={quote(img_type)}"
    )
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(url)
            if resp.status_code in (404, 400):
                return None
            resp.raise_for_status()
            return resp.content
    except (httpx.ConnectError, httpx.TimeoutException):
        return None
    except Exception:
        return None


@router.get("/media/thumbnail")
def serve_thumbnail(
    filename: str = Query(...),
    subfolder: str = Query(""),
    type: str = Query("output"),
    size: int = Query(300),
    v: str = Query(None),  # cache-busting 版本号，仅用于生成不同 URL，不参与处理逻辑
):
    thumb_path = generate_thumbnail(filename, subfolder, type, size)
    if thumb_path is not None:
        return FileResponse(
            str(thumb_path),
            media_type="image/webp",
            headers={"Cache-Control": "no-cache"},
        )

    # 本地原图不存在：回退到 ComfyUI 代理取图并即时生成缩略图
    # （与 /api/media/image 一致，解决历史图片已不在本地磁盘时缩略图裂图的问题）
    raw = _fetch_remote_image(filename, subfolder, type)
    if raw is None:
        # 文件确实没了：返回「文件缺失」占位图（200），避免画廊/工作台里刷一屏 404
        return missing_image_response()
    try:
        with PILImage.open(BytesIO(raw)) as img:
            img.thumbnail((size, size), PILImage.LANCZOS)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            buf = BytesIO()
            img.save(buf, "WEBP", quality=80)
            buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="image/webp",
            headers={"Cache-Control": "no-cache"},
        )
    except Exception:
        return missing_image_response()


@router.post("/media/thumbnail/clear")
def clear_thumbnail_cache():
    """清空所有缩略图缓存文件。下次访问时自动按新缓存键重新生成。"""
    td = settings.thumbnail_dir
    count = 0
    if td.exists():
        count = len(list(td.glob("*.webp")))
        shutil.rmtree(td)
        td.mkdir(parents=True, exist_ok=True)
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
        ("ComfyUI/output", settings.comfyui_root / "output"),
        ("ComfyUI/input", settings.comfyui_root / "input"),
        ("ComfyUI/temp", settings.comfyui_root / "temp"),
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
    p = Path(path)
    if not p.is_file():
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


@router.get("/browser/image")
def browser_image(path: str = Query(...)):
    """任意图片文件的原图"""
    p = Path(path)
    if not p.is_file():
        return missing_image_response()
    return FileResponse(str(p), headers={"Cache-Control": "no-cache"})
