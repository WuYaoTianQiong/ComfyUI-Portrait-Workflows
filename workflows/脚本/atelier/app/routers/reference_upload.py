"""AI 参考图库 · 上传参考图（M3）。

落盘目录固定为 `data_dir/uploads`（默认 `脚本/atelier/data/uploads`，2026-11-06 归一），文件名由服务端按 sha1 生成，
不接受客户端指定目录；具体落盘规则见 `app/services/uploads.py`。

端点：
- POST /api/reference/uploads（multipart，字段名 `file`）
"""
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.services import uploads

router = APIRouter(tags=["参考图库上传"])


class UploadedReference(BaseModel):
    path: str
    name: str
    width: int
    height: int
    bytes: int
    dedup: bool = False



@router.post("/reference/uploads", response_model=UploadedReference)
async def upload_reference(file: UploadFile = File(...)):
    """接收单张参考图并落盘；同内容重复上传返回 `dedup=true`。"""
    data = await file.read(uploads.MAX_UPLOAD_BYTES + 1)
    if len(data) > uploads.MAX_UPLOAD_BYTES:
        raise HTTPException(400, "文件超过 25MB 上限")

    try:
        # 落盘 + 图片校验是同步 IO（HEIC 解码尤其重），放到线程池里避免阻塞事件循环
        result = await run_in_threadpool(
            uploads.save_upload,
            file.filename or "",
            data,
        )
    except uploads.UploadError as exc:
        raise HTTPException(exc.status_code, exc.message) from None
    return result