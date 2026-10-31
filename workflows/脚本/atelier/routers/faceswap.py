"""批量图像编辑 —— 目标图 × 参考图 的笛卡尔积，逐条提交 ComfyUI。

一个页面覆盖三种 Flux2 编辑工作流：
  · 单图编辑      1 个 LoadImage：目标图
  · 双图参考      2 个 LoadImage：目标图 + 参考图1
  · 三图参考      3 个 LoadImage：目标图 + 参考图1 + 参考图2

素材可以来自两处（可混用）：
  · 画廊历史图（gen_history 的 id）
  · 磁盘上任意文件夹里的图片（绝对路径，前端有文件夹浏览器）

复用项目既有的一套：
  services.workflow_parser  UI→API 转换 / 提示词·种子注入 / LoadImage 多图注入
  services.comfyui_client   push_prompt
  gen_jobs + 后台 job_monitor_loop  出图完成后自动写入 gen_history（画廊自动可见）

与既有端点的区别：/api/batch_generate 是「多提示词 × 单参考图」，
/api/history/{id}/process 是「单主图 × 单参考图」，这里补的是「多目标 × 多参考」。
"""
import base64
import hashlib
import io
import itertools
import json
import random
import traceback
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import settings
from models import Image
from routers.fsbrowse import IMAGE_EXT
from routers.jobs import create_job, update_job_items
from services.comfyui_client import push_prompt
from services.helpers import _resolve_if_reparse
from services.workflow_parser import (
    find_loadimage_nodes,
    find_size_source_loadimage,
    inject_input_image,
    inject_prompt,
    load_workflow,
    set_output_prefix,
)
from services.batch_control import batch_stop_flag

router = APIRouter(tags=["批量图像编辑"])

DEFAULT_PROMPT = (
    "只修改提示词中描述的部分，其余人物相貌、姿势、构图、服装、背景与光线保持与目标图一致，"
    "自然真实，高清细节"
)

# 一个工作流从上到下最多注入「目标图 + 参考图1 + 参考图2」三张
MAX_INPUTS = 3
# 笛卡尔积上限：三组素材全组合很容易爆炸，超限直接让用户收窄选择
MAX_COMBOS = 10

ROLE_ORDER = ("target", "ref1", "ref2")

# 不涂遮罩时走整图重绘；尺寸/画质由工作流自己决定（本项目里多数编辑工作流用 ImageResizeKJ
# 保持目标图原尺寸，EmptyLatentImage 相关的 quality/orientation 注入对这些工作流是空转）
ORIENTATION = "portrait"
QUALITY = "4K"


class NodesRequest(BaseModel):
    workflow_path: str = ""
    workflow_content: str | None = None


class MaskSaveRequest(BaseModel):
    data_url: str


class FaceswapRequest(BaseModel):
    main_ids: list[int] = []       # 目标图（沿用旧字段名，避免已有调用方失效）
    ref_ids: list[int] = []        # 参考图1
    ref2_ids: list[int] = []       # 参考图2（三图工作流）
    main_paths: list[str] = []     # 磁盘绝对路径，可与 ids 混用
    ref_paths: list[str] = []
    ref2_paths: list[str] = []
    # 遮罩：与目标图顺序一一对应；空字符串 = 这张目标图不配遮罩（整图重绘）
    mask_paths: list[str] = []
    workflow_path: str = ""
    workflow_content: str | None = None
    prompt: str = ""
    negative_prompt: str = ""
    seed_mode: str = "fixed"       # fixed | random | increment
    seed: int = 100000
    pair_mode: str = "cross"       # cross = 各组全组合；zip = 按选择顺序 1:1 配对
    main_node: str | None = None   # 目标图注入哪个 LoadImage；留空 = 自动识别尺寸基准
    ref_node: str | None = None    # 参考图1；留空 = 其余 LoadImage 按节点号排序
    ref2_node: str | None = None   # 参考图2
    dry_run: bool = False


# ---------- helpers ----------

def _row_src_path(r) -> Path:
    """历史记录 → 磁盘源图路径（与 history.py 的取图逻辑一致）"""
    base = settings.comfyui_root / ("input" if r.img_type == "input" else "output")
    base = _resolve_if_reparse(base)
    return base / (r.subfolder or "") / r.filename if r.subfolder else base / r.filename


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


