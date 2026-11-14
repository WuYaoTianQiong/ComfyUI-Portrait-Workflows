"""图片元数据：尺寸/大小、采集时间、方向分面、主模型名。

从原 `helpers.py` 拆出。这里只关心"从一张图里读出什么"，路径解析统一走
`app.services.paths.resolve_image_path`（原来三个函数各写了一遍同样的
subfolder 逐段 junction 解析）。
"""
import json
import logging
from datetime import datetime, timezone

from app.services import image_formats  # noqa: F401  注册 HEIC/HEIF 解码
from app.services.paths import resolve_image_path

logger = logging.getLogger("atelier.image_meta")


def captured_at_for_image(filename: str, subfolder: str, img_type: str):
    """图片的真实生成时间（文件 mtime）；取不到返回 None。

    入库时写进 gen_history.captured_at。created_at 是"入库时间"，同步/扫描进来的
    图片会全部落在导入那一刻，画廊按 created_at 排序等于按导入批次排序。
    """
    path = resolve_image_path(filename, subfolder or "", img_type or "output")
    if path is None:
        return None
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None


def get_image_metadata(filename: str, subfolder: str, img_type: str) -> dict:
    """读取图片文件的分辨率和大小（始终从磁盘读取）"""
    path = resolve_image_path(filename, subfolder, img_type)
    if path is None:
        return {}
    try:
        file_size = path.stat().st_size
        from PIL import Image as PILImage

        with PILImage.open(path) as img:
            width, height = img.size
        return {"width": width, "height": height, "file_size": file_size}
    except Exception:
        return {}


def get_image_metadata_fast(filename: str, subfolder: str, img_type: str,
                            prompt_params: str | None = None) -> dict:
    """优化的元数据读取：优先从 prompt_params JSON 获取宽高（已在同步/入库时写入），
    file_size 用 os.stat 秒读（无需 PIL），仅当 prompt_params 无宽高时回退 PIL 解码。

    性能：page_size=1000 时 PIL 打开 1000 次大 PNG 可耗时 5-20s 导致前端超时。
    本函数将 1000 次 PIL 打开的极端情况降为 0 次（所有图片都有 prompt_params 时）
    或极少次（仅缺失图片）。
    """
    path = resolve_image_path(filename, subfolder, img_type)
    if path is None:
        return {}

    try:
        file_size = path.stat().st_size
    except OSError:
        file_size = 0

    # ---- 宽/高优先从 prompt_params JSON 取（同步/入库时已写入）----
    width = None
    height = None
    if prompt_params:
        try:
            pp = json.loads(prompt_params) if isinstance(prompt_params, str) else prompt_params
            w = pp.get("width")
            h = pp.get("height")
            if w and h:
                width, height = int(w), int(h)
        except Exception:
            pass

    # ---- 回退：PIL 打开读取 ----
    if not width or not height:
        try:
            from PIL import Image as PILImage

            with PILImage.open(path) as img:
                width, height = img.size
        except Exception:
            pass

    meta = {}
    if file_size:
        meta["file_size"] = file_size
    if width and height:
        meta["width"] = width
        meta["height"] = height
    return meta


def compute_orientation(width, height):
    """根据像素宽高返回方向分面值：横图 / 竖图 / 方图；宽高缺失返回 None。"""
    if not width or not height:
        return None
    # 容忍 2% 以内的取整误差，避免近似正方形被误判
    if abs(width - height) <= max(width, height) * 0.02:
        return "方图"
    return "横图" if width > height else "竖图"


# ComfyUI 中用于加载主模型的节点类型（其 checkpoint/unet 名称输入键）
CHECKPOINT_NODE_TYPES = {
    "CheckpointLoaderSimple",
    "CheckpointLoaderGGUF",
    "unCLIPCheckpointLoader",
    "CheckpointLoaderNF4",
    "diffusersModelLoader",
    "UNETLoader",
}


