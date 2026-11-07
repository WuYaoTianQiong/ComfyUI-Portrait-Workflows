"""批量图像编辑 —— 目标图 × 参考图 的笛卡尔积，逐条提交 ComfyUI。

一个页面覆盖四种 Flux2 编辑工作流：
  · 单图编辑      1 个 LoadImage：目标图
  · 双图参考      2 个 LoadImage：目标图 + 参考图1
  · 三图参考      3 个 LoadImage：目标图 + 参考图1 + 参考图2
  · 四图参考      4 个 LoadImage：再加参考图3（只补鞋包/配饰/场景，接链尾）

素材可以来自两处（可混用）：
  · 画廊历史图（gen_history 的 id）
  · 磁盘上任意文件夹里的图片（绝对路径，前端有文件夹浏览器）

复用项目既有的一套：
  services.workflow_parser  UI→API 转换 / 提示词·种子注入 / LoadImage 多图注入
  services.comfyui_client   push_prompt
  gen_jobs + 后台 job_monitor_loop  出图完成后自动写入 gen_history（画廊自动可见）

与既有端点的区别：/api/runs/batch 是「多提示词 × 单参考图」，
/api/images/{id}/process 是「单主图 × 单参考图」，这里补的是「多目标 × 多参考」。
"""
import base64
import hashlib
import io
import itertools
import json
import random
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.models import Image
from app.routers.media import IMAGE_EXT
from app.routers.jobs import (
    build_job_extra,
    find_job_by_idempotency,
)
from app.services.image_inputs import (
    clean_dest_name as _clean_dest_name,
    compose_masked_target as _compose_masked_target,
    dest_name as _dest_name,
)
from app.services.output_location import (
    OutputLocationError,
    expand_subfolder,
    with_subfolder,
)
from app.services.generation import SubmitSpec, submit_spec
from app.services.idempotency import SCOPE_FACESWAP, request_key
from app.services.paths import resolve_image_path
from app.services.quality_keys import QUALITY_SCALES, normalize_quality
from app.services.workflow_parser import (
    CANONICAL_RATIOS,
    detect_workflow_caps,
    find_loadimage_nodes,
    find_size_source_loadimage,
    inject_input_image,
    inject_prompt,
    load_workflow,
    resolve_seed,
    normalize_aspect_ratio,
    set_output_prefix,
    set_save_subfolder,
)

router = APIRouter(tags=["批量图像编辑"])

DEFAULT_PROMPT = (
    "只修改提示词中描述的部分，其余人物相貌、姿势、构图、服装、背景与光线保持与目标图一致，"
    "自然真实，高清细节"
)

# 一个工作流从上到下最多注入「目标图 + 参考图1 + 参考图2 + 参考图3」四张
MAX_INPUTS = 4
# 笛卡尔积上限：多组素材全组合很容易爆炸，超限直接让用户收窄选择
MAX_COMBOS = 100

ROLE_ORDER = ("target", "ref1", "ref2", "ref3")

# 不涂遮罩时走整图重绘；尺寸/画质由工作流自己决定（本项目里多数编辑工作流用 ImageResizeKJ
# 保持目标图原尺寸，EmptyLatentImage 相关的 quality/orientation 注入对这些工作流是空转）
ORIENTATION = "portrait"
QUALITY = "1.0x"


class NodesRequest(BaseModel):
    workflow_path: str = ""
    workflow_content: str | None = None


class MaskSaveRequest(BaseModel):
    data_url: str


