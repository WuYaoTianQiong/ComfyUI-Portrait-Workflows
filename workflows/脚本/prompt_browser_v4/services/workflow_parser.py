"""工作流格式转换 —— 将 ComfyUI 内部格式转换为 API 格式"""
import json
import logging
from urllib.parse import quote

import httpx

from config import settings

logger = logging.getLogger("prompt_browser.workflow")

COMFYUI_API = settings.comfyui_api

# widget 名称顺序缓存
_widget_name_cache: dict[str, list[tuple[str, int]]] = {}

SKIP_NODE_TYPES = {"Note", "MarkdownNote", "Label (rgthree)", "Comment", "StickyNote"}

WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}
# 不论有没有 widget 字段，这些类型的输入在 widgets_values 中都占一个位置
_WIDGET_INPUT_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO", "IMAGEUPLOAD"}

# 常见输出节点类型（保存图片/潜空间），供 inject_prompt 与 set_output_prefix 共用
_SAVE_NODE_TYPES = {
    "SaveImage", "SaveImageWebedition", "SaveImageExtended",
    "VHS_SaveImage", "SaveAnimatedWEBP", "SaveAnimatedPNG",
    "ImageSave", "SaveLatent", "ETN_SaveImage",
}


def _pytype_matches_comfy(py_val: object, comfy_type: str) -> bool:
    """检查 Python 值类型是否与 ComfyUI 输入类型兼容。"""
    if comfy_type in ("INT",):
        return isinstance(py_val, int) and not isinstance(py_val, bool)
    if comfy_type in ("FLOAT",):
        return isinstance(py_val, (int, float)) and not isinstance(py_val, bool)
    if comfy_type in ("BOOLEAN",):
        return isinstance(py_val, (bool, int))
    if comfy_type in ("STRING", "COMBO"):
        return isinstance(py_val, str)
    # IMAGEUPLOAD, HIDDEN 等类型不做限制
    return True


def _get_widget_order(node_type: str) -> list[tuple[str, int]]:
    """获取节点 widget 名称和槽位数（带缓存）。失败不缓存，避免脏数据。"""
    if node_type in _widget_name_cache:
        return _widget_name_cache[node_type]

    entries: list[tuple[str, int]] = []
    try:
        safe = quote(node_type, safe="")
        with httpx.Client(timeout=3) as client:
            resp = client.get(f"{COMFYUI_API}/object_info/{safe}")
            resp.raise_for_status()
            info = resp.json()

        nd = info.get(node_type, {})
        for group in ["required", "optional"]:
            for k, v in nd.get("input", {}).get(group, {}).items():
                if not isinstance(v, list) or len(v) == 0:
                    continue
                first = v[0]
                # 连接槽（list 类型，如 MODEL、VAE、LATENT 等）→ 占 1 个 slot
                if isinstance(first, list):
                    entries.append((k, 1))
                # COMBO 类型（下拉选择）→ v[1] 是选项列表，占 1 个 slot
                elif first == "COMBO":
                    entries.append((k, 1))
                # 普通 widget（INT/FLOAT/STRING/BOOLEAN）→ v[1] 是配置 dict
                elif isinstance(first, str) and len(v) >= 2 and isinstance(v[1], dict):
                    slots = 2 if v[1].get("control_after_generate") else 1
                    entries.append((k, slots))

        # 成功才缓存
        _widget_name_cache[node_type] = entries
    except Exception as exc:
        # 拿不到 object_info 时退回启发式排序即可，属于正常降级路径，
        # 不能每加载一次页面就刷一段 traceback（ComfyUI 离线时尤其吵）。
        logger.debug("object_info 不可用，退回启发式 widget 顺序：%s (%s)", node_type, type(exc).__name__)

    return entries


