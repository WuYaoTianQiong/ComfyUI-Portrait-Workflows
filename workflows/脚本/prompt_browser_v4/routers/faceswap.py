"""批量换脸 —— N 主图 × M 参考图 的笛卡尔积，逐条提交 ComfyUI。

素材可以来自两处（可混用）：
  · 画廊历史图（gen_history 的 id）
  · 磁盘上任意文件夹里的图片（绝对路径，前端有文件夹浏览器）

复用项目既有的一套：
  services.workflow_parser  UI→API 转换 / 提示词·种子注入 / LoadImage 双图注入
  services.comfyui_client   push_prompt
  gen_jobs + 后台 job_monitor_loop  出图完成后自动写入 gen_history（画廊自动可见）

与既有端点的区别：/api/batch_generate 是「多提示词 × 单参考图」，
/api/history/{id}/process 是「单主图 × 单参考图」，这里补的是「多主图 × 多参考图」。
"""
import hashlib
import json
import random
import traceback
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import settings
from models import GenHistory as Gh
from routers.fsbrowse import IMAGE_EXT
from routers.jobs import create_job, update_job_items
from services.comfyui_client import push_prompt
from services.helpers import _resolve_if_reparse
from services.workflow_parser import (
    find_loadimage_nodes,
    inject_input_image,
    inject_prompt,
    load_workflow,
    set_output_prefix,
)
from state import batch_stop_flag

router = APIRouter(tags=["批量换脸"])

DEFAULT_PROMPT = (
    "保持主图人物的姿势、构图、服装、背景与光线完全不变，"
    "只把人物的面部替换成参考图中人物的脸，脸型与五官保持一致，自然真实，写实人像摄影，高清细节"
)

# 不涂遮罩时走整图重绘；尺寸/画质由工作流自己决定（本项目里多数换脸工作流用 ImageResizeKJ
# 保持主图原尺寸，EmptyLatentImage 相关的 quality/orientation 注入对这些工作流是空转）
ORIENTATION = "portrait"
QUALITY = "4K"


class NodesRequest(BaseModel):
    workflow_path: str = ""
    workflow_content: str | None = None


class FaceswapRequest(BaseModel):
    main_ids: list[int] = []
    ref_ids: list[int] = []
    main_paths: list[str] = []     # 磁盘绝对路径，可与 main_ids 混用
    ref_paths: list[str] = []
    workflow_path: str = ""
    workflow_content: str | None = None
    prompt: str = ""
    negative_prompt: str = ""
    seed_mode: str = "fixed"       # fixed | random | increment
    seed: int = 100000
    pair_mode: str = "cross"       # cross = 主图×参考图 全组合；zip = 按选择顺序 1:1 配对
    main_node: str | None = None   # 主图注入哪个 LoadImage；留空 = 第一个 LoadImage
    ref_node: str | None = None    # 参考图注入哪个 LoadImage；留空 = 第二个 LoadImage
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
        r = Gh.get_or_none(Gh.id == i)
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


def output_prefix(job_id, main_label: str, ref_label: str, max_label: int = 24) -> str:
    """出图文件名前缀：平铺在 output 根目录（不带子目录）。

    不加子目录的原因：项目里的磁盘兜底扫描（_sync_disk_orphans）只扫 output 根目录，
    一旦 job 入库失败，子目录里的图就再也捡不回来了。
    标签截断到 max_label：素材文件名本身可能很长，拼起来容易撞 Windows 260 字符路径上限；
    完整对应关系都记在 gen_jobs.items 里，文件名只需可辨认。
    """
    def cut(s: str) -> str:
        s = (s or "img").strip()
        return s[:max_label]

    return f"fs{job_id}_{cut(main_label)}_{cut(ref_label)}"


def _resolve_seed(mode: str, base: int, idx: int) -> int:
    if mode == "random":
        return random.randint(1, 2 ** 32 - 1)
    if mode == "increment":
        return base + idx
    return base


def _resolve_node_pair(loads: list[tuple[str, str]], main_node: str | None, ref_node: str | None):
    """确定主图/参考图各自的 LoadImage 节点 id"""
    if not loads:
        raise HTTPException(400, "工作流里没有 LoadImage 节点，无法注入素材")
    main = main_node or loads[0][0]
    if ref_node:
        ref = ref_node
    elif len(loads) >= 2:
        ref = loads[1][0]
    else:
        raise HTTPException(
            400,
            f"工作流只找到 1 个 LoadImage（节点 {loads[0][0]}），无法同时注入主图和参考图；"
            f"请在「高级」里手动指定参考图节点",
        )
    if main == ref:
        raise HTTPException(400, f"主图与参考图指向同一个节点 {main}，两张图会互相覆盖")
    return main, ref


# ---------- routes ----------

@router.post("/faceswap/nodes")
def faceswap_nodes(req: NodesRequest):
    """探测工作流的 LoadImage 节点，供工作台展示「主图 / 参考图」映射与默认值"""
    if not req.workflow_path and not req.workflow_content:
        raise HTTPException(400, "缺少工作流")
    try:
        api_wf = load_workflow(req.workflow_path, req.workflow_content)
    except Exception as e:
        raise HTTPException(400, f"工作流加载失败: {e}")

    loads = find_loadimage_nodes(api_wf)
    return {
        "loadimages": [{"id": nid, "title": title} for nid, title in loads],
        "main": loads[0][0] if loads else None,
        "ref": loads[1][0] if len(loads) >= 2 else None,
    }


