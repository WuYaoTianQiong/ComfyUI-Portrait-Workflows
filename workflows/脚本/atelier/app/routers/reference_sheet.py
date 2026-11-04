"""AI 参考图库 · 参考板导出（M5）。

端点：
- GET /api/reference/sheet?pose=&costume=&portrait=&extra=&labels=1

返回 1800×1200 PNG。路径解析全部复用 `reference_library` 的只读接口
（同一套 root 校验与 NSFW 过滤）；`remote` 条目、缺图、非法附加图一律 400。
产物只用于下载/带走，不写 `gen_history`。
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.services import reference_sheet

router = APIRouter(tags=["参考图库参考板"])

SHEET_FILENAME = "reference-sheet.png"


@router.get("/reference/ping")
def ping_reference_sheet():
    return {"ok": True, "router": "reference_sheet"}


@router.get("/reference/sheet")
def get_reference_sheet(
    pose: str = Query("", description="姿势库条目 id"),
    costume: str = Query("", description="服装库条目 id"),
    portrait: str = Query("", description="人像库条目 id"),
    extra: str = Query("", description="第 4 张上传图路径（必须是 uploads 目录内的文件）"),
    labels: bool = Query(True, description="1 画「图N · 名称」标题条，0 纯图拼接"),
):
    try:
        png = reference_sheet.render_png(
            pose=pose,
            costume=costume,
            portrait=portrait,
            extra=extra,
            labels=labels,
        )
    except reference_sheet.SheetError as exc:
        raise HTTPException(exc.status_code, exc.message) from None

    return Response(
        content=png,
        media_type="image/png",
        headers={
            "Content-Disposition": f'inline; filename="{SHEET_FILENAME}"',
            # 同一组合换图后不要命中浏览器旧缓存
            "Cache-Control": "no-store",
        },
    )