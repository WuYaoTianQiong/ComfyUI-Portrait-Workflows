"""AI 参考图库 · 只读浏览（M1）。

参考库是只读素材层：上游 `ai-pose-gallery-zh` 的 JSON 与图片不复制、不改写，
这里只负责把四份 JSON 适配成 atelier 的 DTO 与分页响应。

端点（§3.3）：
- GET /api/reference/libraries
- GET /api/reference/items
- GET /api/reference/items/{library}/{item_id}
- GET /api/reference/items/{library}/{item_id}/image?kind=thumb|image|depth|depth_thumb
"""
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field


from app.config import settings
from app.services import reference_library, reference_remote_cache, reference_studio, uploads
from app.services.asset_store import AssetStore, LibraryAssetRef
from app.services.paths import IMAGE_EXTENSIONS, resolve_plain, resolve_under
from app.services.prompt_compiler import compile_for_submission
from app.services.recipe_prompt import (
    BODY_MODES,
    RecipeEntry,
    STYLE_PRESETS,
    build_recipe_prompt,
)
from app.services.workflow_parser import (
    detect_workflow_caps,
    find_loadimage_nodes,
    load_workflow,
    loadimage_role,
)

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


# 兼容旧引用：常量与裁剪引擎已下沉到 services/reference_studio.py。
DEFAULT_STUDIO_WORKFLOW = reference_studio.DEFAULT_STUDIO_WORKFLOW
SLOT_ROLES = reference_studio.SLOT_ROLES
SLOT_LABELS = reference_studio.SLOT_LABELS

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
    #: canonical 三轴字段（仅 pose 非空）：来源 / 构图 / 姿势类型 / 风格
    source: str = ""
    source_label: str = ""
    composition: str = ""
    pose_type: str = ""
    style: str = ""
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
    #: 该条目是否有深度变体；pose-studio-lite 等第二来源为 false
    has_depth: bool = False
    #: 仅 pose：可用性标记（`false` = 实测姿势不跟随，仍可手动选）
    usable: bool = True
    #: 仅 pose：不可用原因；可用时为空串
    usable_note: str = ""
    remote: bool = False
    #: 仅 costume-anime 且上游有「来源地址」时非空
    source_url: str | None = None
    #: 仅 hair：正/背面裁切图端点；单面发型两者均为 None
    hair_front_url: str | None = None
    hair_back_url: str | None = None
    #: 仅 hair：是否有背面无脸图可用于第 4 槽
    hair_usable: bool = False
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


class ReferenceLibrarySourceStats(BaseModel):
    """多来源库（当前仅 pose）的逐来源明细。"""

    key: str
    label: str
    total: int
    available: bool
    has_depth: bool


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
    #: 多来源库（pose）逐来源条数/可用性；单源库为空数组
    sources: list[ReferenceLibrarySourceStats] = Field(default_factory=list)


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
    library: str = Query("pose", description="pose / costume / portrait / hair / costume-anime"),
    search: str = Query("", description="直接匹配上游预拼好的「检索」串"),
    group: str = Query(""),
    facet: str = Query(""),
    angle: str = Query(""),
    nsfw: bool | None = Query(None, description="仅在 ATELIER_REFERENCE_ALLOW_NSFW=1 时生效"),
    page: int = Query(1),
    page_size: int = Query(0, description="0 表示使用 ATELIER_REFERENCE_PAGE_SIZE"),
):
    if library not in reference_library.LIBRARIES:
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
        path = AssetStore().path(LibraryAssetRef(library, item_id, kind))
    except reference_library.ReferenceImageError as exc:
        raise HTTPException(exc.status_code, exc.detail) from None
    if path is None:
        raise HTTPException(404, "参考图片不存在")
    return FileResponse(
        str(path),
        media_type=reference_library.media_type_for(path),
        headers={"Cache-Control": "no-cache"},
    )