class FaceswapRequest(BaseModel):
    main_ids: list[int] = []       # 目标图（沿用旧字段名，避免已有调用方失效）
    ref_ids: list[int] = []        # 参考图1
    ref2_ids: list[int] = []       # 参考图2（三图工作流）
    ref3_ids: list[int] = []       # 参考图3（四图工作流，只补鞋包/配饰/场景）
    main_paths: list[str] = []     # 磁盘绝对路径，可与 ids 混用
    ref_paths: list[str] = []
    ref2_paths: list[str] = []
    ref3_paths: list[str] = []
    # 遮罩：与目标图顺序一一对应；空字符串 = 这张目标图不配遮罩（整图重绘）
    mask_paths: list[str] = []
    workflow_path: str = ""
    workflow_content: str | None = None
    prompt: str = ""
    negative_prompt: str = ""
    #: 手动改写（P3）：true = 跳过 compile_prompt，prompt 原文写正向、用户负向原文写负向
    skip_compile: bool = False
    seed_mode: str = "fixed"       # fixed | random | increment
    seed: int = 100000
    pair_mode: str = "cross"       # cross = 各组全组合；zip = 按选择顺序 1:1 配对
    main_node: str | None = None   # 目标图注入哪个 LoadImage；留空 = 自动识别尺寸基准
    ref_node: str | None = None    # 参考图1；留空 = 其余 LoadImage 按节点号排序
    ref2_node: str | None = None   # 参考图2
    ref3_node: str | None = None   # 参考图3（四图工作流的链尾节点）
    dry_run: bool = False
    output_subfolder: str = ""     # 可选：output 下的相对子目录，空 = 平铺
    # 批量超分页专用（编辑页不传，保持旧行为）：空 = 沿用 QUALITY 常量
    quality: str = ""
    #: 目标朝向：portrait / landscape；空 = 旧默认 portrait
    orientation: str = ""
    #: 标准比例（如 16:9）；空 = 工作流默认比例
    aspect_ratio: str = ""
    job_label: str = ""            # 任务标题前缀；空 = 旧文案「图像编辑」
    clean_source_name: bool = False  # 拷进 input 时保留原文件名（SaveImageFromSource 取源图名）
    idempotency_key: str = ""


# ---------- helpers ----------

def _row_src_path(r) -> Path:
    """历史记录 → 磁盘源图路径（与统一路径解析保持一致，含越界校验）。"""
    path = resolve_image_path(r.filename or "", r.subfolder or "", r.img_type or "output")
    if path is None:
        raise HTTPException(404, f"图片文件不存在: {r.filename}")
    return path


def _collect_sources(ids: list[int], paths: list[str], label: str) -> list[dict]:
    """把「历史图 id」和「磁盘路径」统一成同一种素材描述。

    返回 [{label, path, name, meta}]，meta 用于写进 prompt_params 做溯源。
    """
    out: list[dict] = []
    for i in ids:
        r = Image.get_or_none(Image.id == i)
        if r is None:
            raise HTTPException(404, f"历史记录不存在: {i}")
        src = _row_src_path(r)
        if not src.is_file():
            raise HTTPException(404, f"图片文件不存在: {src}")
        out.append({
            "label": Path(r.filename or "").stem,
            "path": src,
            "name": r.filename or src.name,
            "meta": {
                "source": "history", "history_id": r.id,
                "filename": r.filename, "subfolder": r.subfolder or "",
                "img_type": r.img_type or "output",
            },
        })
    for raw in paths:
        p = Path(raw)
        if not p.is_file():
            raise HTTPException(404, f"图片不存在: {raw}")
        if p.suffix.lower() not in IMAGE_EXT:
            raise HTTPException(400, f"不是支持的图片格式: {raw}")
        out.append({
            "label": p.stem,
            "path": p,
            "name": p.name,
            "meta": {"source": "file", "path": str(p)},
        })
    if not out:
        raise HTTPException(400, f"{label}至少选 1 张")
    return out


def output_prefix(job_id, labels: list[str], max_label: int = 24) -> str:
    """出图文件名前缀：平铺在 output 根目录（不带子目录）。

    不加子目录的原因：项目里的磁盘兜底扫描（_sync_disk_orphans）只扫 output 根目录，
    一旦 job 入库失败，子目录里的图就再也捡不回来了。
    标签截断到 max_label：素材文件名本身可能很长，拼起来容易撞 Windows 260 字符路径上限；
    完整对应关系都记在 gen_jobs.items 里，文件名只需可辨认。
    """
    def cut(s: str) -> str:
        s = (s or "img").strip()
        return s[:max_label]

    parts = "_".join(cut(x) for x in labels if x)
    return f"fs{job_id}_{parts}" if parts else f"fs{job_id}"


def _resolve_seed(mode: str, base: int, idx: int) -> int:
    if mode == "random":
        return random.randint(1, 2 ** 32 - 1)
    if mode == "increment":
        return resolve_seed(base + idx)
    return resolve_seed(base)


def _resolve_size_params(
    caps: dict,
    quality: str,
    aspect_ratio: str,
    orientation: str,
) -> tuple[str, str, str]:
    """按工作流能力归一尺寸参数，返回 (quality, aspect_ratio, orientation)。

    后端二次防护：即使前端误传，工作流没有对应旋钮时也一律回默认值，
    避免留下“参数已发送但永远不生效”的假控件（Qwen21 的 quality/orientation 都是 false）。
    """
    if not caps.get("quality"):
        quality = QUALITY
    if not caps.get("orientation"):
        aspect_ratio, orientation = "", ORIENTATION
    return quality, aspect_ratio, orientation


