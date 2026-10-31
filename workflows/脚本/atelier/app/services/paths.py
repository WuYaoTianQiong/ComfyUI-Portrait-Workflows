"""路径与占位响应。

从原 `helpers.py` 拆出（那个模块是"什么都往里塞"的杂物间）：
- Windows 跨卷 junction 的解析（`WinError 448` 的唯一绕行点）
- 图片在 ComfyUI 目录下的定位（三处重复实现合并为 `resolve_image_path`）
- 图片访问 URL 与「文件缺失」占位图
"""
import os
from pathlib import Path
from urllib.parse import quote

from app.config import settings


def _resolve_if_reparse(p: Path) -> Path:
    """Windows 跨卷 junction/symlink 会被 Python 的 exists()/stat()/realpath
    判定为"不受信任的装入点"(WinError 448/22)，导致缩略图与本地图片代理 404。

    若路径本身是重解析点（junction），用 os.readlink 解析到真实目标后再访问，
    彻底绕开 junction 上的信任校验；普通目录则原样返回。
    """
    try:
        target = os.readlink(p)
        if target:
            return Path(target)
    except (OSError, ValueError):
        pass
    return p


def image_base_dir(img_type: str) -> Path:
    """按 img_type 取 ComfyUI 的 input/output 根目录（已解析重解析点）。"""
    name = "input" if img_type == "input" else "output"
    return _resolve_if_reparse(settings.comfyui_root / name)


def resolve_image_path(filename: str, subfolder: str, img_type: str) -> Path | None:
    """把 (filename, subfolder, type) 解析成本地真实文件路径；不存在返回 None。

    subfolder 可能逐层都是 junction（如 image/2026-07-04），必须逐段解析，
    否则跨卷 junction 上的 exists()/stat() 会抛 WinError 448，被误判成"文件缺失"。
    """
    if not filename:
        return None
    cur = image_base_dir(img_type)
    if subfolder:
        for part in subfolder.replace("\\", "/").split("/"):
            if not part:
                continue
            cur = _resolve_if_reparse(cur / part)
    img_path = cur / filename
    try:
        return img_path if img_path.exists() else None
    except OSError:
        return None


def build_view_url(filename: str, subfolder: str, img_type: str) -> str:
    """构建图片访问 URL（始终走 /api/image，确保统一的 Cache-Control 策略，
    避免静态文件路径缺失缓存控制导致浏览器旧缓存与新文件内容不一致）"""
    return (
        f"/api/image"
        f"?filename={quote(filename)}"
        f"&subfolder={quote(subfolder or '')}"
        f"&type={quote(img_type or 'output')}"
    )


# 「文件缺失」占位图。
#
# 原来是一个静态文件（static/img-missing.svg），S2-7 删除旧前端目录时被一起删掉，
# 结果缺失图片的请求直接 500。改成内联 SVG：不再依赖任何外部文件，
# 删目录、换部署方式都不会再影响它。
MISSING_IMAGE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300" viewBox="0 0 300 300">
<rect width="300" height="300" fill="#23232e"/>
<g fill="none" stroke="#5b5b70" stroke-width="3">
<rect x="96" y="104" width="108" height="84" rx="6"/>
<path d="M96 168l30-28 26 24 20-18 32 30"/>
</g>
<text x="150" y="222" text-anchor="middle" fill="#8b8b9e" font-size="15" font-family="sans-serif">文件缺失</text>
<text x="150" y="242" text-anchor="middle" fill="#63637a" font-size="12" font-family="sans-serif">已被删除或移动</text>
</svg>"""


def missing_image_response():
    """返回「文件缺失」占位图（HTTP 200），而不是 404。

    历史库里只要有一批记录对应的文件被手动删掉，`<img>` 就会每张刷一条
    404，控制台噪音很大；而 404 在前端也只能显示裂图，信息量还不如占位图上
    写着的"文件缺失/已被删除"。用 no-store，保证文件恢复后立刻能取到真图。
    """
    from fastapi.responses import Response

    return Response(
        content=MISSING_IMAGE_SVG,
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )
