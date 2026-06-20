"""缩略图接口"""
from fastapi import APIRouter, Query, Response
from fastapi.responses import FileResponse, JSONResponse

from services.thumbnail import generate_thumbnail

router = APIRouter(tags=["缩略图"])


@router.get("/thumbnail")
def get_thumbnail(
    filename: str = Query(...),
    subfolder: str = Query(""),
    type: str = Query("output"),
    size: int = Query(300),
):
    """返回图片缩略图（WEBP 格式，缓存到本地）"""
    thumb_path = generate_thumbnail(filename, subfolder, type, size)
    if thumb_path is None or not thumb_path.exists():
        return JSONResponse(status_code=404, content={"error": "图片不存在"})
    return FileResponse(str(thumb_path), media_type="image/webp")
