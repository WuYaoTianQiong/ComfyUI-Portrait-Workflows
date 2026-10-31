"""本地文件夹浏览 —— 让「批量换脸」工作台可以自由打开任意文件夹选图。

只监听 127.0.0.1，供本机使用。按需求不做路径白名单（要能"自由打开想要的文件夹"），
但所有路径都必须真实存在，异常一律转成 4xx，避免暴露成 500 堆栈。
"""
from __future__ import annotations

import hashlib
import os
import re
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from PIL import Image

from config import settings
from services.helpers import _resolve_if_reparse, missing_image_response

router = APIRouter(tags=["文件浏览"])

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
MAX_ITEMS = 800          # 单个目录最多返回多少个子目录 / 图片，避免超大目录把前端卡死


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
        ("工作流目录", settings.project_root),
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


@router.get("/fs/list")
def fs_list(path: str = Query("")):
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


@router.get("/fs/thumb")
def fs_thumb(path: str = Query(...), size: int = Query(300)):
    """任意图片文件的缩略图（带磁盘缓存，按 路径+mtime+尺寸 做键）"""
    p = Path(path)
    if not p.is_file():
        return missing_image_response()
    size = max(64, min(int(size), 1024))
    cache = _thumb_cache_path(p, size)
    if not cache.is_file():
        try:
            settings.thumbnail_dir.mkdir(parents=True, exist_ok=True)
            with Image.open(p) as im:
                im.thumbnail((size, size), Image.LANCZOS)
                if im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")
                im.save(cache, "WEBP", quality=80)
        except Exception:
            # 坏图/不支持格式：给占位图，别让网格里出现裂图
            return missing_image_response()
    return FileResponse(str(cache), media_type="image/webp",
                        headers={"Cache-Control": "no-cache"})


@router.get("/fs/image")
def fs_image(path: str = Query(...)):
    """任意图片文件的原图"""
    p = Path(path)
    if not p.is_file():
        return missing_image_response()
    return FileResponse(str(p), headers={"Cache-Control": "no-cache"})
