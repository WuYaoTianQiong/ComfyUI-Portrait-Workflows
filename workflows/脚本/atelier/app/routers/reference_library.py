"""AI 参考图库 · 只读浏览（M1）。

参考库是只读素材层：上游 `ai-pose-gallery-zh` 的 JSON 与图片不复制、不改写，
这里只负责把四份 JSON 适配成 atelier 的 DTO 与分页响应。

端点（§3.3）：
- GET /api/reference/libraries
- GET /api/reference/items
- GET /api/reference/items/{library}/{item_id}
- GET /api/reference/items/{library}/{item_id}/image?kind=thumb|image|depth|depth_thumb
"""
import copy
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field


from app.config import settings
from app.services import reference_library, reference_remote_cache, uploads
from app.services.paths import IMAGE_EXTENSIONS, resolve_plain, resolve_under
from app.services.recipe_prompt import (
    BODY_MODES,
    RecipeEntry,
    STYLE_PRESETS,
    build_recipe_prompt,
)
from app.services.workflow_parser import (
    find_image_input_keys,
    find_loadimage_nodes,
    image_input_key_index,
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


#: 合成台默认工作流：2026-11-05 T0 三候选实测对比后定为 Qwen21 + VNCCS
#: （三槽齐全 + 姿势 LoRA，25 步单人链路）；空请求一律用它，不再按张数硬绑三图/四图。
DEFAULT_STUDIO_WORKFLOW = "图库专用_Qwen21+VNCCS_三图_25步_单人.api.json"

#: 槽位固定顺序：提示词编号、提交顺序、错误文案都以它为准。
SLOT_ROLES = ("portrait", "costume", "pose", "extra")

#: 槽位中文名（仅用于错误信息，前端不依赖）
SLOT_LABELS = {"portrait": "人像", "costume": "服装", "pose": "姿势", "extra": "第 4 张参考"}

#: 参考图分支上可安全删除的节点类型：删掉它们只会移除这一路参考，
#: 不会影响主链路（KSampler / SaveImage 等不在此列，遇到即停止向下裁剪）。
_REFERENCE_BRANCH_TYPES = frozenset({
    "ImageScaleToTotalPixels",
    "ImageScale",
    "ImageScaleBy",
    "ImageResize",
    "ImageResizeKJ",
    "ImageResizeKJv2",
    "VAEEncode",
    "ReferenceLatent",
})

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
    #: 上传图路径（必须在 `library_root/uploads` 内）；与对应 `*_id` 二选一
    portrait_path: str = ""
    costume_path: str = ""
    pose_path: str = ""
    #: 第 4 张（可选）：任意本地库条目或上传图，只补鞋包/配饰/场景
    extra_library: str = ""
    extra_id: str = ""
    extra_path: str = ""
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


class _NotTrimmable(Exception):
    """该工作流的空槽不能安全裁剪（不是纯文本编码器输入，或删了会断主链路）。"""


def _downstream_consumers(api_workflow: dict, node_id: str) -> list[tuple[str, str]]:
    """返回引用该节点的下游 (节点 id, 输入键)。"""
    target = str(node_id)
    out: list[tuple[str, str]] = []
    for nid, node in api_workflow.items():
        if not isinstance(node, dict):
            continue
        for key, value in (node.get("inputs") or {}).items():
            if isinstance(value, (list, tuple)) and len(value) == 2 \
                    and str(value[0]) == target:
                out.append((str(nid), key))
    return out


def _role_nodes(api_workflow: dict) -> dict[str, str]:
    """按标题把 LoadImage 映射到业务角色；同一角色重复时只认第一个。"""
    out: dict[str, str] = {}
    for node_id, title in find_loadimage_nodes(api_workflow):
        role = loadimage_role(title)
        if role and role not in out:
            out[role] = node_id
    return out


def _build_index_map(api_workflow: dict, filled: dict[str, bool],
                     role_nodes: dict[str, str]) -> dict[str, int]:
    """角色 → 工作流真实图号（images.image_N / imageN 里的 N）。

    裁剪后图位不压缩重排，所以提示词必须按真实图号书写（Qwen21 缺人像时
    服装仍是图3、姿势仍是图1）。没有图片键的工作流（Flux 系）返回空映射，
    提示词退回按出现顺序编号，与实际图位一致。
    """
    index_map: dict[str, int] = {}
    for role in SLOT_ROLES:
        node_id = role_nodes.get(role)
        if not node_id or not filled.get(role):
            continue
        numbers = [
            image_input_key_index(key)
            for _enc_id, key in find_image_input_keys(api_workflow, node_id)
        ]
        numbers = [number for number in numbers if number]
        if numbers:
            index_map[role] = min(numbers)
    return index_map


def _trim_unfilled_slots(api_workflow: dict,
                         filled: dict[str, bool]) -> tuple[dict, dict[str, int]]:
    """在副本上裁掉空槽的参考图分支，返回 (裁剪后工作流, 角色→图号映射)。

    只对“图片通过文本编码器参考图键进入”的 Qwen 系工作流生效：
    · 先删文本编码器里的 images.image_N / imageN 键；
    · 再沿参考图分支删除 ImageScale / VAEEncode / ReferenceLatent；
    · 若被删节点是 conditioning 透传节点，把下游引用改接其上游 conditioning；
    · 其它下游输入（如 KSampler.latent_image）无法直通 → `_NotTrimmable`。

    Flux 系把参考图接到 ReferenceLatent.latent 而文本编码器没有图片键，
    直接删节点会在 VAEEncode 上留下悬空输入，因此判定为不可裁剪。
    """
    api = copy.deepcopy(api_workflow)
    role_nodes = _role_nodes(api)
    index_map = _build_index_map(api, filled, role_nodes)

    drop: set[str] = set()
    drop_keys: list[tuple[str, str]] = []

    for role in SLOT_ROLES:
        node_id = role_nodes.get(role)
        if not node_id or filled.get(role):
            continue
        keys = find_image_input_keys(api, node_id)
        if not keys:
            raise _NotTrimmable(role)
        drop_keys.extend(keys)
        drop.add(node_id)

        # 只沿参考图预处理分支向下走；遇到 KSampler / SaveImage 等主链路节点就停。
        stack = [node_id]
        while stack:
            current = stack.pop()
            for consumer_id, key in _downstream_consumers(api, current):
                # conditioning / positive / negative 是透传语义：沿它扩散会误删
                # 另一条参考分支（例如服装的 ReferenceLatent），改由直通检查处理
                if key == "conditioning" or key.startswith("conditioning_") \
                        or key in ("positive", "negative"):
                    continue
                consumer = api.get(consumer_id)
                if not isinstance(consumer, dict):
                    continue
                if consumer.get("class_type") not in _REFERENCE_BRANCH_TYPES:
                    continue
                if consumer_id in drop:
                    continue
                drop.add(consumer_id)
                stack.append(consumer_id)

    # 被删节点若仍被保留节点引用：只有 conditioning 语义能直通上游
    drop_key_set = set(drop_keys)
    replacements: list[tuple[str, str, object]] = []
    for dropped in drop:
        node = api.get(dropped) or {}
        cond_src = (node.get("inputs") or {}).get("conditioning")
        for consumer_id, key in _downstream_consumers(api, dropped):
            if consumer_id in drop or (consumer_id, key) in drop_key_set:
                continue
            transparent = key == "conditioning" or key.startswith("conditioning_") \
                or key in ("positive", "negative")
            if transparent and cond_src is not None:
                replacements.append((consumer_id, key, cond_src))
                continue
            raise _NotTrimmable(dropped)

    for consumer_id, key, value in replacements:
        api[consumer_id].setdefault("inputs", {})[key] = value
    for enc_id, key in drop_keys:
        inputs = api.get(enc_id, {}).get("inputs")
        if isinstance(inputs, dict):
            inputs.pop(key, None)
    for node_id in drop:
        api.pop(node_id, None)
    return api, index_map


def _resolve_studio_workflow(requested: str) -> Path:
    """解析合成台工作流；显式指定不在 studio 范围内时 400，绝不静默回落。"""
    from app.services.workflow_catalog import list_valid_workflows

    items = list_valid_workflows(scope="studio")
    if not items:
        raise HTTPException(400, "合成台暂无可用工作流")

    explicit = (requested or "").strip()
    raw = explicit or DEFAULT_STUDIO_WORKFLOW
    for item in items:
        name = item["name"]
        # 兼容前端只传简称：xxx.api.json 的 Path.stem 仍是 xxx.api，这里再去一层
        candidates = {name, Path(name).stem, Path(Path(name).stem).stem}
        if raw in candidates or item["path"] == raw:
            return Path(item["path"])

    try:
        resolved = Path(raw).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        resolved = None
    if resolved is not None:
        for item in items:
            if Path(item["path"]).resolve(strict=False) == resolved:
                return Path(item["path"])

    if explicit:
        raise HTTPException(400, "该工作流不属于合成台可用范围")
    raise HTTPException(400, f"默认工作流不可用：{DEFAULT_STUDIO_WORKFLOW}")


@router.post("/reference/recipes")
def create_reference_recipe(req: RecipeRequest):
    """参考库出图：组提示词后直接复用 editor 的批量提交入口。

    每个槽都允许为空；空槽会在工作流副本上裁掉，提示词编号仍按真实图位书写。
    这里**不**新写图片注入与提交队列：`_collect_sources`、`inject_input_image`、
    任务记录、SSE、画廊归档全部走 `/api/editor/faceswap/batch` 的现成实现。
    """
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
    if req.body_mode == "bare" and (req.costume_id.strip() or req.costume_path.strip()):
        raise HTTPException(400, "素体模式不能同时选择服装")

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

    paths = {
        "portrait": portrait_path,
        "costume": costume_path,
        "pose": pose_path,
        "extra": extra_path,
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
    if total > input_count:
        raise HTTPException(
            400, f"该工作流只有 {input_count} 个输入，但提交了 {total} 张",
        )

    role_nodes = _role_nodes(api_wf)
    # 整条工作流一个角色都认不出：与"缺某一个槽"是两回事，文案必须分开，
    # 否则用户只会看到「该工作流没有人像输入」，完全猜不到根因（多为 UI 格式 .json）。
    if not role_nodes:
        raise HTTPException(
            400,
            f"该工作流的参考图节点无法识别角色（可能是 UI 格式工作流），"
            f"请换用 .api.json 工作流：{workflow_path.name}",
        )
    for role in SLOT_ROLES:
        if filled[role] and role not in role_nodes:
            raise HTTPException(
                400, f"该工作流没有{SLOT_LABELS[role]}输入：{workflow_path.name}",
            )

    if total < input_count:
        try:
            trimmed_api, index_map = _trim_unfilled_slots(api_wf, filled)
        except _NotTrimmable:
            trimmed_api = api_wf
            index_map = _build_index_map(api_wf, filled, role_nodes)
        if len(find_loadimage_nodes(trimmed_api)) != total:
            # 工作流还有本次用不到、又无法安全删除的输入：明确告诉用户需要几张
            raise HTTPException(
                400,
                f"该工作流有 {input_count} 个输入且无法裁剪到 {total} 个；"
                f"请至少提供 {input_count} 张参考图",
            )
    else:
        trimmed_api = api_wf
        index_map = _build_index_map(api_wf, filled, role_nodes)

    # 空槽直接传 None（不再用上传占位包装），否则 faceless 分支永远不会触发
    prompt = build_recipe_prompt(
        _slot_entry(portrait, "portrait") if portrait_path else None,
        _slot_entry(costume, "costume") if costume_path else None,
        _slot_entry(pose, "pose") if pose_path else None,
        _slot_entry(extra, "extra") if extra_path else None,
        style=req.style,
        prompt_suffix=req.prompt_suffix,
        index_map=index_map,
        # 素体模式透传：提示词据此追加中性素体条款（C-REF-BODY-MODE@1）
        body_mode=req.body_mode,
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
        main_node=ordered[0][1],
        ref_node=refs[0][1] if len(refs) > 0 else None,
        ref2_node=refs[1][1] if len(refs) > 1 else None,
        ref3_node=refs[2][1] if len(refs) > 2 else None,
        workflow_path=str(workflow_path),
        # 空槽裁剪只作用在副本上：把裁剪后的 API 工作流随请求传下去，不改磁盘文件
        workflow_content=json.dumps(trimmed_api, ensure_ascii=False) if trimmed else None,
        prompt=prompt,
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

    slots = [
        _slot_info("portrait", portrait, portrait_path, "portrait"),
        _slot_info("costume", costume, costume_path, req.costume_library),
        _slot_info("pose", pose, pose_path, "pose"),
        _slot_info("extra", extra, extra_path, req.extra_library or ""),
    ]

    return {
        **result,
        "prompt": prompt,
        "style": req.style,
        "workflow_path": str(workflow_path),
        "input_count": input_count,
        #: 统一溯源：库条目 / 上传图 / 空槽同一形状。`references` 保留兼容。
        "slots": slots,
        "references": {
            "portrait": portrait["id"] if portrait else "",
            "costume": costume["id"] if costume else "",
            "pose": pose["id"] if pose else "",
            "extra": extra["id"] if extra else "",
        },
    }