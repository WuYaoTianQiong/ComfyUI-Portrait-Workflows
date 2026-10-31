"""图片与缩略图服务（从 `comfyui.py` 拆出）。

`/api/image`、`/api/thumbnail` 服务的是画廊/工作台对**任意历史图片**的读取
（本地直读 → 代理 ComfyUI → 代理后落盘），与"往 ComfyUI 提交出图任务"无关，
所以不该待在那个已经 700 行的 `comfyui.py` 里。URL 保持不变。
"""
import mimetypes
import shutil
from io import BytesIO
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from PIL import Image as PILImage

from app.config import settings
from app.services.paths import image_base_dir, missing_image_response, resolve_image_path
from app.services.thumbnail import generate_thumbnail

router = APIRouter(tags=["图片与缩略图"])

COMFYUI_API = settings.comfyui_api


@router.get("/image")
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


@router.get("/thumbnail")
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
    # （与 /api/image 一致，解决历史图片已不在本地磁盘时缩略图裂图的问题）
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


@router.post("/thumbnail/clear")
def clear_thumbnail_cache():
    """清空所有缩略图缓存文件。下次访问时自动按新缓存键重新生成。"""
    td = settings.thumbnail_dir
    count = 0
    if td.exists():
        count = len(list(td.glob("*.webp")))
        shutil.rmtree(td)
        td.mkdir(parents=True, exist_ok=True)
    return {"success": True, "deleted": count}