def _extract_model_from_workflow(wf) -> str | None:
    """从 ComfyUI workflow/prompt 结构提取主模型名（checkpoint 文件名）。

    兼容三种格式：
      - prompt 字典：{node_id: {class_type, inputs}}
      - workflow 字典：{nodes: [{type, widgets_values, inputs}]}
      - 外层含 {"prompt": {...}} 的封装
    """
    if not wf or not isinstance(wf, dict):
        return None
    # 情形1：prompt 字典 {node_id: {class_type, inputs}}
    if all(
        (isinstance(k, (str, int)) and str(k).lstrip("-").isdigit())
        for k in (list(wf.keys())[:1] or ["_"])
    ):
        for node in wf.values():
            if not isinstance(node, dict):
                continue
            ct = node.get("class_type") or node.get("type")
            if ct in CHECKPOINT_NODE_TYPES:
                inp = node.get("inputs", {}) or {}
                name = inp.get("ckpt_name") or inp.get("unet_name") or inp.get("model_name")
                if name:
                    return name
    # 情形2：workflow 字典 {nodes: [...]}
    nodes = wf.get("nodes")
    if nodes is not None:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            ct = node.get("type") or node.get("class_type")
            if ct in CHECKPOINT_NODE_TYPES:
                wv = node.get("widgets_values")
                if isinstance(wv, list) and wv and isinstance(wv[0], str):
                    return wv[0]
                inp = node.get("inputs", {}) or {}
                name = inp.get("ckpt_name") or inp.get("unet_name") or inp.get("model_name")
                if name:
                    return name
    # 情形3：{"prompt": {...}} 封装
    if "prompt" in wf and isinstance(wf["prompt"], dict):
        return _extract_model_from_workflow(wf["prompt"])
    return None


def extract_model_name(filename: str, subfolder: str, img_type: str) -> str | None:
    """从出图 PNG 的元数据（workflow/prompt text chunk）提取主模型名；找不到返回 None。"""
    path = resolve_image_path(filename, subfolder, img_type)
    if path is None:
        return None
    try:
        from PIL import Image as PILImage

        with PILImage.open(path) as img:
            info = dict(img.info)
        for key in ("workflow", "prompt"):
            raw = info.get(key)
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            model = _extract_model_from_workflow(data)
            if model:
                return model
    except Exception:
        return None
    return None


def extract_model_from_comfy_prompt(prompt_dict) -> str | None:
    """从 ComfyUI history API 的 prompt 字典（{node_id: {class_type, inputs}}）提取模型名。"""
    return _extract_model_from_workflow(prompt_dict)


def _comfy_prompt_graph(wf) -> dict:
    """取出 API 格式的 prompt 图：{node_id: {class_type, inputs}}。"""
    if not isinstance(wf, dict):
        return {}
    wrapped = wf.get("prompt")
    if isinstance(wrapped, dict):
        return wrapped
    return wf


def extract_run_params(wf) -> dict:
    """从 ComfyUI prompt 图里提取实际采样参数。

    只认 API 格式（inputs 是带键的字典）；PNG 里的 `workflow` 是 GUI 格式，
    参数在 widgets_values 里且顺序不稳定，这里不猜。双程工作流取第一个采样节点，
    足够回答"用了什么步数 / 采样器 / CFG"。
    """
    graph = _comfy_prompt_graph(wf)
    node_inputs = {}
    for node in graph.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        if "sampler_name" in inputs or ("steps" in inputs and "cfg" in inputs):
            node_inputs = inputs
            break

    params: dict = {}
    if node_inputs:
        if isinstance(node_inputs.get("steps"), (int, float)):
            params["steps"] = int(node_inputs["steps"])
        if isinstance(node_inputs.get("cfg"), (int, float)):
            params["cfg_scale"] = float(node_inputs["cfg"])
        sampler = node_inputs.get("sampler_name")
        if isinstance(sampler, str) and sampler:
            params["sampler"] = sampler
        scheduler = node_inputs.get("scheduler")
        if isinstance(scheduler, str) and scheduler:
            params["scheduler"] = scheduler
        seed = node_inputs.get("seed", node_inputs.get("noise_seed"))
        if isinstance(seed, (int, float)):
            params["seed"] = int(seed)
        denoise = node_inputs.get("denoise")
        if isinstance(denoise, (int, float)):
            params["denoise"] = float(denoise)

    model = _extract_model_from_workflow(graph)
    if model:
        params["model"] = model
    return params


