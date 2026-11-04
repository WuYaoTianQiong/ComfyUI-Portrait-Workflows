"""AI 参考图库 · 上传参考图（M3）。

落盘目录固定为 `library_root/uploads`，文件名由服务端按 sha1 生成，
不接受客户端指定目录；具体实现在后续会话补齐。
"""
from fastapi import APIRouter

router = APIRouter(tags=["参考图库上传"])


@router.get("/reference/ping")
def ping_reference_upload():
    return {"ok": True, "router": "reference_upload"}