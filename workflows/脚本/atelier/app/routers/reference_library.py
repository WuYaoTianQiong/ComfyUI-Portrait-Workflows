"""AI 参考图库 · 只读浏览（M1）。

参考库是只读素材层：上游 `ai-pose-gallery-zh` 的 JSON 与图片不复制、不改写，
这里只负责把四份 JSON 适配成 atelier 的 DTO 与分页响应。

端点（§3.3）：
- GET /api/reference/libraries
- GET /api/reference/items
- GET /api/reference/items/{library}/{item_id}
- GET /api/reference/items/{library}/{item_id}/image?kind=thumb|image|depth|depth_thumb
"""
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field


from app.config import settings
from app.services import reference_library, reference_remote_cache, uploads
from app.services.paths import IMAGE_EXTENSIONS, resolve_plain, resolve_under
from app.services.recipe_prompt import RecipeEntry, STYLE_PRESETS, build_recipe_prompt

router = APIRouter(tags=["参考图库"])
logger = logging.getLogger(__name__)


@router.on_event("startup")
def log_reference_libraries_on_startup():
    """启动时打印四库条数与 18+ 总闸；失败/偏离基线会以 warning 出现在同一份日志里。"""
    reference_library.log_library_summary()
    logger.info(
        "参考库 18+ 总闸：%s",
        "开启（前端可切换）" if settings.reference_allow_nsfw else "关闭（敏感内容过滤）",
    )


#: 出图工作流文件名（都在 `settings.library_root` 根目录）。
THREE_REF_WORKFLOW = "PornMaster_Flux2Klein9B_三图角色合成_6步_自动尺寸.api.json"
FOUR_REF_WORKFLOW = "PornMaster_Flux2Klein9B_四图参考_6步_自动尺寸.api.json"

#: 四图工作流里第 4 张的 LoadImage 节点（已接链尾，勿改接法）。
EXTRA_REF_NODE = "78"

#: 服装槽允许的库：本地服装库 + 外链二次元服装库（后者需缓存就绪）。
COSTUME_LIBRARIES = ("costume", "costume-anime")


class ReferenceItem(BaseModel):
    id: str
    library: str
    name: str
    subtitle: str = ""
    #: 仅 pose 非空：上游「姿势编号」；其他库为 ""
    number: str = ""
    group: str = ""
    facet: str = ""
    angle: str = ""
    tags: list[str] = Field(default_factory=list)
    keywords: str = ""
    #: 外链条目字段缺失时给 None（空串会让前端 <img src=""> 请求当前页面）
    thumb_url: str | None = None
    image_url: str | None = None
    depth_url: str | None = None
    #: 仅 pose 且 `thumbs/depth/{id}.webp` 存在时非空；卡片用它，灯箱仍用 `depth_url`。
    depth_thumb_url: str | None = None
    hot: bool = False
    featured: bool = False
    nsfw: bool = False
    remote: bool = False
    #: 仅 costume-anime 且上游有「来源地址」时非空
    source_url: str | None = None
    #: 与后端过滤一致的预拼检索串原文（前端「检索」字段直接取此值）
    search_text: str = ""


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
    #: 后端总闸；每库行内带一份，方便前端不额外请求就能判断开关可用性
    allow_nsfw: bool = False
    groups: list[ReferenceFacetValue] = Field(default_factory=list)
    facets: list[ReferenceFacetValue] = Field(default_factory=list)
    angles: list[ReferenceFacetValue] = Field(default_factory=list)


class ReferenceLibraryListResponse(BaseModel):
    libraries: list[ReferenceLibraryStats] = Field(default_factory=list)
    #: 18+ 总闸（`ATELIER_REFERENCE_ALLOW_NSFW`）；前端据此置灰开关，不再靠条数推断
    allow_nsfw: bool = False


@router.get("/reference/ping")
def ping_reference_library():
    """唯一保留的参考库探活端点（其余 router 的重复注册已删除）。"""
    return {"ok": True, "router": "reference_library"}