def workflow_supports_mask(api_workflow: dict) -> bool:
    """工作流是否带遮罩链路。

    两个「可选遮罩」工作流都用 VAEEncodeForInpaint 接 mask；参考类工作流没有该节点，
    前端据此隐藏遮罩区域，避免提交后被静默忽略。
    """
    return any(
        isinstance(node, dict) and node.get("class_type") == "VAEEncodeForInpaint"
        for node in api_workflow.values()
    )


def _sort_node_ids(ids: list[str]) -> list[str]:
    """LoadImage 节点 id 按数字排序；非数字 id 排在后面。"""
    def key(nid: str):
        try:
            return (0, int(nid))
        except ValueError:
            return (1, nid)

    return sorted(ids, key=key)


def _resolve_input_nodes(
    api_wf: dict,
    loads: list[tuple[str, str]],
    main_node: str | None = None,
    ref_node: str | None = None,
    ref2_node: str | None = None,
    ref3_node: str | None = None,
) -> list[dict]:
    """把 LoadImage 分成「目标图 / 参考图1 / 参考图2 / 参考图3」。

    目标图优先取决定输出尺寸的那个 LoadImage（多图工作流里尺寸基准不一定是第一个节点），
    其余节点按节点号升序作为参考图。返回 [{"role", "id"}]，数量与工作流的输入数一致。
    """
    if not loads:
        raise HTTPException(400, "工作流里没有 LoadImage 节点，无法注入素材")
    ids = [nid for nid, _ in loads]
    if len(ids) > MAX_INPUTS:
        raise HTTPException(
            400,
            f"工作流有 {len(ids)} 个 LoadImage，当前最多支持 {MAX_INPUTS} 个输入",
        )

    target = main_node or find_size_source_loadimage(api_wf) or _sort_node_ids(ids)[0]
    if target not in ids:
        raise HTTPException(400, f"指定的目标图节点 {target} 不在工作流的 LoadImage 里")

    others = _sort_node_ids([nid for nid in ids if nid != target])
    refs: list[str] = []
    for index, explicit in enumerate((ref_node, ref2_node, ref3_node)):
        if index >= len(others):
            break
        chosen = explicit or others[index]
        if chosen not in ids:
            raise HTTPException(400, f"指定的参考图节点 {chosen} 不在工作流的 LoadImage 里")
        refs.append(chosen)

    resolved = [{"role": "target", "id": target}]
    for i, nid in enumerate(refs):
        resolved.append({"role": f"ref{i + 1}", "id": nid})

    used = [item["id"] for item in resolved]
    if len(set(used)) != len(used):
        raise HTTPException(400, f"多个角色指向同一个 LoadImage 节点：{used}")
    return resolved


# ---------- routes ----------

@router.post("/editor/faceswap/mask")
def faceswap_save_mask(req: MaskSaveRequest):
    """保存前端涂抹出来的遮罩 PNG（白=重绘，黑=保留），返回可供注入的绝对路径。"""
    prefix = "data:image/png;base64,"
    if not req.data_url.startswith(prefix):
        raise HTTPException(400, "遮罩必须是 PNG dataURL")
    try:
        raw = base64.b64decode(req.data_url[len(prefix):])
    except Exception:
        raise HTTPException(400, "遮罩数据解析失败")

    from PIL import Image as PILImage

    try:
        with PILImage.open(io.BytesIO(raw)) as image:
            if image.format != "PNG":
                raise ValueError("不是 PNG")
            image.verify()
    except Exception:
        raise HTTPException(400, "遮罩不是有效的 PNG")

    digest = hashlib.sha1(raw).hexdigest()[:16]
    mask_dir = settings.library_root / "painted_masks"
    mask_dir.mkdir(parents=True, exist_ok=True)
    path = mask_dir / f"mask_{digest}.png"
    path.write_bytes(raw)
    return {"path": str(path), "size": len(raw)}


