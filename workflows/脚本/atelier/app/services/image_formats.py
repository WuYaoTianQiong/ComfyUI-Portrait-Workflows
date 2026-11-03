"""图片真实格式识别与 HEIC/HEIF 支持。

项目原来的判断只看扩展名，于是「把 .heic 改名成 .jpg」能混进来，但缩略图、
元数据和 ComfyUI 都会在解码阶段失败。这里做两件事：

- 首次 import 时注册 Pillow 的 HEIF 解码器（依赖 `pillow-heif`，未装则降级）；
- 通过文件头（ISO BMFF 的 `ftyp` 品牌）识别 HEIC/HEIF，不依赖扩展名。

投喂 ComfyUI 前统一把 HEIC 转成 PNG，避免依赖 ComfyUI 本身是否装了 HEIC 插件。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

_HEIF_AVAILABLE = False
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    _HEIF_AVAILABLE = True
except Exception:  # pragma: no cover - 未安装依赖时走降级分支
    pass

#: pillow-heif 报告的格式名
HEIF_FORMATS = {"HEIF", "HEIC", "AVIF"}
#: ISO BMFF 里常见的 HEIC/HEIF 主品牌
_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"avif", b"avis"}


def heif_available() -> bool:
    """当前环境是否装了 HEIC 解码器。"""
    return _HEIF_AVAILABLE


def is_heif(path: str | Path) -> bool:
    """按文件头判断是否是 HEIC/HEIF（扩展名改成 .jpg 也能识别）。"""
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError:
        return False
    # ISO BMFF: [4字节长度][ftyp][主品牌]
    return len(head) >= 12 and head[4:8] == b"ftyp" and head[8:12] in _HEIF_BRANDS


def convert_heif_to_png(source: str | Path, dest: str | Path) -> None:
    """把 HEIC/HEIF 转成 PNG，并按 EXIF 方向摆正。"""
    if not _HEIF_AVAILABLE:
        raise RuntimeError("缺少 pillow-heif，无法解码 HEIC/HEIF")
    with Image.open(source) as raw:
        image = ImageOps.exif_transpose(raw)
        if image.mode not in ("RGB", "RGBA", "L"):
            image = image.convert("RGB")
        image.save(dest, "PNG")
