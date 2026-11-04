"""AI 参考图库 · 只读浏览（M1）。

参考库是只读素材层：上游 `ai-pose-gallery-zh` 的 JSON 与图片不复制、不改写，
这里只负责把四份 JSON 适配成 atelier 的 DTO 与分页响应。

端点（§3.3）：
- GET /api/reference/libraries
- GET /api/reference/items
- GET /api/reference/items/{library}/{item_id}
- GET /api/reference/items/{library}/{item_id}/image?kind=thumb|image|depth
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field


from app.services import reference_library

router = APIRouter(tags=["参考图库"])


class ReferenceItem(BaseModel):
    id: str
    library: str
    name: str
    subtitle: str = ""
    group: str = ""
    facet: str = ""
    angle: str = ""
    tags: list[str] = Field(default_factory=list)
    keywords: str = ""
    thumb_url: str
    image_url: str
    depth_url: str | None = None
    hot: bool = False
    featured: bool = False
    nsfw: bool = False
    remote: bool = False


class ReferenceItemListResponse(BaseModel):
    items: list[ReferenceItem] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 60


class ReferenceFacetValue(BaseModel):
    value: str
    count: int


class ReferenceLibraryStats(BaseModel):
    library: str
    label: str
    total: int
    local: int
    remote: int
    #: NSFW 过滤后当前可见的条数（默认过滤敏感分类）
    visible: int
    available: bool
    groups: list[ReferenceFacetValue] = Field(default_factory=list)
    facets: list[ReferenceFacetValue] = Field(default_factory=list)
    angles: list[ReferenceFacetValue] = Field(default_factory=list)


class ReferenceLibraryListResponse(BaseModel):
    libraries: list[ReferenceLibraryStats] = Field(default_factory=list)


@router.get("/reference/ping")
def ping_reference_library():
    return {"ok": True, "router": "reference_library"}


@router.get("/reference/libraries", response_model=ReferenceLibraryListResponse)
def list_reference_libraries():
    return {"libraries": reference_library.library_stats()}


@router.get("/reference/items", response_model=ReferenceItemListResponse)
def list_reference_items(
    library: str = Query("pose", description="pose / costume / portrait / costume-anime"),
    search: str = Query("", description="直接匹配上游预拼好的「检索」串"),
    group: str = Query(""),
    facet: str = Query(""),
    angle: str = Query(""),
    nsfw: bool | None = Query(None, description="仅在 ATELIER_REFERENCE_ALLOW_NSFW=1 时生效"),
    page: int = Query(1),
    page_size: int = Query(0, description="0 表示使用 ATELIER_REFERENCE_PAGE_SIZE"),
):
    if library not in reference_library.LIBRARY_FILES:
        raise HTTPException(404, f"未知参考库：{library}")
    return reference_library.query_items(
        library=library,
        search=search,
        group=group,
        facet=facet,
        angle=angle,
        nsfw=nsfw,
        page=page,
        page_size=page_size or None,
    )


@router.get("/reference/items/{library}/{item_id}", response_model=ReferenceItem)
def get_reference_item(library: str, item_id: str):
    item = reference_library.get_item(library, item_id)
    if item is None:
        raise HTTPException(404, "参考条目不存在")
    return item


@router.get("/reference/items/{library}/{item_id}/image")
def get_reference_image(
    library: str,
    item_id: str,
    kind: str = Query("thumb", description="thumb / image / depth"),
):
    try:
        path = reference_library.resolve_image(library, item_id, kind)
    except reference_library.ReferenceImageError as exc:
        raise HTTPException(exc.status_code, exc.detail) from None
    return FileResponse(
        str(path),
        media_type=reference_library.media_type_for(path),
        headers={"Cache-Control": "no-cache"},
    )