def _dest_name(src: dict) -> str:
    """拷进 ComfyUI input 目录时用的稳定文件名：同一条素材只拷一份，不同素材不撞名。"""
    h = hashlib.sha1(str(src["path"]).lower().encode("utf-8")).hexdigest()[:10]
    return f"pb_fs_{h}_{src['name']}"


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
        return base + idx
    return base


def workflow_supports_mask(api_workflow: dict) -> bool:
    """工作流是否带遮罩链路。

    两个「可选遮罩」工作流都用 VAEEncodeForInpaint 接 mask；三图参考工作流没有该节点，
    前端据此隐藏遮罩区域，避免提交后被静默忽略。
    """
    return any(
        isinstance(node, dict) and node.get("class_type") == "VAEEncodeForInpaint"
        for node in api_workflow.values()
    )


def _compose_masked_target(target_path: Path, mask_path: Path, dest_dir: Path) -> Path:
    """把遮罩烘焙进目标图 alpha 通道，返回可直接注入 LoadImage 的 PNG。

    工作流里 LoadImage 的 MASK = 1 - alpha，因此「要改的区域」alpha 必须为 0。
    · 遮罩图真的带透明通道 → 透明区 = 要改
    · 否则按亮度 → 白色 = 要改（兼容最常见的黑白遮罩图）
    其余区域 alpha=255，工作流的归约链会原样保留这些像素。
    """
    from PIL import Image as PILImage, ImageOps

    with PILImage.open(target_path) as raw:
        image = ImageOps.exif_transpose(raw).convert("RGB")

    with PILImage.open(mask_path) as raw_mask:
        mask = ImageOps.exif_transpose(raw_mask)
        alpha = mask.convert("RGBA").getchannel("A")
        if alpha.getextrema()[0] < 255:
            # 透明区域 = 要重绘；反相后 255 = 重绘
            repaint = ImageOps.invert(alpha)
        else:
            # 没有真正的透明区域：按亮度取白色区域
            repaint = mask.convert("L")
        repaint = repaint.resize(image.size, PILImage.Resampling.BILINEAR)

    output = image.convert("RGBA")
    output.putalpha(ImageOps.invert(repaint))

    digest = hashlib.sha1(
        f"{target_path}|{mask_path}|{target_path.stat().st_mtime}|{mask_path.stat().st_mtime}".encode("utf-8")
    ).hexdigest()[:12]
    dest = Path(dest_dir) / f"pb_edit_{digest}.png"
    output.save(dest, "PNG")
    return dest


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
) -> list[dict]:
    """把 LoadImage 分成「目标图 / 参考图1 / 参考图2」。

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
    refs = []
    if others:
        refs.append(ref_node or others[0])
    if len(others) >= 2:
        refs.append(ref2_node or others[1])

    resolved = [{"role": "target", "id": target}]
    for i, nid in enumerate(refs):
        resolved.append({"role": f"ref{i + 1}", "id": nid})

    used = [item["id"] for item in resolved]
    if len(set(used)) != len(used):
        raise HTTPException(400, f"多个角色指向同一个 LoadImage 节点：{used}")
    return resolved


# ---------- routes ----------

@router.post("/faceswap/mask")
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
    mask_dir = settings.project_root / "painted_masks"
    mask_dir.mkdir(parents=True, exist_ok=True)
    path = mask_dir / f"mask_{digest}.png"
    path.write_bytes(raw)
    return {"path": str(path), "size": len(raw)}


@router.post("/faceswap/nodes")
def faceswap_nodes(req: NodesRequest):
    """探测工作流的 LoadImage 节点，供工作台展示「目标图 / 参考图1 / 参考图2」映射"""
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


@router.post("/faceswap/batch")
def faceswap_batch(req: FaceswapRequest):
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

    # 1) 节点映射（先探测一次，dry_run 与实跑共用同一份判断）
    try:
        api_wf = load_workflow(workflow_path, req.workflow_content)
    except Exception as e:
        raise HTTPException(400, f"工作流加载失败: {e}")
    loads = find_loadimage_nodes(api_wf)
    inputs = _resolve_input_nodes(api_wf, loads, req.main_node, req.ref_node, req.ref2_node)
    roles = [item["role"] for item in inputs]

    # 2) 按角色收集素材；工作流没有的角色不允许提交素材，避免"第四张图悄悄被丢掉"
    if "ref1" not in roles and (req.ref_ids or req.ref_paths):
        raise HTTPException(400, f"该工作流只有 {len(roles)} 个输入，但提交了参考图1")
    if "ref2" not in roles and (req.ref2_ids or req.ref2_paths):
        raise HTTPException(400, f"该工作流只有 {len(roles)} 个输入，但提交了参考图2")

    provided = {
        "target": _collect_sources(req.main_ids, req.main_paths, "目标图"),
    }
    if "ref1" in roles:
        provided["ref1"] = _collect_sources(req.ref_ids, req.ref_paths, "参考图1")
    if "ref2" in roles:
        provided["ref2"] = _collect_sources(req.ref2_ids, req.ref2_paths, "参考图2")
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
    input_dir_path = settings.comfyui_root / "input"
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
        plan.append({
            "index": i + 1,
            "labels": labels,
            "roles": roles,
            "metas": [src["meta"] for src in combo],
            "seed": _resolve_seed(req.seed_mode, req.seed, i),
            "label": " × ".join(labels),
            # 出图文件名规则（平铺在 output 根目录，不带子目录），dry_run 时可见，
            # 也用于冒烟测试防回归
            "prefix": output_prefix("<job_id>", labels),
        })

    if req.dry_run:
        return {"success": True, "dry_run": True, "total": len(plan),
                "nodes": node_info, "plan": plan}

    prompt_text = (req.prompt or "").strip() or DEFAULT_PROMPT

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
    job_id = create_job(
        "faceswap", f"图像编辑 {counts}",
        items, workflow_path, ORIENTATION, QUALITY,
        extra={"nodes": node_info, "prompt": prompt_text, "seed_mode": req.seed_mode},
    )

    # 5) 逐条构造并入队。push_prompt 只是把任务塞进 ComfyUI 队列，很快，
    #    用同步循环与既有 batch_generate 一致；真正的执行进度由 gen_jobs + 监控协程跟踪。
    input_dir = str(settings.comfyui_root / "input")
    ok = 0
    errors: list[dict] = []

    for i, combo in enumerate(combos):
        if batch_stop_flag.is_set():
            items[i]["status"] = "cancelled"
            items[i]["error"] = "已取消"
            errors.append({"index": i, "error": "已取消"})
            continue
        try:
            api_wf = load_workflow(workflow_path, req.workflow_content)
            inject_prompt(api_wf, {
                "prompt": prompt_text,
                "negative_prompt": req.negative_prompt or "",
                "seed_override": plan[i]["seed"],
                "orientation": ORIENTATION,
                "quality": QUALITY,
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
                        dest_name = f"pb_fs_{digest}_{src['name']}"
                inject_input_image(api_wf, str(source_path), input_dir,
                                   node_id=node_id, dest_name=dest_name)
            # 输出名带「任务号 + 组合」，配对关系一眼可查。
            # 平铺在 output 根目录（不加子目录）：一是与项目里其它出图习惯一致，
            # 二是磁盘兜底扫描（_sync_disk_orphans）只扫根目录，平铺才能被它捡回来。
            set_output_prefix(api_wf, output_prefix(job_id, plan[i]["labels"]))

            result = push_prompt(api_wf)
            items[i]["comfyui_prompt_id"] = result.get("prompt_id", "")
            items[i]["status"] = "pending"
            ok += 1
        except Exception as e:
            traceback.print_exc()
            items[i]["status"] = "error"
            items[i]["error"] = str(e)
            errors.append({"index": i, "label": plan[i]["label"], "error": str(e)})

    batch_stop_flag.clear()
    update_job_items(job_id, items, status="running" if ok else "error")

    return {
        "success": ok > 0,
        "job_id": job_id,
        "total": len(combos),
        "submitted": ok,
        "errors": errors,
        "nodes": node_info,
        "plan": plan,
    }
