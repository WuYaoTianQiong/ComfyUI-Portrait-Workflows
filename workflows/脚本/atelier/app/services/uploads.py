"""参考图上传落盘（M3）。

上传的图片统一放在 `library_root/uploads/`，文件名由服务端按内容 sha1 前 12 位生成，
**不接受客户端指定目录**：任何带目录分隔符、盘符或控制字符的文件名直接拒绝。

三条硬规则：
- 扩展名白名单复用 `paths.IMAGE_EXTENSIONS`；
- HEIC/HEIF（含改名成 `.jpg` 的）按文件头识别后转 PNG，下游 ComfyUI 与浏览器都能直接读；
- 同一文件（sha1 相同）只落一份，重复上传返回 `dedup=true`。
"""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from pathlib import Path

from app.config import settings
from app.services import image_formats
from app.services.paths import IMAGE_EXTENSIONS

#: 单文件上限 25MB；超限由调用方（路由）在读取阶段截断，这里再做一次兜底。
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
#: Windows 保留设备名：`CON.png` 这类文件名在落盘/读取时会出怪问题。
_RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
_HEIF_EXTENSIONS = {".heic", ".heif"}


class UploadError(ValueError):
    """可读的上传错误：路由统一转成 400。"""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def uploads_dir(root: Path | None = None) -> Path:
    """上传目录：`library_root/uploads`，只允许服务端决定。

    `root` 为 library_root（测试可注入临时目录），不是 uploads 本身。
    """
    base = Path(root) if root is not None else settings.library_root
    return base / "uploads"


def safe_upload_name(filename: str) -> str:
    """只接受单段文件名；带路径/盘符/控制字符的一律拒绝。"""
    name = (filename or "").strip()
    if not name or name in (".", ".."):
        raise UploadError("文件名不能为空")
    if "/" in name or "\\" in name or ":" in name or _WINDOWS_DRIVE_RE.match(name):
        raise UploadError("文件名不能包含路径或盘符")
    if any(ord(ch) < 32 for ch in name):
        raise UploadError("文件名包含非法控制字符")
    if len(name) > 200:
        raise UploadError("文件名过长（上限 200 字符）")
    if name.split(".")[0].lower() in _RESERVED_NAMES:
        raise UploadError("文件名是系统保留名，请改名后再上传")
    return name


def _existing_upload(base: Path, digest: str) -> Path | None:
    """按 sha1 前缀找已落盘文件（大小写/扩展名不同也认同一份内容）。"""
    for candidate in base.glob(f"{digest}.*"):
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _probe_size(path: Path) -> tuple[int, int]:
    """读取真实宽高；解不开的坏图/非图片统一报 400。"""
    from PIL import Image, ImageOps

    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            width, height = ImageOps.exif_transpose(img).size
    except UploadError:
        raise
    except Exception as exc:
        raise UploadError(f"无法识别的图片文件：{exc or type(exc).__name__}") from None
    if not width or not height:
        raise UploadError("图片尺寸异常，无法读取宽高")
    return int(width), int(height)


def _store_bytes(dest: Path, temp: Path) -> None:
    """临时文件落盘后原子替换为目标文件，避免半截文件被下游读到。"""
    try:
        os.replace(temp, dest)
    except OSError as exc:
        raise UploadError(f"保存图片失败：{exc}") from None


def save_upload(filename: str, data: bytes, root: Path | None = None) -> dict:
    """保存一张上传图，返回 `{path, name, width, height, bytes, dedup}`。

    `root` 仅供测试注入；生产固定 `settings.library_root`。
    """
    name = safe_upload_name(filename)
    if not data:
        raise UploadError("上传内容为空")
    if len(data) > MAX_UPLOAD_BYTES:
        size_mb = len(data) / (1024 * 1024)
        raise UploadError(f"文件超过 25MB 上限（当前 {size_mb:.1f}MB）")

    suffix = Path(name).suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        allowed = " ".join(sorted(ext.lstrip(".") for ext in IMAGE_EXTENSIONS))
        raise UploadError(f"不支持的文件类型 {suffix or '（无扩展名）'}，仅接受：{allowed}")

    base = uploads_dir(root)
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise UploadError(f"上传目录不可用：{exc}") from None

    digest = hashlib.sha1(data).hexdigest()[:12]
    existing = _existing_upload(base, digest)
    if existing is not None:
        try:
            width, height = _probe_size(existing)
            size = existing.stat().st_size
        except OSError as exc:
            raise UploadError(f"读取已存图片失败：{exc}") from None
        return {
            "path": str(existing),
            "name": name,
            "width": width,
            "height": height,
            "bytes": size,
            "dedup": True,
        }

    temp = base / f".incoming-{uuid.uuid4().hex}"
    try:
        temp.write_bytes(data)
        # 以**文件头**为准，扩展名只是提示：`.heic` 里装的可能是 PNG/JPEG（下载改名很常见），
        # 这时按 HEIC 强行解码只会报"解码失败"，反而把好文件判死。
        if image_formats.is_heif(temp):
            dest = base / f"{digest}.png"
            try:
                image_formats.convert_heif_to_png(temp, dest)
            except RuntimeError as exc:
                raise UploadError(str(exc)) from None
            except Exception as exc:
                raise UploadError(f"HEIC/HEIF 解码失败：{exc or type(exc).__name__}") from None
        elif suffix in _HEIF_EXTENSIONS:
            # 扩展名是 HEIC 但内容不是：按真实内容统一转成 PNG，避免下游按扩展名解错
            dest = base / f"{digest}.png"
            try:
                from PIL import Image  # 与 _probe_size 一致：Pillow 按需导入

                with Image.open(temp) as img:
                    img.convert("RGBA").save(dest, "PNG")
            except Exception as exc:
                # 内容既不是 HEIC 又解不开：给出"装解码器"的提示，避免用户对着 .heic 干瞪眼
                hint = (
                    ""
                    if image_formats.heif_available()
                    else "；若文件确实是 HEIC/HEIF，需安装 pillow-heif"
                )
                raise UploadError(f"图片解码失败：{exc or type(exc).__name__}{hint}") from None
        else:
            dest = base / f"{digest}{suffix}"
            _store_bytes(dest, temp)
        try:
            width, height = _probe_size(dest)
        except UploadError:
            # 落盘后才发现解不开：把刚写入的文件删掉，别留下坏图占位
            try:
                dest.unlink()
            except OSError:
                pass
            raise
        size = dest.stat().st_size
    except OSError as exc:
        raise UploadError(f"保存图片失败：{exc}") from None
    finally:
        try:
            if temp.exists():
                temp.unlink()
        except OSError:
            pass

    return {
        "path": str(dest),
        "name": name,
        "width": width,
        "height": height,
        "bytes": size,
        "dedup": False,
    }