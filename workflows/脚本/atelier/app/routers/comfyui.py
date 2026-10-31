"""ComfyUI 交互 —— 工作流列表 / 跑图 / 批量生成 / 缺图补跑。

图片与缩略图服务在 `routers/media.py`；运行状态与配置在 `routers/system.py`
（P3 路由资源化后，裸动词 `/api/system/status`、`/api/system/config` 已收编到 `/api/system/*`）。
"""
import json
import logging
import os
import traceback

from fastapi import APIRouter, HTTPException, Query
from app.schemas import WorkflowListResponse
from pydantic import BaseModel

from app.models import Prompt, PromptCategory, Category
from app.services.fragment_syntax import strip_headers
from app.services.workflow_catalog import find_default_workflow, list_valid_workflows
from app.services.workflow_parser import load_workflow, inject_prompt
from app.services.comfyui_client import push_prompt
from app.routers.jobs import create_job, update_job_items
from app.services.batch_control import batch_stop_flag

router = APIRouter(tags=["ComfyUI"])
logger = logging.getLogger(__name__)


# ---------- Pydantic schemas ----------

class RunRequest(BaseModel):
    id: int
    workflow_path: str = ""
    workflow_content: str | None = None
    orientation: str = "portrait"
    quality: str = "4K"
    seed_override: int = 0


class RunTextRequest(BaseModel):
    prompt: str = ""
    negative_prompt: str = ""
    workflow_path: str = ""
    workflow_content: str | None = None
    orientation: str = "portrait"
    quality: str = "4K"
    seed: int = 0
    source_prompt_id: int = 0  # 试跑来源提示词 ID，0 表示无来源


class BatchItem(BaseModel):
    prompt_id: int
    seed: int = 0
    # 批量替换碎片用：只替换本次注入的文本，不写回提示词库
    prompt_override: str | None = None


class BatchRequest(BaseModel):
    items: list[BatchItem]
    workflow_path: str = ""
    workflow_content: str | None = None
    orientation: str = "portrait"
    quality: str = "4K"
    title: str = "批量生成"


class GenerateMissingRequest(BaseModel):
    """为所有「没有生成过图片」的提示词批量出图"""
    workflow_path: str = ""
    workflow_content: str | None = None
    orientation: str = "portrait"
    quality: str = "4K"
    prompt_ids: list[int] | None = None  # 可选：仅补全指定提示词（与缺图集合取交集）


# ---------- 工作流校验 ----------

@router.get("/validate_workflow")
def validate_workflow(path: str = Query("")):
    """验证工作流文件是否合法（仅检查格式，不要求特定节点类型）"""
    if not path or not os.path.exists(path):
        return {"valid": False, "error": "文件不存在"}
    try:
        with open(path, "r", encoding="utf-8") as f:
            wf = json.load(f)
        # 仅检查是否为合法的 ComfyUI 工作流格式（API 格式或 UI 格式）
        if isinstance(wf, dict):
            # API 格式：至少包含一个节点（key 为数字字符串，value 含 class_type）
            if any("class_type" in v for v in wf.values() if isinstance(v, dict)):
                return {"valid": True, "name": os.path.basename(path)}
            # UI 格式：包含 nodes 数组
            if "nodes" in wf and isinstance(wf["nodes"], list):
                return {"valid": True, "name": os.path.basename(path)}
        return {"valid": False, "error": "不支持的工作流格式"}
    except Exception as e:
        return {"valid": False, "error": str(e)}


# ---------- 工作流列表 ----------

@router.get("/workflows", response_model=WorkflowListResponse)
def list_workflows(sort: str = Query("mtime")):
    """列出所有可用工作流"""
    results = list_valid_workflows()

    if sort == "mtime":
        results.sort(key=lambda x: x["mtime"], reverse=True)
    else:
        results.sort(key=lambda x: x["name"])

    return {"workflows": results, "default": find_default_workflow()}


# ---------- 单图跑图 ----------