def ensure_api_format(workflow: dict) -> dict:
    """将 ComfyUI 内部格式（nodes + links 数组）转为 API 格式（dict keyed by node id）"""
    if "nodes" not in workflow or not isinstance(workflow["nodes"], list):
        return workflow

    # 构建 link_id → (source_node, source_slot) 映射
    link_map: dict[int, tuple[str, int]] = {}
    for link in workflow.get("links", []):
        if isinstance(link, list) and len(link) >= 4:
            link_map[link[0]] = (str(link[1]), int(link[2]))

    api: dict[str, dict] = {}
    for node in workflow["nodes"]:
        node_type = node.get("type", "unknown")
        if node_type in SKIP_NODE_TYPES:
            continue

        nid = str(node.get("id", 0))
        # 保留节点标题（_meta 是官方 API 导出格式的标准字段，后端会忽略）：
        # 双图工作流要靠「主图 / 参考图」这类标题给用户展示节点映射
        api[nid] = {"class_type": node_type, "inputs": {},
                    "_meta": {"title": node.get("title") or node_type}}
        raw_inputs = node.get("inputs", [])
        wv = node.get("widgets_values", [])

        # 如果 inputs 已经是 dict 格式，直接使用
        if not isinstance(raw_inputs, list):
            if isinstance(raw_inputs, dict):
                api[nid]["inputs"] = dict(raw_inputs)
            continue

        # 按 inputs 数组顺序映射 widgets_values，配合类型检测跳过隐藏值
        # 关键：INT/FLOAT/STRING/BOOLEAN/COMBO 类型的输入无论有没有 widget 字段或 link，
        #       都在 widgets_values 中占一个位置（如 resolution 接 Range 节点）
        wv_idx = 0
        for inp in raw_inputs:
            name = inp.get("name", "")
            if not name:
                continue
            inp_type = inp.get("type", "")
            link_id = inp.get("link")
            has_widget_field = "widget" in inp
            is_value_type = inp_type in _WIDGET_INPUT_TYPES
            consumes_wv = has_widget_field or is_value_type  # 是否消耗 widgets_values 位置

            if not consumes_wv:
                # 纯连接输入（IMAGE, MODEL, VAE 等）
                if link_id is not None:
                    src = link_map.get(link_id)
                    if src:
                        api[nid]["inputs"][name] = [src[0], src[1]]
                continue

            # 跳过 widgets_values 中类型不匹配的隐藏值
            while wv_idx < len(wv) and not _pytype_matches_comfy(wv[wv_idx], inp_type):
                wv_idx += 1

            if link_id is not None:
                # 有连线的 widget 类型输入：使用 link 值，但仍消耗位置
                src = link_map.get(link_id)
                if src:
                    api[nid]["inputs"][name] = [src[0], src[1]]
                wv_idx += 1
            elif has_widget_field or is_value_type:
                # 纯 widget 输入：从 widgets_values 取值
                if wv_idx < len(wv):
                    api[nid]["inputs"][name] = wv[wv_idx]
                    wv_idx += 1
                elif has_widget_field:
                    val = inp.get("widget", {}).get("value")
                    if val is not None:
                        api[nid]["inputs"][name] = val

        # 补充：widgets_values 中剩余的值，按 object_info 顺序映射到未覆盖的输入
        # （适用于 CLIPTextEncode 等 inputs 数组不含 widget 的节点）
        if wv_idx < len(wv):
            w_entries = _get_widget_order(node_type)
            if w_entries:
                covered = set(api[nid]["inputs"].keys())
                slot_pos = wv_idx
                for wname, slots in w_entries:
                    # 跳过已覆盖的连接型输入（如 model/image/vae），它们不消耗 widgets_values
                    if wname in covered:
                        continue
                    if slot_pos >= len(wv):
                        break
                    api[nid]["inputs"][wname] = wv[slot_pos]
                    slot_pos += slots

    return api


def load_workflow(workflow_path: str, workflow_content: str | None = None) -> dict:
    """加载并解析工作流 JSON，返回 API 格式的 dict"""
    if workflow_content:
        workflow = json.loads(workflow_content)
    else:
        import os
        if not os.path.exists(workflow_path):
            raise FileNotFoundError(f"工作流文件不存在: {workflow_path}")
        with open(workflow_path, "r", encoding="utf-8") as f:
            workflow = json.load(f)
    return ensure_api_format(workflow)


def _inject_sampler_params(node: dict, prompt_data: dict):
    """为采样器节点（KSampler/KSamplerAdvanced）按需覆盖参数。

    重要设计原则：只覆盖 prompt_data 中显式传入了值的参数，
    保留工作流原有的采样器参数（steps/cfg/sampler/scheduler/start/end/return_with_leftover_noise等）。
    这样才能兼容双程采样（two-pass）等特殊工作流的设计意图。
    """
    inputs = node.get("inputs", {})
    is_advanced = node.get("class_type") == "KSamplerAdvanced"

    # 步数：只有 prompt_data 显式传入了才覆盖
    steps_val = prompt_data.get("steps")
    if steps_val is not None and "steps" in inputs:
        inputs["steps"] = int(steps_val)

    # CFG：只有 prompt_data 显式传入了才覆盖
    cfg_val = prompt_data.get("cfg_scale")
    if cfg_val is not None and "cfg" in inputs:
        inputs["cfg"] = float(cfg_val)

    # sampler_name：只有 prompt_data 显式传入了才覆盖
    sampler_name = prompt_data.get("sampler")
    if sampler_name and "sampler_name" in inputs:
        inputs["sampler_name"] = str(sampler_name)

    # scheduler：只有 prompt_data 显式传入了才覆盖
    if is_advanced and "scheduler" in inputs:
        scheduler = prompt_data.get("scheduler")
        if scheduler:
            inputs["scheduler"] = str(scheduler)


