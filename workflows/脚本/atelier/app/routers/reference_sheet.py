"""AI 参考图库 · 参考板导出（M5）。

PIL 拼成 1800×1200 的 PNG，只做导出、不作为出图输入；
具体实现在后续会话补齐。
"""
from fastapi import APIRouter

router = APIRouter(tags=["参考图库参考板"])


@router.get("/reference/ping")
def ping_reference_sheet():
    return {"ok": True, "router": "reference_sheet"}