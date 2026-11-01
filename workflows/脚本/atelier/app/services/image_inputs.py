"""把外部素材交给 ComfyUI 前的本地预处理（与路由无关，重试也要复用）。"""
from __future__ import annotations

import hashlib
from pathlib import Path


def dest_name(src: dict) -> str:
    """拷进 ComfyUI input 目录时用的稳定文件名：同一条素材只拷一份，不同素材不撞名。"""
    h = hashlib.sha1(str(src["path"]).lower().encode("utf-8")).hexdigest()[:10]
    return f"atelier_fs_{h}_{src['name']}"


def compose_masked_target(target_path: Path, mask_path: Path, dest_dir: Path) -> Path:
    """把遮罩烘焙进目标图 alpha 通道，返回可直接注入 LoadImage 的 PNG。

    工作流里 LoadImage 的 MASK = 1 - alpha，因此「要改的区域」alpha 必须为 0。
    · 遮罩图真的带透明通道 → 透明区 = 要改
    · 否则按亮度 → 白色 = 要改（兼容最常见的黑白遮罩图）
    其余区域 alpha=255，工作流的归约链会原样保留这些像素。
    """
    from PIL import Image as PILImage, ImageOps

    with PILImage.open(target_path) as raw:
        image = ImageOps.exif_transpose(raw).convert("RGB")

    with PILImage.open(mask_path) as raw_mask:
        mask = ImageOps.exif_transpose(raw_mask)
        alpha = mask.convert("RGBA").getchannel("A")
        if alpha.getextrema()[0] < 255:
            repaint = ImageOps.invert(alpha)
        else:
            repaint = mask.convert("L")
        repaint = repaint.resize(image.size, PILImage.Resampling.BILINEAR)

    output = image.convert("RGBA")
    output.putalpha(ImageOps.invert(repaint))

    digest = hashlib.sha1(
        f"{target_path}|{mask_path}|{target_path.stat().st_mtime}|{mask_path.stat().st_mtime}".encode("utf-8")
    ).hexdigest()[:12]
    dest = Path(dest_dir) / f"atelier_edit_{digest}.png"
    output.save(dest, "PNG")
    return dest