@router.post("/editor/faceswap/nodes")
def faceswap_nodes(req: NodesRequest):
    """探测工作流的 LoadImage 节点，供工作台展示「目标图 / 参考图1 / 参考图2 / 参考图3」映射"""
    if not req.workflow_path and not req.workflow_content:
        raise HTTPException(400, "缺少工作流")
    try:
        api_wf = load_workflow(req.workflow_path, req.workflow_content)
    except Exception as e:
        raise HTTPException(400, f"工作流加载失败: {e}")

    loads = find_loadimage_nodes(api_wf)
    inputs = _resolve_input_nodes(api_wf, loads) if loads else []
    return {
        "loadimages": [{"id": nid, "title": title} for nid, title in loads],
        "inputs": inputs,
        "roles": [item["role"] for item in inputs],
        "target": inputs[0]["id"] if inputs else None,
        "refs": [item["id"] for item in inputs[1:]],
        "mask": workflow_supports_mask(api_wf),
        # 兼容旧前端
        "main": inputs[0]["id"] if inputs else None,
        "ref": inputs[1]["id"] if len(inputs) >= 2 else None,
        "max_combos": MAX_COMBOS,
    }


@router.post("/editor/faceswap/batch")
def faceswap_batch(
    req: FaceswapRequest,
    x_idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
):
    """批量图像编辑：目标图 × 参考图 → 逐条推送 ComfyUI"""
    if not (req.main_ids or req.main_paths):
        raise HTTPException(400, "目标图至少选 1 张")
    if req.seed_mode not in ("fixed", "random", "increment"):
        raise HTTPException(400, f"未知的种子模式: {req.seed_mode}")
    if req.pair_mode not in ("cross", "zip"):
        raise HTTPException(400, f"未知的组合方式: {req.pair_mode}")

    workflow_path = req.workflow_path or ""
    if not workflow_path and not req.workflow_content:
        raise HTTPException(400, "缺少工作流")

    # 尺寸参数：只认全局合法档位，非法值直接 400（不静默忽略）；空值保持旧默认
    requested_orientation = (req.orientation or "").strip().lower()
    if requested_orientation and requested_orientation not in ("portrait", "landscape"):
        raise HTTPException(
            400,
            f"不支持的 orientation：{req.orientation}（可用：portrait / landscape）",
        )
    requested_orientation = requested_orientation or ORIENTATION

    raw_ratio = (req.aspect_ratio or "").strip()
    normalized_ratio = normalize_aspect_ratio(raw_ratio) if raw_ratio else None
    if raw_ratio and normalized_ratio is None:
        raise HTTPException(
            400,
            f"不支持的 aspect_ratio：{req.aspect_ratio}"
            f"（可用：{' / '.join(CANONICAL_RATIOS)}）",
        )

    requested_quality = (req.quality or "").strip()
    if requested_quality and normalize_quality(requested_quality) not in QUALITY_SCALES:
        raise HTTPException(
            400,
            f"不支持的 quality：{req.quality}"
            f"（可用：{' / '.join(QUALITY_SCALES)}）",
        )
    requested_quality = requested_quality or QUALITY

    idem_key = request_key(x_idempotency_key, req.idempotency_key)
    existing = find_job_by_idempotency(idem_key, SCOPE_FACESWAP) if idem_key else None
    if existing is not None:
        return {
            "success": True, "job_id": existing["id"], "total": existing["total"],
            "submitted": 0, "errors": [], "idempotent": True, "async": True, "queued": 0,
        }

    # 1) 节点映射（先探测一次，dry_run 与实跑共用同一份判断）
    try:
        api_wf = load_workflow(workflow_path, req.workflow_content)
    except Exception as e:
        raise HTTPException(400, f"工作流加载失败: {e}")
    loads = find_loadimage_nodes(api_wf)
    inputs = _resolve_input_nodes(
        api_wf, loads, req.main_node, req.ref_node, req.ref2_node, req.ref3_node
    )
    roles = [item["role"] for item in inputs]

    # 尺寸能力探测必须在注入前完成：工作流不支持旋钮时忽略请求值（后端二次防护）
    caps = detect_workflow_caps(api_wf)
    quality, aspect_ratio, orientation = _resolve_size_params(
        caps, requested_quality, normalized_ratio or "", requested_orientation,
    )

    try:
        subfolder_preview = expand_subfolder(
            req.output_subfolder, workflow_path=workflow_path, job_id=0,
            quality=quality, orientation=orientation,
        )
    except OutputLocationError as e:
        raise HTTPException(400, str(e))

    # 2) 按角色收集素材；工作流没有的角色不允许提交素材，避免"第四张图悄悄被丢掉"
    if "ref1" not in roles and (req.ref_ids or req.ref_paths):
        raise HTTPException(400, f"该工作流只有 {len(roles)} 个输入，但提交了参考图1")
    if "ref2" not in roles and (req.ref2_ids or req.ref2_paths):
        raise HTTPException(400, f"该工作流只有 {len(roles)} 个输入，但提交了参考图2")
    if "ref3" not in roles and (req.ref3_ids or req.ref3_paths):
        raise HTTPException(400, f"该工作流只有 {len(roles)} 个输入，但提交了参考图3")

    provided = {
        "target": _collect_sources(req.main_ids, req.main_paths, "目标图"),
    }
    if "ref1" in roles:
        provided["ref1"] = _collect_sources(req.ref_ids, req.ref_paths, "参考图1")
    if "ref2" in roles:
        provided["ref2"] = _collect_sources(req.ref2_ids, req.ref2_paths, "参考图2")
    if "ref3" in roles:
        provided["ref3"] = _collect_sources(req.ref3_ids, req.ref3_paths, "参考图3")
    source_groups = [provided[role] for role in roles]

    # 遮罩按目标图顺序一一对应；空字符串表示这张不配遮罩
    targets = provided["target"]
    masks = list(req.mask_paths or [])
    if masks and len(masks) != len(targets):
        raise HTTPException(
            400,
            f"遮罩数量（{len(masks)}）与目标图数量（{len(targets)}）不一致",
        )
    if any(masks):
        if not workflow_supports_mask(api_wf):
            raise HTTPException(400, "该工作流没有遮罩链路，不能使用遮罩")
        for mask_path in masks:
            if mask_path and not Path(mask_path).is_file():
                raise HTTPException(404, f"遮罩文件不存在: {mask_path}")

    # 有遮罩的目标图：把遮罩烘焙进 alpha 通道，得到一张临时目标图
    input_dir_path = settings.input_dir
    composed_paths: dict[int, Path] = {}
    for i, src in enumerate(targets):
        mask_path = masks[i] if masks else ""
        src["meta"]["mask"] = mask_path or None
        if mask_path:
            composed_paths[i] = _compose_masked_target(src["path"], Path(mask_path), input_dir_path)
    target_index = {id(src): i for i, src in enumerate(targets)}

    # 3) 组合方式：cross = 各组笛卡尔积；zip = 按选择顺序每组 1:1 配对
    if len(source_groups) == 1:
        combos = [(src,) for src in source_groups[0]]
    elif req.pair_mode == "zip":
        counts = [len(group) for group in source_groups]
        if len(set(counts)) != 1:
            raise HTTPException(
                400,
                f"1:1 配对要求各组数量相同（当前 {' vs '.join(str(c) for c in counts)}），"
                f"数量不等时请改用「全组合」，或补齐图片后再试",
            )
        combos = list(zip(*source_groups))
    else:
        total = 1
        for group in source_groups:
            total *= len(group)
        if total > MAX_COMBOS:
            raise HTTPException(
                400,
                f"全组合共 {total} 张，超过上限 {MAX_COMBOS} 张；请减少素材或改用「1:1 配对」",
            )
        combos = list(itertools.product(*source_groups))

    # 空组合不能静默入队 0 张（历史上会出现“提交成功但什么都没跑”）
    if not combos:
        raise HTTPException(400, "全组合为空：请至少选择一个参考图")

    node_info = {
        "inputs": inputs,
        "roles": roles,
        "loadimages": loads,
        "target": inputs[0]["id"],
        "refs": [item["id"] for item in inputs[1:]],
        "mask": workflow_supports_mask(api_wf),
        "max_combos": MAX_COMBOS,
        # 兼容旧前端
        "main": inputs[0]["id"],
        "ref": inputs[1]["id"] if len(inputs) >= 2 else None,
    }

    plan = []
    for i, combo in enumerate(combos):
        labels = [src["label"] for src in combo]
        # 记录「保留源图名」：重试时也要按同一份 input 子目录注入，
        # 否则失败重跑会退回 atelier_fs_ 前缀，成品名前后不一致。
        metas = []
        for role, src in zip(roles, combo):
            meta = src["meta"]
            if req.clean_source_name and role == "target" and not meta.get("mask"):
                meta = {**meta, "keep_source_name": True}
            metas.append(meta)
        plan.append({
            "index": i + 1,
            "labels": labels,
            "roles": roles,
            "metas": metas,
            "seed": _resolve_seed(req.seed_mode, req.seed, i),
            "label": " × ".join(labels),
            # 出图文件名规则（默认平铺在 output 根目录；填了子目录才分层），
            # dry_run 时可见，也用于冒烟测试防回归
            "prefix": with_subfolder(subfolder_preview, output_prefix("<job_id>", labels)),
        })

    if req.dry_run:
        return {"success": True, "dry_run": True, "total": len(plan),
                "nodes": node_info, "plan": plan}

    # 纯图像工作流（超分等）没有文本编码节点：不要塞编辑用的默认提示词，
    # 否则任务记录 / 画廊会挂上一段根本没参与执行的假提示词。
    # `caps` 已在上方（注入前）探测过，这里直接复用。
    prompt_text = (req.prompt or "").strip()
    if not prompt_text and caps["prompt"]:
        prompt_text = DEFAULT_PROMPT

    # 4) 建任务记录（前端马上能拿到 job_id 开始轮询）
    items = []
    for p in plan:
        items.append({
            "prompt_id": 0,                      # 编辑任务不来自提示词库
            "seed": p["seed"],
            "prompt_preview": p["label"],
            "inputs": [
                {"role": role, "node": inputs[i]["id"], "meta": p["metas"][i]}
                for i, role in enumerate(roles)
            ],
            "prompt_params": json.dumps({
                "source": "faceswap",
                "prompt": prompt_text,
                "seed": p["seed"],
                "inputs": [
                    {"role": role, "node": inputs[i]["id"], "meta": p["metas"][i]}
                    for i, role in enumerate(roles)
                ],
            }, ensure_ascii=False),
        })
    counts = "×".join(str(len(group)) for group in source_groups)
    for item in items:
        item["status"] = "queued"
    extra = build_job_extra(
        workflow_path, req.workflow_content, req.output_subfolder,
        nodes=node_info, prompt=prompt_text, seed_mode=req.seed_mode,
    )
    if idem_key:
        extra["idempotency_key"] = idem_key
        extra["idempotency_scope"] = SCOPE_FACESWAP
    job_title = f"{req.job_label.strip()} {counts}" if req.job_label.strip() else f"图像编辑 {counts}"
    # 5) 构造每条 workflow 的函数交给后台提交线程；请求立即返回 job_id
    input_dir = str(settings.input_dir)

    def prepare(i: int, ctx) -> dict:
        combo = combos[i]
        api_wf = load_workflow(workflow_path, req.workflow_content)
        inject_prompt(api_wf, {
            "prompt": prompt_text,
            "negative_prompt": req.negative_prompt or "",
            "skip_compile": req.skip_compile,
            "seed": plan[i]["seed"],
            "orientation": orientation,
            "aspect_ratio": aspect_ratio,
            "quality": quality,
        })
        # 按角色逐个注入 LoadImage；有遮罩的目标图换成 alpha 合成后的副本
        for role, src in zip(roles, combo):
            node_id = next(item["id"] for item in inputs if item["role"] == role)
            source_path = src["path"]
            dest_name = _dest_name(src)
            if role == "target":
                index = target_index[id(src)]
                source_path = composed_paths.get(index, source_path)
                mask_path = masks[index] if masks else ""
                if mask_path:
                    # 同一张目标图配不同遮罩时，input 目录里的文件名不能互相覆盖
                    digest = hashlib.sha1(
                        f"{src['path']}|{mask_path}".encode("utf-8")
                    ).hexdigest()[:10]
                    dest_name = f"atelier_fs_{digest}_{src['name']}"
                elif req.clean_source_name:
                    dest_name = _clean_dest_name(src)
            inject_input_image(api_wf, str(source_path), input_dir,
                               node_id=node_id, dest_name=dest_name)
        set_output_prefix(
            api_wf, with_subfolder(ctx.subfolder, output_prefix(ctx.job_id, plan[i]["labels"]))
        )
        set_save_subfolder(api_wf, ctx.subfolder)
        return api_wf

    outcome = submit_spec(SubmitSpec(
        job_type="faceswap", title=job_title, items=items,
        workflow_path=workflow_path, workflow_content=req.workflow_content,
        orientation=orientation, quality=quality, aspect_ratio=aspect_ratio,
        output_subfolder=req.output_subfolder,
        prepare=prepare, mode="queue",
        indexes=tuple(range(len(combos))), extra=extra, apply_output=False,
    ))

    return {
        "success": True,
        "job_id": outcome["job_id"],
        "total": len(combos),
        "submitted": 0,
        "queued": len(combos),
        "errors": [],
        "async": True,
        "nodes": node_info,
        "plan": plan,
    }