class RecipeRequest(BaseModel):
    """参考库出图；人像/服装/姿势/第 4 张每个槽都允许留空。

    优先级：`*_id` 非空用库条目，否则用 `*_path`；两者都空表示该槽不参与本次出图。
    空槽会在提交前从工作流副本里裁掉，提示词编号仍按工作流真实图位书写。

    `workflow` 为空时使用合成台默认工作流；非空时必须是 `scope=studio` 的合法
    工作流，否则 400（绝不静默回落到默认值）。

    `costume_library` 只影响服装槽：默认本地 `costume`，也可选外链
    `costume-anime`（缓存就绪后才参与出图）。人像/姿势槽的库固定不变。
    """

    portrait_id: str = ""
    costume_id: str = ""
    pose_id: str = ""
    #: 服装槽使用的库：仅 `costume` / `costume-anime`
    costume_library: str = "costume"
    #: 上传图路径（必须在 `data_dir/uploads` 内）；与对应 `*_id` 二选一
    portrait_path: str = ""
    costume_path: str = ""
    pose_path: str = ""
    #: 第 4 张（可选）：发型库背面图 / 上传单图，只补发型或附加元素
    extra_library: str = ""
    extra_id: str = ""
    extra_path: str = ""
    #: 第 4 槽文字补充：只在 extra 图片存在时追加「此外需体现」；有文本无图 400
    extra_text: str = ""
    #: V2-C 第 5 槽（可选）：人物B服装；整批共享 1 张，不进入组合维度
    extra_costume_library: str = ""
    extra_costume_id: str = ""
    extra_costume_path: str = ""
    #: 指定合成台工作流（文件名或库内路径）；空 = 默认 Qwen21+VNCCS 三图
    workflow: str = ""
    #: 尺寸参数（前端透传）：空 = 保持现有默认；工作流 caps 不支持时后端会忽略
    quality: str = ""
    aspect_ratio: str = ""
    orientation: str = ""
    style: str = "realistic"
    #: 素体模式（C-REF-BODY-MODE@1）：`costume`（默认，常规出图）/ `bare`（无服装素体展示）。
    #: 其它值 400；`bare` 时不允许同时选择服装。
    body_mode: str = "costume"
    prompt_suffix: str = ""
    #: 槽位碎片文本：槽有图时仅在对应 `*_supplement=true` 时作为补充；
    #: 槽无图时作为替代（§5.1 文本主句）。image 模式 + 文本但开关关闭 → 400。
    portrait_text: str = ""
    costume_text: str = ""
    pose_text: str = ""
    #: 跨源补充开关（P4）：图片槽有图时，是否允许把同槽文本追加为「此外需体现」。
    #: 默认 false；随机整套默认关闭，手动模式按槽显式开启。
    portrait_supplement: bool = False
    costume_supplement: bool = False
    pose_supplement: bool = False
    #: 双人姿势的人物 B 文字设定；仅 `composition=pair` 且自动模式生效
    person_b_text: str = ""
    #: v1.5：人物 B 的面部/身材与服饰文本碎片，独立于 A 的三槽文本；
    #: 仅双人姿势下并入「人物B（文字设定）」，单人姿势忽略。
    person_b_portrait_text: str = ""
    person_b_costume_text: str = ""
    #: 修饰层渲染结果（`• 类型：内容` 多行）；始终追加，插在「补充要求」之前
    modifier_fragments: str = ""
    #: 真负向（透传 FaceswapRequest.negative_prompt）；实际提交内容由编译层合并
    negative_prompt: str = ""
    #: 手动改写（P3）：非空 = 手动模式，直接用该文本作为正向，不再渲染碎片、不校验槽位文本
    prompt_override: str = ""
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
    if library not in reference_library.LIBRARIES:
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
        kind = "back" if library == "hair" else "image"
        path = reference_library.resolve_image(library, item_id, kind)
    except reference_library.ReferenceImageError as exc:
        raise HTTPException(exc.status_code, f"{label}：{exc.detail}") from None
    return item, path


def _resolve_slot(
    library: str, item_id: str, raw_path: str, label: str
) -> tuple[dict | None, Path | None]:
    """解析槽位：库条目 / 上传图 / 空槽。

    id 与 path 都为空时返回 `(None, None)` 表示该槽不参与本次出图；
    其余非法输入（有 id 但查不到、path 越界）仍按原逻辑 400。
    """
    if item_id.strip():
        return _recipe_entry(library, item_id.strip(), label)
    if raw_path.strip():
        return None, _upload_path(raw_path, label)
    return None, None