@router.get("/reference/libraries", response_model=ReferenceLibraryListResponse)
def list_reference_libraries():
    return {
        "libraries": reference_library.library_stats(),
        "allow_nsfw": settings.reference_allow_nsfw,
    }


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
async def get_reference_image(
    library: str,
    item_id: str,
    kind: str = Query("thumb", description="thumb / image / depth / depth_thumb"),
):
    """参考图库图片端点。

    本地三库走 `_safe_image_path`；`costume-anime` 走本机缓存优先 + 只读代理下载
    （C-REMOTE-CACHE@1）：缓存命中不发网络请求，未命中下载并原子写入后返回。
    """
    if library == "costume-anime":
        if kind == "depth":
            raise HTTPException(404, "该库没有深度图")
        if kind == "depth_thumb":
            raise HTTPException(404, "该库没有深度缩略图")
        if kind not in ("thumb", "image"):
            raise HTTPException(404, "不支持的图片类型")

        if reference_library.get_item(library, item_id) is None:
            raise HTTPException(404, "参考条目不存在")
        url = reference_library.resolve_remote_url(library, item_id, kind)
        if not url:
            raise HTTPException(400, "该条目没有可用的图片地址")

        try:
            path = await reference_remote_cache.ensure_cached(library, item_id, kind, url)
        except reference_remote_cache.RemoteCacheError as exc:
            raise HTTPException(exc.status_code, exc.detail) from None
        return FileResponse(
            str(path),
            media_type=reference_library.media_type_for(path),
            headers={"Cache-Control": "no-cache"},
        )

    try:
        path = reference_library.resolve_image(library, item_id, kind)
    except reference_library.ReferenceImageError as exc:
        raise HTTPException(exc.status_code, exc.detail) from None
    return FileResponse(
        str(path),
        media_type=reference_library.media_type_for(path),
        headers={"Cache-Control": "no-cache"},
    )

class RecipeRequest(BaseModel):
    """参考库三图/四图出图；每张参考可给库条目 id 或 uploads 内路径。

    优先级：`*_id` 非空用库条目，否则用 `*_path`；两者都空视为缺输入。
    带第 4 张（库条目或上传图）时自动切四图工作流。

    `costume_library` 只影响服装槽：默认本地 `costume`，也可选外链
    `costume-anime`（缓存就绪后才参与出图）。人像/姿势槽的库固定不变。
    """

    portrait_id: str = ""
    costume_id: str = ""
    pose_id: str = ""
    #: 服装槽使用的库：仅 `costume` / `costume-anime`
    costume_library: str = "costume"
    #: 上传图路径（必须在 `library_root/uploads` 内）；与对应 `*_id` 二选一
    portrait_path: str = ""
    costume_path: str = ""
    pose_path: str = ""
    #: 第 4 张（可选）：任意本地库条目或上传图，只补鞋包/配饰/场景
    extra_library: str = ""
    extra_id: str = ""
    extra_path: str = ""
    style: str = "realistic"
    prompt_suffix: str = ""
    seed: int = 100000
    seed_mode: str = "fixed"
    output_subfolder: str = ""
    dry_run: bool = False


def _upload_path(raw: str, label: str) -> Path:
    """校验上传图路径：必须在 uploads 内、扩展名合法、确实是文件，否则 400。

    相对路径按 uploads 目录解析（前端上传接口返回的是绝对路径，两种都接受）。
    """
    base = resolve_plain(uploads.uploads_dir())
    candidate = resolve_under(base, raw)
    if candidate is None:
        raise HTTPException(400, f"{label}必须是上传目录 uploads 内的文件")
    if candidate.suffix.lower() not in IMAGE_EXTENSIONS:
        raise HTTPException(400, f"{label}不是支持的图片类型")
    try:
        if not candidate.is_file():
            raise HTTPException(400, f"{label}不存在：{raw}")
    except OSError:
        raise HTTPException(400, f"{label}不可读：{raw}") from None
    return candidate