@router.post("/runs")
def run_prompt(req: RunRequest):
    """单图生成"""
    p = Prompt.get_or_none(Prompt.id == req.id)
    if p is None:
        raise HTTPException(404, "提示词不存在")

    workflow_path = req.workflow_path or ""
    if not workflow_path:
        raise HTTPException(400, "缺少工作流路径")

    try:
        # 加载并解析工作流
        api_wf = load_workflow(workflow_path, req.workflow_content)

        # 注入提示词：传 ComfyUI 时去掉【】碎片标题
        clean_prompt = strip_headers(p.prompt)
        prompt_data = {
            "prompt": clean_prompt,
            "negative_prompt": p.negative_prompt or "",
            "seed": p.seed or 0,
            "seed_override": req.seed_override,
            "orientation": req.orientation,
            "quality": req.quality,
        }
        inject_prompt(api_wf, prompt_data)

        # 创建任务记录
        prompt_params = {
            "prompt": clean_prompt,
            "negative_prompt": p.negative_prompt or "",
            "seed": req.seed_override or (p.seed or 0),
            "steps": p.steps, "cfg_scale": p.cfg_scale,
            "sampler": p.sampler or "", "model": p.model or "",
            "width": p.width, "height": p.height,
            "source": "prompt_run",
        }
        items = [{
            "prompt_id": req.id,
            "seed": req.seed_override or (p.seed or 0),
            "prompt_preview": (p.name or p.prompt or "")[:40],
            "prompt_params": json.dumps(prompt_params, ensure_ascii=False),
        }]
        job_id = create_job("single", "单图生成", items, workflow_path, req.orientation, req.quality)

        # 推送 ComfyUI
        result = push_prompt(api_wf)
        comfy_pid = result.get("prompt_id", "")
        items[0]["comfyui_prompt_id"] = comfy_pid
        items[0]["status"] = "pending"
        update_job_items(job_id, items, status="running")

        dims = ""
        if p.width and p.height:
            dims = f"{p.width}×{p.height}"

        return {"success": True, "job_id": job_id, "result": result, "dimensions": dims}

    except FileNotFoundError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        logger.exception("跑图失败(prompt=%s, 工作流=%s)", req.id, workflow_path)
        raise HTTPException(500, str(e))
    except Exception as e:
        logger.exception("跑图失败(prompt=%s, 工作流=%s, 自定义内容=%s)",
                         req.id, workflow_path, bool(req.workflow_content))
        raise HTTPException(500, f"{type(e).__name__}: {e}")


# ---------- 裸 prompt 跑图（无需 prompt_id） ----------

@router.post("/runs/text")
def run_text_prompt(req: RunTextRequest):
    """直接提交 prompt 文本生成，无需数据库中已有记录"""
    workflow_path = req.workflow_path or ""
    if not workflow_path:
        raise HTTPException(400, "缺少工作流路径")

    try:
        api_wf = load_workflow(workflow_path, req.workflow_content)

        prompt_data = {
            "prompt": strip_headers(req.prompt),
            "negative_prompt": req.negative_prompt or "",
            "seed": req.seed or 0,
            "orientation": req.orientation,
            "quality": req.quality,
        }
        inject_prompt(api_wf, prompt_data)

        prompt_params = {
            "prompt": req.prompt or "",
            "negative_prompt": req.negative_prompt or "",
            "seed": req.seed or 0,
            "source": "text_run",
            "source_prompt_id": req.source_prompt_id or 0,
        }
        # 试跑若指定了来源提示词，直接关联到该提示词的 history（否则关弹窗就找不到了）
        linked_prompt_id = req.source_prompt_id or 0
        items = [{
            "prompt_id": linked_prompt_id,
            "seed": req.seed or 0,
            "prompt_preview": (req.prompt or "")[:40],
            "prompt_params": json.dumps(prompt_params, ensure_ascii=False),
        }]
        job_id = create_job("single", "文本跑图", items, workflow_path, req.orientation, req.quality)

        result = push_prompt(api_wf)
        comfy_pid = result.get("prompt_id", "")
        items[0]["comfyui_prompt_id"] = comfy_pid
        items[0]["status"] = "pending"
        update_job_items(job_id, items, status="running")

        return {"success": True, "job_id": job_id, "result": result}

    except FileNotFoundError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"{type(e).__name__}: {e}")


# ---------- 批量生成 ----------

@router.post("/runs/batch")
def batch_generate(req: BatchRequest):
    """批量 / 变体生成"""
    if not req.items:
        raise HTTPException(400, "缺少 items")

    workflow_path = req.workflow_path or ""

    # 创建任务记录
    items_raw = [{"prompt_id": it.prompt_id, "seed": it.seed} for it in req.items]
    job_id = create_job(
        "batch", req.title,
        items_raw, workflow_path,
        req.orientation, req.quality,
    )

    results = []
    errors = []

    for i, item in enumerate(req.items):
        # 检查停止标志
        if batch_stop_flag.is_set():
            items_raw[i]["status"] = "cancelled"
            items_raw[i]["error"] = "已取消"
            errors.append({"index": i, "prompt_id": item.prompt_id, "error": "已取消"})
            continue

        pid = item.prompt_id
        if not pid:
            items_raw[i]["status"] = "error"
            items_raw[i]["error"] = "缺少 prompt_id"
            errors.append({"index": i, "error": "缺少 prompt_id"})
            continue

        p = Prompt.get_or_none(Prompt.id == pid)
        if p is None:
            items_raw[i]["status"] = "error"
            items_raw[i]["error"] = f"提示词 {pid} 不存在"
            errors.append({"index": i, "prompt_id": pid, "error": f"提示词 {pid} 不存在"})
            continue

        try:
            api_wf = load_workflow(workflow_path, req.workflow_content)
            # 有 override 时用替换后的文本出图，其余参数仍取原提示词；
            # strip_headers 与普通批量出图保持一致（【类型】标题不注入模型）。
            prompt_text = (
                strip_headers(item.prompt_override)
                if item.prompt_override
                else strip_headers(p.prompt)
            )
            prompt_data = {
                "prompt": prompt_text,
                "negative_prompt": p.negative_prompt or "",
                "seed": p.seed or 0,
                "seed_override": item.seed,
                "steps": p.steps,
                "cfg_scale": p.cfg_scale,
                "sampler": p.sampler,
                "orientation": req.orientation,
                "quality": req.quality,
            }
            inject_prompt(api_wf, prompt_data)

            result = push_prompt(api_wf)
            comfy_pid = result.get("prompt_id", "")
            items_raw[i]["comfyui_prompt_id"] = comfy_pid
            items_raw[i]["status"] = "pending"
            items_raw[i]["prompt_preview"] = (
                item.prompt_override or p.name or p.prompt or ""
            )[:40]
            results.append({"index": i, "prompt_id": pid, "comfyui_prompt_id": comfy_pid})
        except Exception as e:
            traceback.print_exc()
            items_raw[i]["status"] = "error"
            items_raw[i]["error"] = str(e)
            errors.append({"index": i, "prompt_id": pid, "error": str(e)})

    batch_stop_flag.clear()
    status = "running" if results else "error"
    update_job_items(job_id, items_raw, status=status)

    return {"success": len(results) > 0, "job_id": job_id, "results": results, "errors": errors}