#: 上传图没有上游元数据，提示词里用中性描述占位，避免出现空括号。
_UPLOAD_ENTRY: dict[str, RecipeEntry] = {
    # 人像槽的 facet 会作为"发型（…）"的兜底描述
    "portrait": RecipeEntry(id="", name="", facet="与参考图一致"),
    "costume": RecipeEntry(id="", name="上传的服装参考"),
    "pose": RecipeEntry(id="", name="上传的姿势参考"),
    "extra": RecipeEntry(id="", name="上传的附加参考图"),
    "extra_costume": RecipeEntry(id="", name="上传的人物B服装参考"),
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
        composition=item.get("composition", ""),
    )


def _slot_info(role: str, item: dict | None, path: Path | None, library: str) -> dict:
    """一个槽位的溯源信息：库条目、上传图与空槽统一成同一种形状。"""
    if path is None:
        # 空槽用 source=empty 明确标记，前端据此显示“未选择”而不是空白假路径
        return {
            "role": role,
            "source": "empty",
            "library": "",
            "id": "",
            "name": "",
            "path": "",
        }
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


def _resolve_studio_workflow(requested: str) -> Path:
    """HTTP 适配层：把 service 的白名单错误转成 400。"""
    try:
        return reference_studio.resolve_studio_workflow(requested)
    except reference_studio.StudioWorkflowError as exc:
        raise HTTPException(400, str(exc)) from None


class TrimCheckRequest(BaseModel):
    """提交前可裁剪探测：只问「这组已填槽位能否提交进这些工作流」，不产生任务。"""

    #: 合成台工作流（文件名或库内路径）；空列表 = 默认工作流
    workflows: list[str] = Field(default_factory=list)
    #: 已填槽位角色（portrait / costume / pose / extra）；重复项忽略
    roles: list[str] = Field(default_factory=list)


class TrimCheckItem(BaseModel):
    #: 与提交端点的 `workflow` 同形（前端按路径对号入座）
    name: str
    path: str
    input_count: int = 0
    #: 本次提交的非空槽位数 M
    slot_count: int = 0
    #: True = 能按 M 张提交（空槽可安全裁掉，或本来就够）
    trimmable: bool = False
    #: 不可提交时的原因（与提交端点的 400 文案同源）
    reason: str = ""


class TrimCheckResponse(BaseModel):
    workflows: list[TrimCheckItem] = Field(default_factory=list)
    #: 全部工作流都能按当前非空槽提交（前端据此直接提交、不弹确认框）
    all_trimmable: bool = True


@router.post("/reference/trim-check", response_model=TrimCheckResponse)
def check_reference_trim(req: TrimCheckRequest):
    """提交前能力探测：空槽能否裁掉。

    与 `/reference/recipes` 共用角色校验与 `reference_studio.resolve_trim_plan`，
    因此 `all_trimmable=true` 时提交不会再因输入数 400；`false` 时前端才弹确认框。
    """
    unknown = sorted({role for role in req.roles if role not in SLOT_ROLES})
    if unknown:
        raise HTTPException(400, f"未知槽位：{'、'.join(unknown)}")
    roles = set(req.roles)
    filled = {role: role in roles for role in SLOT_ROLES}
    total = len(roles)
    if total == 0:
        raise HTTPException(400, "请至少选择一个参考图或上传一张参考图")

    requested = [item.strip() for item in req.workflows if item.strip()] or [""]
    items: list[TrimCheckItem] = []
    for requested_workflow in requested:
        workflow_path = _resolve_studio_workflow(requested_workflow)
        try:
            api_wf = load_workflow(str(workflow_path))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"工作流加载失败：{exc}") from None

        input_count = len(find_loadimage_nodes(api_wf))
        reason = reference_studio.role_support_error(
            reference_studio.role_nodes(api_wf), filled, workflow_path.name,
        )
        if not reason:
            if total > input_count:
                reason = f"该工作流只有 {input_count} 个输入，但提交了 {total} 张"
            else:
                _, _, reason = reference_studio.resolve_trim_plan(api_wf, filled)
        items.append(
            TrimCheckItem(
                name=workflow_path.name,
                path=str(workflow_path),
                input_count=input_count,
                slot_count=total,
                trimmable=not reason,
                reason=reason,
            )
        )

    return TrimCheckResponse(
        workflows=items,
        all_trimmable=all(item.trimmable for item in items),
    )


