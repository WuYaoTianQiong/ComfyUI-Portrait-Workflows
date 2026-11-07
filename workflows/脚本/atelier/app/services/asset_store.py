"""统一资产寻址：ComfyUI 出图 / 参考库 / 上传图 / 外链缓存。

`assets.py` 只认识 ComfyUI 的 (filename, subfolder, type)。本模块把另外三类
资产也纳入同一套 `resolve / path / thumbnail / delete` 语义，路由不再各自拼
路径、判扩展名、猜缓存目录。
"""
from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from app.services import assets, uploads
from app.services.assets import (
    NO_CACHE,
    SHORT_CACHE,
    AssetPayload,
    AssetRef as ComfyAssetRef,
)
from app.services.paths import resolve_image_path


@dataclass(frozen=True)
class LibraryAssetRef:
    library: str
    item_id: str
    kind: str = "thumb"


@dataclass(frozen=True)
class UploadAssetRef:
    path: str


@dataclass(frozen=True)
class RemoteAssetRef:
    library: str
    item_id: str
    kind: str
    url: str


AssetRef = ComfyAssetRef | LibraryAssetRef | UploadAssetRef | RemoteAssetRef


def _file_payload(path: Path, cache_control: str = NO_CACHE) -> AssetPayload:
    media_type = mimetypes.guess_type(str(path))[0] or "image/png"
    return AssetPayload(
        kind="file", path=path, media_type=media_type, cache_control=cache_control,
    )


def _thumbnail_bytes(path: Path, size: int) -> AssetPayload:
    try:
        from PIL import Image as PILImage

        with PILImage.open(path) as img:
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


class AssetStore:
    """所有资产读取的唯一入口；写入仍由各域自己的服务负责。"""

    def path(self, ref: AssetRef) -> Path | None:
        if isinstance(ref, ComfyAssetRef):
            return resolve_image_path(ref.filename, ref.subfolder, ref.img_type)
        if isinstance(ref, LibraryAssetRef):
            from app.services import reference_library

            return reference_library.resolve_image(ref.library, ref.item_id, ref.kind)
        if isinstance(ref, UploadAssetRef):
            return uploads.resolve_upload(ref.path)
        return None

    def resolve(self, ref: AssetRef) -> AssetPayload:
        if isinstance(ref, ComfyAssetRef):
            return assets.raw_payload(ref)
        if isinstance(ref, RemoteAssetRef):
            # 外链必须异步下载；同步接口只报告缺失，调用方走 remote cache。
            return AssetPayload(kind="missing")
        try:
            path = self.path(ref)
        except Exception:
            return AssetPayload(kind="missing")
        return _file_payload(path) if path else AssetPayload(kind="missing")

    def thumbnail(self, ref: AssetRef, size: int = 300) -> AssetPayload:
        size = max(64, min(int(size or 300), 1024))
        if isinstance(ref, ComfyAssetRef):
            return assets.thumbnail_payload(ref, size)
        if isinstance(ref, RemoteAssetRef):
            return AssetPayload(kind="missing")
        try:
            path = self.path(ref)
        except Exception:
            return AssetPayload(kind="missing")
        if path is None:
            return AssetPayload(kind="missing")
        if isinstance(ref, LibraryAssetRef):
            # 参考库的 thumb 已经是服务端预生成的缩略图，直接用。
            return _file_payload(path)
        return _thumbnail_bytes(path, size)

    def exists(self, ref: AssetRef) -> bool:
        try:
            path = self.path(ref)
        except Exception:
            return False
        return bool(path and path.is_file())

    def delete_upload(self, ref: UploadAssetRef) -> bool:
        """只允许删除 uploads 目录内的受管文件。"""
        path = uploads.resolve_upload(ref.path)
        if path is None:
            return False
        try:
            path.unlink()
            return True
        except OSError:
            return False


__all__ = [
    "AssetRef",
    "AssetStore",
    "ComfyAssetRef",
    "LibraryAssetRef",
    "UploadAssetRef",
    "RemoteAssetRef",
]