def _recipe_entry(library: str, item_id: str, label: str) -> tuple[dict, Path]:
    """校验条目可见并解析出图用的真实文件路径；错误信息带上槽位名。

    本地三库直接取参考库内的原图；`costume-anime` 是外链库，先取上游 URL，
    缓存命中用本机文件，未命中按 `C-REMOTE-CACHE@1` 下载后再参与出图。
    `costume-anime` 不再因 `remote=true` 一律拒绝，但其余外链库仍不允许。

    许可边界：CharaDB 素材仅本机参考、禁止再分发；缓存只落在
    `reference_cache_dir`，不得复制进 `reference_root` / `data/` / `dist/`。
    """
    if not item_id:
        raise HTTPException(400, f"缺少{label}")
    if library not in reference_library.LIBRARY_FILES:
        raise HTTPException(404, f"未知参考库：{library}")
    item = reference_library.get_item(library, item_id)
    if item is None:
        raise HTTPException(404, f"{label}不存在或不可见：{item_id}")

    if item["remote"]:
        # CharaDB 素材仅本机参考、禁止再分发；只有 costume-anime 提供缓存通道。
        if library != "costume-anime":
            raise HTTPException(400, f"{label}是外链素材，不能参与本地出图")
        url = reference_library.resolve_remote_url(library, item_id, "image")
        if not url:
            raise HTTPException(400, f"{label}没有可用的图片地址：{item_id}")
        try:
            path = reference_remote_cache.ensure_cached_sync(
                library, item_id, "image", url
            )
        except reference_remote_cache.RemoteCacheError as exc:
            # 下载/落盘失败统一 502；URL、域名等非法仍按 400 返回，且都带槽位名。
            if exc.status_code == 502:
                raise HTTPException(502, f"{label}：外链图片下载失败") from None
            raise HTTPException(exc.status_code, f"{label}：{exc.detail}") from None
        return item, path

    try:
        path = reference_library.resolve_image(library, item_id, "image")
    except reference_library.ReferenceImageError as exc:
        raise HTTPException(exc.status_code, f"{label}：{exc.detail}") from None
    return item, path


def _resolve_slot(
    library: str, item_id: str, raw_path: str, label: str
) -> tuple[dict | None, Path]:
    """`*_id` 优先用库条目，否则回落到 uploads 内路径；条目为 None 表示上传图。"""
    if item_id.strip():
        return _recipe_entry(library, item_id.strip(), label)
    if raw_path.strip():
        return None, _upload_path(raw_path, label)
    raise HTTPException(400, f"缺少{label}（库条目 id 或上传图路径）")


#: 上传图没有上游元数据，提示词里用中性描述占位，避免出现空括号。
_UPLOAD_ENTRY: dict[str, RecipeEntry] = {
    # 人像槽的 facet 会作为"发型（…）"的兜底描述
    "portrait": RecipeEntry(id="", name="", facet="与参考图一致"),
    "costume": RecipeEntry(id="", name="上传的服装参考"),
    "pose": RecipeEntry(id="", name="上传的姿势参考"),
    "extra": RecipeEntry(id="", name="上传的附加参考图"),
}


def _slot_entry(item: dict | None, key: str) -> RecipeEntry:
    return _as_entry(item) if item is not None else _UPLOAD_ENTRY[key]


def _as_entry(item: dict) -> RecipeEntry:
    return RecipeEntry(
        id=item["id"],
        name=item.get("name", ""),
        subtitle=item.get("subtitle", ""),
        facet=item.get("facet", ""),
        angle=item.get("angle", ""),
    )


def _slot_info(role: str, item: dict | None, path: Path, library: str) -> dict:
    """一个槽位的溯源信息：库条目与上传图统一成同一种形状，便于前端/日志核对。"""
    if item is None:
        return {
            "role": role,
            "source": "upload",
            "library": "",
            "id": "",
            "name": path.name,
            "path": str(path),
        }
    return {
        "role": role,
        "source": "library",
        "library": library,
        "id": item["id"],
        "name": item.get("name", ""),
        "path": str(path),
    }