def _extra_kind(api_workflow: dict) -> str:
    """第 4 张的业务语义：标题带「人物B/PersonB」→ B 身份参考；「发型/Hair」→ 发型参考。"""
    for _node_id, title in find_loadimage_nodes(api_workflow):
        if loadimage_role(title) != "extra":
            continue
        lower = title.lower()
        # v2-A：人物B 身份图优先于发型（两者互斥，标题不会同时出现）。
        if "人物b" in lower or "personb" in lower or "person_b" in lower:
            return "person_b"
        if "发型" in title or "hair" in lower:
            return "hair"
    return ""


@router.post("/reference/recipes")
def create_reference_recipe(req: RecipeRequest):
    """参考库出图：组提示词后直接复用 editor 的批量提交入口。

    每个槽都允许为空；空槽会在工作流副本上裁掉，提示词编号仍按真实图位书写。
    这里**不**新写图片注入与提交队列：`_collect_sources`、`inject_input_image`、
    任务记录、SSE、画廊归档全部走 `/api/editor/faceswap/batch` 的现成实现。

    `prompt_override` 非空 = P3 手动改写：整段正向由前端编辑后原样带回，不再跑
    `build_recipe_prompt`，槽位文本字段也不参与校验；图片槽位、裁剪与体态判定不变。
    """
    # P3 手动改写：前端把编辑后的整段提示词原样带回，非空即手动模式。
    # 统一 strip 一次，后续 prompt / prompt_raw / payload 都用同一份文本。
    manual_override = (req.prompt_override or "").strip()
    if req.style not in STYLE_PRESETS:
        raise HTTPException(400, f"不支持的画风：{req.style}")
    if req.body_mode not in BODY_MODES:
        raise HTTPException(
            400,
            f"不支持的素体模式：{req.body_mode}"
            f"（仅支持 {' / '.join(BODY_MODES)}）",
        )
    if req.costume_library not in COSTUME_LIBRARIES:
        raise HTTPException(
            400,
            f"不支持的服装库：{req.costume_library}"
            f"（仅支持 {' / '.join(COSTUME_LIBRARIES)}）",
        )
    # 素体模式不穿衣服：同时选了服装（库条目或上传图）就自相矛盾，直接 400
    if req.body_mode == "bare" and (
        req.costume_id.strip()
        or req.costume_path.strip()
        or req.extra_costume_id.strip()
        or req.extra_costume_path.strip()
    ):
        raise HTTPException(400, "素体模式不能同时选择服装")
    # bare 下服装文本同样属于「不穿衣服却描述衣服」，与服装图一视同仁拒绝。
    # P3 手动模式下文本字段不参与（前端不发送），因此不再据此 400。
    if (
        not manual_override
        and req.body_mode == "bare"
        and req.costume_text.strip()
    ):
        raise HTTPException(400, "素体模式不能同时选择服装文本")

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

    # V2-C 第 5 槽：人物B服装（整批共享 1 张；只允许服装库或上传）
    extra_costume = None
    extra_costume_path = None
    if req.extra_costume_id.strip():
        if req.extra_costume_library not in COSTUME_LIBRARIES:
            raise HTTPException(
                400,
                f"不支持的人物B服装库：{req.extra_costume_library}"
                f"（仅支持 {' / '.join(COSTUME_LIBRARIES)}）",
            )
        extra_costume, extra_costume_path = _recipe_entry(
            req.extra_costume_library, req.extra_costume_id.strip(), "人物B服装参考",
        )
    elif req.extra_costume_path.strip():
        extra_costume_path = _upload_path(req.extra_costume_path, "人物B服装参考")

    # 第 4 槽是「图为主 + 文本补充」：没有图片时文字不生效，直接 400，
    # 避免把一句发型描述当成纯文字第 4 槽提交（与明确不做项一致）。
    extra_text = req.extra_text.strip()
    if extra_text and extra_path is None:
        raise HTTPException(
            400,
            "第 4 槽文字补充必须同时提供一张发型参考图（不支持纯文字第 4 槽）",
        )

    paths = {
        "portrait": portrait_path,
        "costume": costume_path,
        "pose": pose_path,
        "extra": extra_path,
        "extra_costume": extra_costume_path,
    }
    filled = {role: paths[role] is not None for role in SLOT_ROLES}
    total = sum(filled.values())

    # 工作流：显式指定必须是 studio 白名单；为空用默认（不按张数/extra 静默切换）
    workflow_path = _resolve_studio_workflow(req.workflow)
    try:
        api_wf = load_workflow(str(workflow_path))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"工作流加载失败：{exc}") from None

    # 按槽位数校验工作流能力：工作流 LoadImage 数 = N，实际非空槽数（含 extra）= M
    input_count = len(find_loadimage_nodes(api_wf))
    if total == 0:
        raise HTTPException(400, "请至少选择一个参考图或上传一张参考图")
    # P2 替代态（方案 §4.4）：*_text 在对应槽无图时作为替代主描述，不再 400。
    # 文本槽不计入 filled，仍交给 reference_studio.resolve_trim_plan 裁剪；
    # 三槽全无图已在上方 total==0 拦住（文本不参与计数）。
    if total > input_count:
        raise HTTPException(
            400, f"该工作流只有 {input_count} 个输入，但提交了 {total} 张",
        )

    # P4（2026-11-06）：图片槽 + 同槽文本默认不再静默补充。
    # 必须显式开启 *_supplement；否则 400，避免跨源文本覆盖参考图特征。
    # 手动改写（P3）不渲染槽位文本，因此不参与本校验。
    if not manual_override:
        for role, label, text, enabled in (
            ("portrait", "人像", req.portrait_text, req.portrait_supplement),
            ("costume", "服装", req.costume_text, req.costume_supplement),
            ("pose", "姿势", req.pose_text, req.pose_supplement),
        ):
            if filled[role] and text.strip() and not enabled:
                raise HTTPException(
                    400,
                    f"{label}槽已选择参考图；文本补充需显式开启 {role}_supplement=true，"
                    "或把该槽切为文本模式",
                )

    role_nodes = reference_studio.role_nodes(api_wf)
    role_error = reference_studio.role_support_error(role_nodes, filled, workflow_path.name)
    if role_error:
        raise HTTPException(400, role_error)

    # 空槽裁剪：与 /reference/trim-check 共用同一判定，探测通过即不会在这里 400
    trimmed_api, index_map, trim_error = reference_studio.resolve_trim_plan(api_wf, filled)
    if trim_error:
        raise HTTPException(400, trim_error)

    # 缺服装时的体态语义（2026-11-06 实测）：`costume` 模式但「服装槽无图」时，若提示词里
    # 没有任何服装约束，Qwen 系会自由发挥（实测两张连续出裸体）。这里统一按 `bare`
    # （中性素体展示 + 禁止性化措辞）生成提示词；响应回传生效值，前端据此 toast 说明。
    # P2（C3-1）：服装**文本**也是服装约束，只有「既无服装图、也无服装文本」才自动切 bare，
    # 否则用户填的文字描述会被素体条款抹掉，等于静默丢需求。
    # `bare` 与服装（图/文本）同时出现仍在上方直接 400，本兜底只在服装槽为空时生效。
    # P3 手动模式下槽位文本不参与提示词，因此自动素体只看「服装槽是否有图」。
    effective_costume_text = "" if manual_override else req.costume_text
    body_mode = req.body_mode
    body_mode_auto = False
    if (
        body_mode == "costume"
        and not filled["costume"]
        and not effective_costume_text.strip()
    ):
        body_mode = "bare"
        body_mode_auto = True

    # 第 4 张在发型工作流里按「发型参考」写专用提示词；其他工作流保持附加参考。
    extra_kind = _extra_kind(api_wf)

    # 手动改写（P3）：前端已按分段编辑好整段正向，后端不再渲染碎片。
    # 第 4 槽文字同样不参与（前端手动模式也不发送），与三槽文本口径一致。
    if manual_override:
        prompt = manual_override
        extra_text = ""
    else:
        # 空槽直接传 None（不再用上传占位包装），否则 faceless 分支永远不会触发
        prompt = build_recipe_prompt(
            _slot_entry(portrait, "portrait") if portrait_path else None,
            _slot_entry(costume, "costume") if costume_path else None,
            _slot_entry(pose, "pose") if pose_path else None,
            _slot_entry(extra, "extra") if extra_path else None,
            extra_kind=extra_kind,
            # V2-C：第 5 槽 = 人物B服装；仅双人姿势下写 B 条款
            extra_costume=(
                _slot_entry(extra_costume, "extra_costume")
                if extra_costume_path
                else None
            ),
            style=req.style,
            prompt_suffix=req.prompt_suffix,
            index_map=index_map,
            # 素体模式透传：提示词据此追加中性素体条款（C-REF-BODY-MODE@1）
            body_mode=body_mode,
            # P2/P4 三槽文本：槽无图 → 替代态（§5.1）；槽有图 + supplement=true
            # → 补充态（「此外需体现」）。槽有图但开关关闭已在上方 400，不会到这里。
            portrait_text=req.portrait_text,
            costume_text=req.costume_text,
            pose_text=req.pose_text,
            # 修饰层：始终追加，插在「补充要求」/固定风格段之前
            modifier_fragments=req.modifier_fragments,
            negative_prompt=req.negative_prompt,
            person_b_text=req.person_b_text,
            # v1.5：人物 B 的面部/身材与服饰碎片，只在双人姿势下并入 B 条款
            person_b_portrait_text=req.person_b_portrait_text,
            person_b_costume_text=req.person_b_costume_text,
            # 第 4 槽文字补充：只在 extra 图片存在时渲染「此外需体现」
            extra_text=extra_text,
        )

    # 提交顺序固定 人像 → 服装 → 姿势 → 附加；节点 id 用工作流真实图位（不重排）
    ordered = [
        (role, role_nodes[role], paths[role])
        for role in SLOT_ROLES
        if filled[role] and role_nodes.get(role)
    ]
    refs = ordered[1:]

    from app.routers import editor as editor_router

    trimmed = len(trimmed_api) != len(api_wf)
    payload = editor_router.FaceswapRequest(
        main_paths=[str(ordered[0][2])],
        ref_paths=[str(refs[0][2])] if len(refs) > 0 else [],
        ref2_paths=[str(refs[1][2])] if len(refs) > 1 else [],
        ref3_paths=[str(refs[2][2])] if len(refs) > 2 else [],
        ref4_paths=[str(refs[3][2])] if len(refs) > 3 else [],
        main_node=ordered[0][1],
        ref_node=refs[0][1] if len(refs) > 0 else None,
        ref2_node=refs[1][1] if len(refs) > 1 else None,
        ref3_node=refs[2][1] if len(refs) > 2 else None,
        ref4_node=refs[3][1] if len(refs) > 3 else None,
        workflow_path=str(workflow_path),
        # 空槽裁剪只作用在副本上：把裁剪后的 API 工作流随请求传下去，不改磁盘文件
        workflow_content=json.dumps(trimmed_api, ensure_ascii=False) if trimmed else None,
        prompt=prompt,
        # 负向透传：真实提交由 inject_prompt 统一跑 compile_prompt 合并/清空
        negative_prompt=req.negative_prompt,
        # P3 手动改写：跳过 compile_prompt，按原文写入正向/负向
        skip_compile=bool(manual_override),
        seed=req.seed,
        seed_mode=req.seed_mode,
        #: 尺寸参数原样透传，由 editor 统一校验并按工作流能力做二次防护
        quality=req.quality,
        aspect_ratio=req.aspect_ratio,
        orientation=req.orientation,
        output_subfolder=req.output_subfolder,
        dry_run=req.dry_run,
        job_label="参考库出图",
    )
    result = editor_router.faceswap_batch(payload)

    # dry-run 一致性（方案 §11.3）：真实提交时 inject_prompt 会跑 compile_prompt，
    # 把「不要军姿 / 文字水印」等否定抽成负向并改写正向；预览必须返回同一份结果，
    # 否则用户看到的和实际跑的不是一份。`prompt_raw` 保留编译前原文供对照。
    # P3 手动改写不走编译：预览与实际提交都必须是用户编辑后的原文。
    prompt_raw = prompt
    response_prompt = prompt
    response_negative = req.negative_prompt
    negative_effective: bool | None = None
    if manual_override:
        if req.dry_run:
            # 与 inject_prompt 同源判定，且用裁剪后的工作流（与真实提交内容一致）
            caps = detect_workflow_caps(trimmed_api)
            negative_effective = bool(caps.get("negative_effective"))
            # 负向不生效时实际提交空串，预览同步显示空串
            response_negative = (
                req.negative_prompt if negative_effective else ""
            )
    elif req.dry_run:
        # 与 inject_prompt 同源判定，且用裁剪后的工作流（与真实提交内容一致）
        caps = detect_workflow_caps(trimmed_api)
        negative_effective = bool(caps.get("negative_effective"))
        compiled = compile_for_submission(
            prompt, req.negative_prompt, negative_effective=negative_effective,
        )
        response_prompt = compiled.positive
        # inject_prompt 在负向不生效时提交空串，这里同步显示空串（而不是原文）
        response_negative = compiled.negative if negative_effective else ""

    slots = [
        _slot_info("portrait", portrait, portrait_path, "portrait"),
        _slot_info("costume", costume, costume_path, req.costume_library),
        _slot_info("pose", pose, pose_path, "pose"),
        _slot_info("extra", extra, extra_path, req.extra_library or ""),
        _slot_info(
            "extra_costume", extra_costume, extra_costume_path,
            req.extra_costume_library or "",
        ),
    ]

    body = {
        **result,
        "prompt": response_prompt,
        #: 编译前正向原文（dry_run 与真实提交共用同一份来源）
        "prompt_raw": prompt_raw,
        #: 实际会提交的负向：dry_run 时为「自动抽取 + 用户填写」合并后的结果
        "negative_prompt": response_negative,
        #: 仅 dry_run 计算，与 inject_prompt 的 negative_effective 同源；其它情况为 None
        "negative_effective": negative_effective,
        "style": req.style,
        "workflow_path": str(workflow_path),
        "input_count": input_count,
        #: 实际生效的体态模式；`body_mode_auto=True` 表示「服装槽为空 → 自动素体展示」
        "body_mode": body_mode,
        "body_mode_auto": body_mode_auto,
        #: 本次实际生效的跨源补充槽；手动改写恒为 false
        "supplements": {
            "portrait": bool(
                not manual_override
                and filled["portrait"]
                and req.portrait_text.strip()
                and req.portrait_supplement
            ),
            "costume": bool(
                not manual_override
                and filled["costume"]
                and req.costume_text.strip()
                and req.costume_supplement
            ),
            "pose": bool(
                not manual_override
                and filled["pose"]
                and req.pose_text.strip()
                and req.pose_supplement
            ),
        },
        #: 统一溯源：库条目 / 上传图 / 空槽同一形状。`references` 保留兼容。
        "slots": slots,
        "references": {
            "portrait": portrait["id"] if portrait else "",
            "costume": costume["id"] if costume else "",
            "pose": pose["id"] if pose else "",
            "extra": extra["id"] if extra else "",
            "extra_costume": extra_costume["id"] if extra_costume else "",
        },
    }
    #: 手动改写标记只在该模式下出现，自动模式（P1/P2）响应形状保持不变
    if manual_override:
        body["manual_override"] = True
    return body