def inject_prompt(api_workflow: dict, prompt_data: dict) -> dict:
    """
    向工作流注入提示词 / 种子 / 方向 / 画质。
    修改传入的 dict（就地修改）。
    """
    # 1. 注入提示词到 CLIPTextEncode 节点
    #    若无 CLIPTextEncode 节点（如纯图片超分工作流），则跳过提示词注入
    clip_nodes = []
    for node_id, node in api_workflow.items():
        if isinstance(node, dict) and node.get("class_type") == "CLIPTextEncode":
            if node.get("inputs", {}).get("clip") is not None:
                clip_nodes.append((node_id, node))

    if len(clip_nodes) == 0:
        # 纯图像工作流（如 SeedVR2 超分）不含文本编码节点，跳过提示词注入
        print("[workflow_parser] 警告：未找到 CLIPTextEncode 节点，跳过提示词注入")
    else:
        clip_nodes[0][1]["inputs"]["text"] = prompt_data["prompt"]
        if len(clip_nodes) >= 2:
            clip_nodes[1][1]["inputs"]["text"] = prompt_data["negative_prompt"]

    # 2. 注入种子
    # 注意：seed=0 是有效值，不应跳过；seed_override=0 表示强制用 0
    seed_override = prompt_data.get("seed_override")
    if seed_override is not None:
        seed_val = seed_override
    else:
        seed_val = prompt_data.get("seed", 0)
    # 如果 seed_val 仍为 0 且没有显式 override，则生成随机种子
    if seed_val == 0 and seed_override is None:
        import random as _rnd
        seed_val = _rnd.randint(1, 2**32 - 1)

    # 遍历所有采样器节点：先注种子，再注参数
    for node_id, node in api_workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        cls = node.get("class_type", "")
        if cls in ("KSampler", "KSamplerAdvanced"):
            # 种子
            if "noise_seed" in inputs:
                inputs["noise_seed"] = seed_val
            elif "seed" in inputs:
                inputs["seed"] = seed_val
            # 显式覆盖采样参数（修复 workflow 解析器值错位问题）
            _inject_sampler_params(node, prompt_data)
        elif "noise_seed" in inputs:
            # 独立噪声节点（RandomNoise + SamplerCustomAdvanced 这类链路）。
            # 旧逻辑只按 KSampler 类名匹配，导致这类工作流的种子注入静默失效——
            # 界面上的 randomize 是前端行为，走 API 后会退化成工作流里的字面量种子。
            inputs["noise_seed"] = seed_val

    # 3. 注入方向（横竖屏）
    orientation = prompt_data.get("orientation", "portrait")
    for node_id, node in api_workflow.items():
        if isinstance(node, dict) and node.get("class_type") == "EmptyLatentImage":
            w, h = node["inputs"].get("width", 640), node["inputs"].get("height", 960)
            if orientation == "landscape" and h > w:
                node["inputs"]["width"], node["inputs"]["height"] = h, w
            elif orientation == "portrait" and w > h:
                node["inputs"]["width"], node["inputs"]["height"] = h, w
            break

    # 4. 注入画质
    quality = prompt_data.get("quality", "4K")
    quality_scale_map = {"2K": 0.75, "4K": 1.0, "6K": 1.25, "8K": 1.5, "12K": 2.0}
    scale = quality_scale_map.get(quality, 1.0)

    # 4a. SeedVR 工作流：设置超分分辨率
    seedvr_quality_map = {
        "2K": (2160, 3840), "4K": (2560, 4096),
        "6K": (3200, 5120), "8K": (3840, 6400), "12K": (5120, 8192),
    }
    has_seedvr = False
    if quality in seedvr_quality_map:
        res, max_res = seedvr_quality_map[quality]
        for node_id, node in api_workflow.items():
            if isinstance(node, dict) and node.get("class_type") == "SeedVR2VideoUpscaler":
                node["inputs"]["resolution"] = res
                node["inputs"]["max_resolution"] = max_res
                has_seedvr = True
                break

    # 4b. 非 SeedVR 工作流：按比例缩放 EmptyLatentImage 尺寸
    if not has_seedvr and scale != 1.0:
        for node_id, node in api_workflow.items():
            if isinstance(node, dict) and node.get("class_type") == "EmptyLatentImage":
                w = node["inputs"].get("width", 640)
                h = node["inputs"].get("height", 960)
                node["inputs"]["width"] = max(256, min(4096, int(w * scale)))
                node["inputs"]["height"] = max(256, min(4096, int(h * scale)))
                break

    # 5. 为输出节点注入唯一文件名前缀，避免批量跑图时文件互相覆盖
    import time
    import random as _random
    _ts = int(time.time() * 1000)
    _rand = _random.randint(1000, 9999)
    _unique_prefix = f"prompt_browser_{_ts}_{_rand}"
    # 常见输出节点类型
    for node_id, node in api_workflow.items():
        if not isinstance(node, dict):
            continue
        cls = node.get("class_type", "")
        inputs = node.get("inputs", {})
        # 精确匹配已知保存节点
        if cls in _SAVE_NODE_TYPES:
            if "filename_prefix" in inputs:
                # 在原前缀后追加唯一标识，保留用户原有的前缀习惯
                orig = inputs["filename_prefix"] or ""
                inputs["filename_prefix"] = f"{orig}_{_unique_prefix}" if orig else _unique_prefix
        # 模糊匹配：类名包含 Save/Export/Output 且无连线输出（是终端保存节点）
        elif "Save" in cls or "Export" in cls or "Output" in cls:
            if "filename_prefix" in inputs:
                orig = inputs["filename_prefix"] or ""
                inputs["filename_prefix"] = f"{orig}_{_unique_prefix}" if orig else _unique_prefix

    return api_workflow