@router.post("/reference/recipes")
def create_reference_recipe(req: RecipeRequest):
    """三图/四图出图：组提示词后直接复用 editor 的批量提交入口。

    这里**不**新写图片注入与提交队列：`_collect_sources`、`inject_input_image`、
    任务记录、SSE、画廊归档全部走 `/api/editor/faceswap/batch` 的现成实现。
    """
    if req.style not in STYLE_PRESETS:
        raise HTTPException(400, f"不支持的画风：{req.style}")
    if req.costume_library not in COSTUME_LIBRARIES:
        raise HTTPException(
            400,
            f"不支持的服装库：{req.costume_library}"
            f"（仅支持 {' / '.join(COSTUME_LIBRARIES)}）",
        )

    portrait, portrait_path = _resolve_slot("portrait", req.portrait_id, req.portrait_path, "人像")
    costume, costume_path = _resolve_slot(
        req.costume_library, req.costume_id, req.costume_path, "服装"
    )
    pose, pose_path = _resolve_slot("pose", req.pose_id, req.pose_path, "姿势")

    extra = None
    extra_path = None
    if req.extra_id.strip():
        if not req.extra_library:
            raise HTTPException(400, "第 4 张缺少参考库标识")
        extra, extra_path = _recipe_entry(req.extra_library, req.extra_id.strip(), "第 4 张参考")
    elif req.extra_path.strip():
        extra_path = _upload_path(req.extra_path, "第 4 张参考")

    prompt = build_recipe_prompt(
        _slot_entry(portrait, "portrait"),
        _slot_entry(costume, "costume"),
        _slot_entry(pose, "pose"),
        _slot_entry(extra, "extra") if extra_path else None,
        style=req.style,
        prompt_suffix=req.prompt_suffix,
    )

    workflow_name = FOUR_REF_WORKFLOW if extra_path else THREE_REF_WORKFLOW
    workflow_path = settings.library_root / workflow_name
    if not workflow_path.is_file():
        raise HTTPException(400, f"出图工作流不存在：{workflow_name}")

    # 节点顺序与提示词编号严格对应：图1 人像 / 图2 服装 / 图3 姿势 / 图4 附加。
    from app.routers import editor as editor_router

    payload = editor_router.FaceswapRequest(
        main_paths=[str(portrait_path)],
        ref_paths=[str(costume_path)],
        ref2_paths=[str(pose_path)],
        ref3_paths=[str(extra_path)] if extra_path else [],
        main_node="1",
        ref_node="2",
        ref2_node="3",
        ref3_node=EXTRA_REF_NODE if extra_path else None,
        workflow_path=str(workflow_path),
        prompt=prompt,
        seed=req.seed,
        seed_mode=req.seed_mode,
        output_subfolder=req.output_subfolder,
        dry_run=req.dry_run,
        job_label="参考库出图",
    )
    result = editor_router.faceswap_batch(payload)

    slots = [
        _slot_info("portrait", portrait, portrait_path, "portrait"),
        _slot_info("costume", costume, costume_path, req.costume_library),
        _slot_info("pose", pose, pose_path, "pose"),
    ]
    if extra_path is not None:
        slots.append(_slot_info("extra", extra, extra_path, req.extra_library or ""))

    return {
        **result,
        "prompt": prompt,
        "style": req.style,
        "workflow_path": str(workflow_path),
        #: 统一溯源：库条目与上传图同一形状（source/id/path）。`references` 保留兼容。
        "slots": slots,
        "references": {
            "portrait": portrait["id"] if portrait else "",
            "costume": costume["id"] if costume else "",
            "pose": pose["id"] if pose else "",
            "extra": extra["id"] if extra else "",
        },
    }