def _iso_from_ms(ms: float) -> str:
    return (
        datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def extract_run_times(entry) -> dict:
    """从 ComfyUI history 条目的 status.messages 取开始/结束时间与耗时。

    ComfyUI 在 `execution_start` / `execution_success` 消息里带毫秒时间戳，
    这是唯一能拿到"单张实际跑了多久"的地方（任务表的 created/updated 只到秒且含排队）。
    """
    status = entry.get("status") if isinstance(entry, dict) else None
    messages = (status or {}).get("messages") or []
    start = end = None
    for msg in messages:
        if not isinstance(msg, (list, tuple)) or len(msg) < 2:
            continue
        name, data = msg[0], msg[1]
        data = data if isinstance(data, dict) else {}
        ts = data.get("timestamp")
        if not isinstance(ts, (int, float)):
            continue
        if name == "execution_start" and start is None:
            start = ts
        elif name in ("execution_success", "execution_error", "execution_interrupted"):
            end = ts

    times: dict = {}
    if start:
        times["started_at"] = _iso_from_ms(start)
    if end:
        times["finished_at"] = _iso_from_ms(end)
    if start and end and end >= start:
        times["duration_seconds"] = round((end - start) / 1000, 1)
    return times


def read_embedded_run_params(filename: str, subfolder: str, img_type: str) -> dict:
    """读 PNG 内嵌的 ComfyUI `prompt` 元数据里的采样参数。

    老图没有把参数写进 prompt_params，但 ComfyUI 把完整 prompt 图嵌在 PNG 里；
    读这里比依赖 ComfyUI history（只保留最近 500 条）更可靠。
    """
    path = resolve_image_path(filename, subfolder, img_type)
    if path is None:
        return {}
    try:
        from PIL import Image as PILImage

        with PILImage.open(path) as img:
            info = dict(img.info)
    except Exception:
        return {}
    for key in ("prompt", "workflow"):
        raw = info.get(key)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue
        params = extract_run_params(data)
        if params:
            return params
    return {}


def read_embedded_prompt(filename: str, subfolder: str = "", img_type: str = "output") -> dict:
    """从 PNG 内嵌的 ComfyUI `prompt` 元数据还原提交时的正向/负向文本。

    任务轮询遗漏、只剩磁盘文件的图也能从文件本身读回提示词，不依赖
    ComfyUI history（只保留最近若干条）。负向是否生效按同一套工作流能力探测。
    """
    path = resolve_image_path(filename, subfolder or "", img_type or "output")
    if path is None:
        return {}
    try:
        from PIL import Image as PILImage

        with PILImage.open(path) as img:
            raw = img.info.get("prompt")
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        api_wf = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(api_wf, dict):
        return {}

    from app.services.workflow_parser import _TEXT_ENCODE_NODES, detect_workflow_caps

    nodes = [
        node for node in api_wf.values()
        if isinstance(node, dict)
        and node.get("class_type") in _TEXT_ENCODE_NODES
        and (node.get("inputs") or {}).get("clip") is not None
    ]
    if not nodes:
        return {}
    first_inputs = nodes[0].get("inputs") or {}
    pos_field, neg_field = _TEXT_ENCODE_NODES[nodes[0]["class_type"]]
    positive = str(first_inputs.get(pos_field) or "")
    if not positive.strip():
        return {}

    negative = ""
    if neg_field:
        negative = str(first_inputs.get(neg_field) or "")
    elif len(nodes) >= 2:
        second_inputs = nodes[1].get("inputs") or {}
        second_pos, _ = _TEXT_ENCODE_NODES[nodes[1]["class_type"]]
        negative = str(second_inputs.get(second_pos) or "")

    caps = detect_workflow_caps(api_wf)
    return {
        "prompt": positive,
        "negative_prompt": negative,
        "negative_effective": bool(caps.get("negative_effective")),
    }

