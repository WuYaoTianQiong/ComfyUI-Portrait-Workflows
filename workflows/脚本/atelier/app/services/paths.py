"""路径与占位响应。

从原 `helpers.py` 拆出（那个模块是"什么都往里塞"的杂物间）：
- Windows 跨卷 junction 的解析（`WinError 448` 的唯一绕行点）
- 图片在 ComfyUI 目录下的定位（三处重复实现合并为 `resolve_image_path`）
- 图片访问 URL 与「文件缺失」占位图
"""
import os
import re
from pathlib import Path
from urllib.parse import quote

from app.config import settings

#: 允许经图片接口读取/浏览的扩展名。放在这里而不是 media.py，
#: 是为了让路径校验和目录浏览共用同一份白名单。
IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff",
    ".heic", ".heif",
}

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _relative_parts(raw: str) -> list[str] | None:
    """把用户提供的相对路径拆成安全片段；含穿越/绝对路径时返回 None。

    不做 realpath：Windows 跨卷 junction 上 realpath/exists 会抛 WinError 448。
    这里只做词法校验，junction 自身仍由 `_resolve_if_reparse` 逐段解析。
    """
    text = (raw or "").replace("\\", "/").strip()
    if not text:
        return []
    if text.startswith("/") or text.startswith("//") or _WINDOWS_DRIVE_RE.match(text):
        return None
    parts: list[str] = []
    for part in text.split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            return None
        if ":" in part or any(ord(ch) < 32 for ch in part):
            return None
        parts.append(part)
    return parts


def _safe_filename(filename: str) -> bool:
    """文件名必须是单段 basename，不能带目录、盘符或 NTFS 备用流。"""
    if not filename or filename in (".", ".."):
        return False
    if "/" in filename or "\\" in filename or ":" in filename:
        return False
    if _WINDOWS_DRIVE_RE.match(filename):
        return False
    return not any(ord(ch) < 32 for ch in filename)


def is_safe_image_ref(filename: str, subfolder: str = "", img_type: str = "output") -> bool:
    """校验 (filename, subfolder, img_type) 是否只能落在 ComfyUI 的 input/output/temp 内。"""
    if (img_type or "output") not in {"input", "output", "temp"}:
        return False
    if not _safe_filename(filename):
        return False
    return _relative_parts(subfolder) is not None


def resolve_local_image(path: str) -> Path | None:
    """浏览器选图用的本地绝对路径：只允许真实存在的图片文件。"""
    if not path:
        return None
    try:
        p = Path(path)
        if not p.is_absolute() or p.suffix.lower() not in IMAGE_EXTENSIONS:
            return None
        return p if p.is_file() else None
    except OSError:
        return None


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
    """按 img_type 取 ComfyUI 的 input/output/temp 根目录（已解析重解析点）。"""
    if img_type == "input":
        base = settings.input_dir
    elif img_type == "temp":
        base = settings.temp_dir
    else:
        base = settings.output_dir
    return _resolve_if_reparse(base)


def resolve_image_path(filename: str, subfolder: str, img_type: str) -> Path | None:
    """把 (filename, subfolder, type) 解析成本地真实文件路径；不存在或越界返回 None。

    subfolder 可能逐层都是 junction（如 image/2026-07-04），必须逐段解析，
    否则跨卷 junction 上的 exists()/stat() 会抛 WinError 448，被误判成"文件缺失"。
    """
    if not is_safe_image_ref(filename, subfolder, img_type):
        return None
    cur = image_base_dir(img_type)
    for part in _relative_parts(subfolder) or []:
        cur = _resolve_if_reparse(cur / part)
    img_path = cur / filename
    try:
        return img_path if img_path.exists() else None
    except OSError:
        return None


def build_view_url(filename: str, subfolder: str, img_type: str) -> str:
    """构建图片访问 URL（始终走 /api/media/image，确保统一的 Cache-Control 策略，
    避免静态文件路径缺失缓存控制导致浏览器旧缓存与新文件内容不一致）"""
    return (
        f"/api/media/image"
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