def set_output_prefix(api_workflow: dict, prefix: str) -> int:
    """把所有保存节点的 filename_prefix 强制设为 prefix，返回改动的节点数。

    批量出图时用它保证文件名可追溯到「哪个组合」：inject_prompt 的唯一后缀是
    毫秒级时间戳，同一毫秒内连续提交多个组合可能撞车，届时 SaveImage 会自动加
    序号，配对关系就丢了。
    """
    n = 0
    for node in api_workflow.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict) or "filename_prefix" not in inputs:
            continue
        cls = node.get("class_type", "")
        if cls in _SAVE_NODE_TYPES or "Save" in cls or "Export" in cls or "Output" in cls:
            inputs["filename_prefix"] = prefix
            n += 1
    return n


def find_loadimage_nodes(api_workflow: dict) -> list[tuple[str, str]]:
    """返回工作流里的 LoadImage 节点 [(node_id, 标题)]，按节点创建顺序。

    多图工作流（主图 + 参考图）靠这个顺序做默认映射：第一个=主图，第二个=参考图。
    """
    out: list[tuple[str, str]] = []
    for node_id, node in api_workflow.items():
        if isinstance(node, dict) and node.get("class_type") == "LoadImage":
            title = (node.get("_meta") or {}).get("title") or "LoadImage"
            out.append((str(node_id), str(title)))
    return out


def inject_input_image(
    api_workflow: dict,
    source_path: str,
    dest_dir: str,
    node_id: str | None = None,
    dest_name: str | None = None,
) -> str:
    """将源图片复制到 ComfyUI input 目录，并注入 LoadImage 节点。

    Args:
        api_workflow: API 格式的工作流
        source_path: 源图片绝对路径（如 ComfyUI output 下的图片）
        dest_dir: ComfyUI input 目录绝对路径
        node_id: 指定注入哪个 LoadImage 节点；None = 第一个 LoadImage（旧行为）。
                 双图工作流必须显式指定，否则两张图会互相覆盖。
        dest_name: 复制后的文件名；None = 带毫秒时间戳的唯一名（旧行为）。
                   批量时传入稳定名字，同一张源图只拷一份，避免 input 目录被刷爆。

    Returns:
        复制后的图片文件名（可用于后续记录的 prompt_params）
    """
    import shutil
    import time
    from pathlib import Path

    src = Path(source_path)
    if not src.exists():
        raise FileNotFoundError(f"源图片不存在: {source_path}")

    if dest_name:
        dst_name = dest_name
        dst_path = Path(dest_dir) / dst_name
        if not dst_path.exists():  # 同名已存在则复用，不重复拷贝
            shutil.copy2(str(src), str(dst_path))
    else:
        # 生成唯一文件名，避免覆盖
        ts = int(time.time() * 1000)
        dst_name = f"pb_process_{ts}_{src.name}"
        dst_path = Path(dest_dir) / dst_name
        shutil.copy2(str(src), str(dst_path))

    # 目标节点：显式指定优先，否则退回第一个 LoadImage（保持旧行为）
    target = api_workflow.get(str(node_id)) if node_id is not None else None
    if not isinstance(target, dict):
        target = None
    if target is None:
        for node in api_workflow.values():
            if isinstance(node, dict) and node.get("class_type") == "LoadImage":
                target = node
                break

    if target is not None:
        target.setdefault("inputs", {})["image"] = dst_name
    else:
        # 没有 LoadImage 节点时尝试在第一个节点新增 image 参数（旧兜底逻辑）
        first_id = next(iter(api_workflow))
        first = api_workflow[first_id]
        if "image" not in first.get("inputs", {}):
            first.setdefault("inputs", {})["image"] = dst_name
            # 也设置 class_type 为 LoadImage
            first["class_type"] = "LoadImage"

    return dst_name
