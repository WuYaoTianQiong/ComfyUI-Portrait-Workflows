"""图片资产底座：把 ComfyUI 图片的本地读取、远程回退与缺失态收敛到一处。

`AssetRef` 是 (filename, subfolder, img_type) 的语义封装；媒体路由只负责把
`AssetPayload` 转成 FastAPI 响应，不再各自实现「先本地、再代理、最后占位图」。
"""
from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

import httpx

from app.config import settings
from app.services.comfyui_client import get_sync_client
from app.services.paths import resolve_image_path
from app.services.thumbnail import generate_thumbnail

IMMUTABLE = "public, max-age=31536000, immutable"
SHORT_CACHE = "public, max-age=300"
NO_CACHE = "no-cache"


class AssetTimeoutError(Exception):
    """ComfyUI 代理超时；由路由映射成 504。"""


class AssetFetchError(Exception):
    """ComfyUI 代理失败；由路由映射成 500。"""


@dataclass(frozen=True)
class AssetRef:
    filename: str
    subfolder: str = ""
    img_type: str = "output"


@dataclass(frozen=True)
class AssetPayload:
    """三态响应：本地文件 / 内存字节 / 文件缺失。"""

    kind: str  # file | bytes | missing
    path: Path | None = None
    data: bytes | None = None
    media_type: str = "image/png"
    cache_control: str = NO_CACHE


def _remote_url(ref: AssetRef) -> str:
    return (
        f"{settings.comfyui_api}/view"
        f"?filename={quote(ref.filename)}"
        f"&subfolder={quote(ref.subfolder or '')}"
        f"&type={quote(ref.img_type or 'output')}"
    )


def fetch_remote(ref: AssetRef) -> tuple[bytes, str] | None:
    """从 ComfyUI `/view` 取原图；400/404 返回 None（文件确实没了）。"""
    try:
        resp = get_sync_client().get(_remote_url(ref), timeout=15)
        if resp.status_code in (400, 404):
            return None
        resp.raise_for_status()
        return resp.content, resp.headers.get("Content-Type", "image/png")
    except httpx.ConnectError:
        return None
    except httpx.TimeoutException as exc:
        raise AssetTimeoutError("获取图片超时（ComfyUI 响应过慢）") from exc
    except Exception as exc:
        raise AssetFetchError(f"获取图片失败: {exc}") from exc


def raw_payload(ref: AssetRef) -> AssetPayload:
    """原图：本地文件 → ComfyUI 代理 → 缺失占位。"""
    local = resolve_image_path(ref.filename, ref.subfolder, ref.img_type)
    if local is not None:
        media_type = mimetypes.guess_type(str(local))[0] or "image/png"
        return AssetPayload(kind="file", path=local, media_type=media_type)

    fetched = fetch_remote(ref)
    if fetched is None:
        return AssetPayload(kind="missing")
    data, media_type = fetched
    return AssetPayload(kind="bytes", data=data, media_type=media_type)


def thumbnail_payload(ref: AssetRef, size: int = 300) -> AssetPayload:
    """缩略图：本地缓存/生成 → 远程取图即时缩放 → 缺失占位。"""
    size = max(64, min(int(size or 300), 1024))
    thumb = generate_thumbnail(ref.filename, ref.subfolder, ref.img_type, size)
    if thumb is not None:
        return AssetPayload(
            kind="file", path=thumb, media_type="image/webp", cache_control=IMMUTABLE,
        )

    fetched = fetch_remote(ref)
    if fetched is None:
        return AssetPayload(kind="missing")
    data, _media_type = fetched
    try:
        from PIL import Image as PILImage

        with PILImage.open(BytesIO(data)) as img:
            img.thumbnail((size, size), PILImage.LANCZOS)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            buf = BytesIO()
            img.save(buf, "WEBP", quality=80)
            return AssetPayload(
                kind="bytes", data=buf.getvalue(),
                media_type="image/webp", cache_control=SHORT_CACHE,
            )
    except Exception:
        return AssetPayload(kind="missing")