# ---------- 补全缺图 ----------

def _missing_prompt_ids():
    """返回所有「没有生成过图片」的提示词 ID 列表（DB 关联判定）。

    缺图判定：Image 中不存在该 prompt_id 的未删除记录，即视为缺图。
    """
    from app.models import Image

    have_ids = {
        r.prompt_id
        for r in Image
        .select(Image.prompt_id)
        .where(
            (Image.is_deleted == False)
            & (Image.prompt_id.is_null(False))
        )
        .distinct()
    }
    return [p.id for p in Prompt.select(Prompt.id).order_by(Prompt.id)
            if p.id not in have_ids]


@router.get("/generate_missing/count")
def generate_missing_count():
    """仅统计缺图提示词数量，不触发出图（供前端二次确认使用）。"""
    missing_ids = _missing_prompt_ids()
    total = Prompt.select().count()
    return {"count": len(missing_ids), "total": total}


@router.get("/generate_missing/list")
def generate_missing_list():
    """返回所有缺图提示词的概要清单，供前端审核模态框展示与勾选。"""
    missing_ids = _missing_prompt_ids()
    if not missing_ids:
        return {"items": []}
    # 分类映射（一个提示词可能多个分类）
    cat_rows = (
        PromptCategory
        .select(PromptCategory.prompt, Category.name)
        .join(Category)
        .where(PromptCategory.prompt.in_(missing_ids))
    )
    cat_map: dict = {}
    for r in cat_rows:
        cat_map.setdefault(r.prompt_id, []).append(r.category.name)
    prompts = {p.id: p for p in Prompt.select().where(Prompt.id.in_(missing_ids))}
    items = []
    for pid in missing_ids:
        p = prompts.get(pid)
        if not p:
            continue
        items.append({
            "id": p.id,
            "name": p.name or "(未命名)",
            "category": ", ".join(cat_map.get(pid, [])),
            "steps": p.steps,
            "cfg_scale": p.cfg_scale,
            "sampler": p.sampler,
            "seed": p.seed,
            "model": p.model,
            "width": p.width,
            "height": p.height,
        })
    return {"items": items}


@router.post("/generate_missing")
def generate_missing(req: GenerateMissingRequest):
    """为所有「没有生成过图片」的提示词统一批量出图。

    缺图判定（DB 关联）：Image 中不存在该 prompt_id 的未删除记录，即视为缺图。
    每条提示词使用其自身保存的参数（steps/cfg/sampler/seed/分辨率），
    实际出图逻辑完全复用 batch_generate。
    """
    # 缺图集合（DB 关联判定）：复用辅助函数
    missing_ids = _missing_prompt_ids()
    if req.prompt_ids:  # 仅补全用户勾选的子集（与缺图集合取交集，防御重复出图）
        want = set(req.prompt_ids)
        missing_ids = [pid for pid in missing_ids if pid in want]

    if not missing_ids:
        return {
            "success": True, "job_id": None, "count": 0,
            "results": [], "errors": [],
            "message": "所有提示词都已有图片，无需补全",
        }

    batch_req = BatchRequest(
        items=[BatchItem(prompt_id=pid, seed=0) for pid in missing_ids],
        workflow_path=req.workflow_path,
        workflow_content=req.workflow_content,
        orientation=req.orientation,
        quality=req.quality,
        title=f"补全缺图 ({len(missing_ids)} 条)",
    )
    result = batch_generate(batch_req)
    result["count"] = len(missing_ids)
    return result
