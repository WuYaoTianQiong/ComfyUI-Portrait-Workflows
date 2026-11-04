"""AI 参考图库 · 只读浏览（M1）。

参考库是只读素材层：上游 `ai-pose-gallery-zh` 的 JSON 与图片不复制、不改写，
这里只负责把四份 JSON 适配成 atelier 的 DTO 与分页响应。
"""
from fastapi import APIRouter

router = APIRouter(tags=["参考图库"])


@router.get("/reference/ping")
def ping_reference_library():
    return {"ok": True, "router": "reference_library"}