@router.post("/faceswap/batch")
def faceswap_batch(req: FaceswapRequest):
    """批量换脸：主图集合 × 参考图集合 → 逐条推送 ComfyUI"""
    if not (req.main_ids or req.main_paths) or not (req.ref_ids or req.ref_paths):
        raise HTTPException(400, "主图与参考图各至少选 1 张")
    if req.seed_mode not in ("fixed", "random", "increment"):
        raise HTTPException(400, f"未知的种子模式: {req.seed_mode}")
    if req.pair_mode not in ("cross", "zip"):
        raise HTTPException(400, f"未知的组合方式: {req.pair_mode}")

    workflow_path = req.workflow_path or ""
    if not workflow_path and not req.workflow_content:
        raise HTTPException(400, "缺少工作流")

    mains = _collect_sources(req.main_ids, req.main_paths, "主图")
    refs = _collect_sources(req.ref_ids, req.ref_paths, "参考图")

    # 1) 节点映射（先探测一次，dry_run 与实跑共用同一份判断）
    try:
        api_wf = load_workflow(workflow_path, req.workflow_content)
    except Exception as e:
        raise HTTPException(400, f"工作流加载失败: {e}")
    loads = find_loadimage_nodes(api_wf)
    main_node, ref_node = _resolve_node_pair(loads, req.main_node, req.ref_node)

    # 组合方式：cross = 笛卡尔积（主图×参考图）；zip = 按选择顺序 1:1 配对
    if req.pair_mode == "zip":
        if len(mains) != len(refs):
            raise HTTPException(
                400,
                f"1:1 配对要求主图与参考图数量相同（当前 {len(mains)} vs {len(refs)}），"
                f"数量不等时请改用「全组合」，或补齐图片后再试",
            )
        combos = list(zip(mains, refs))
    else:
        combos = [(m, r) for m in mains for r in refs]
    node_info = {"main": main_node, "ref": ref_node, "loadimages": loads}

    plan = [
        {
            "index": i + 1,
            "main_label": m["label"],
            "ref_label": r["label"],
            "main_meta": m["meta"],
            "ref_meta": r["meta"],
            "seed": _resolve_seed(req.seed_mode, req.seed, i),
            "label": f"{m['label']} × {r['label']}",
            # 出图文件名规则（平铺在 output 根目录，不带子目录），dry_run 时可见，
            # 也用于冒烟测试防回归
            "prefix": output_prefix("<job_id>", m["label"], r["label"]),
        }
        for i, (m, r) in enumerate(combos)
    ]

    if req.dry_run:
        return {"success": True, "dry_run": True, "total": len(plan),
                "nodes": node_info, "plan": plan}

    prompt_text = (req.prompt or "").strip() or DEFAULT_PROMPT

    # 2) 建任务记录（前端马上能拿到 job_id 开始轮询）
    items = []
    for p in plan:
        items.append({
            "prompt_id": 0,                      # 换脸任务不来自提示词库
            "seed": p["seed"],
            "prompt_preview": p["label"],
            "main_meta": p["main_meta"],
            "ref_meta": p["ref_meta"],
            "prompt_params": json.dumps({
                "source": "faceswap",
                "prompt": prompt_text,
                "seed": p["seed"],
                "main": p["main_meta"],
                "ref": p["ref_meta"],
                "main_node": main_node,
                "ref_node": ref_node,
            }, ensure_ascii=False),
        })
    job_id = create_job(
        "faceswap", f"批量换脸 {len(mains)}×{len(refs)}",
        items, workflow_path, ORIENTATION, QUALITY,
        extra={"nodes": node_info, "prompt": prompt_text, "seed_mode": req.seed_mode},
    )

    # 3) 逐条构造并入队。push_prompt 只是把任务塞进 ComfyUI 队列，很快，
    #    用同步循环与既有 batch_generate 一致；真正的执行进度由 gen_jobs + 监控协程跟踪。
    input_dir = str(settings.comfyui_root / "input")
    ok = 0
    errors: list[dict] = []

    for i, (m, r) in enumerate(combos):
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
            # 双图注入：显式指定节点；用稳定的目标名让同一张源图只拷一份
            inject_input_image(api_wf, str(m["path"]), input_dir,
                               node_id=main_node, dest_name=_dest_name(m))
            inject_input_image(api_wf, str(r["path"]), input_dir,
                               node_id=ref_node, dest_name=_dest_name(r))
            # 输出名带「任务号 + 组合」，配对关系一眼可查。
            # 平铺在 output 根目录（不加子目录）：一是与项目里其它出图习惯一致，
            # 二是磁盘兜底扫描（_sync_disk_orphans）只扫根目录，平铺才能被它捡回来。
            set_output_prefix(api_wf, output_prefix(job_id, m["label"], r["label"]))

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
