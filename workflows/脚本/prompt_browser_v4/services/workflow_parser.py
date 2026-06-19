"""工作流格式转换 —— 将 ComfyUI 内部格式转换为 API 格式"""
import json
import traceback
from urllib.parse import quote

import httpx

from config import settings

COMFYUI_API = settings.comfyui_api

# widget 名称顺序缓存
_widget_name_cache: dict[str, list[tuple[str, int]]] = {}

SKIP_NODE_TYPES = {"Note", "MarkdownNote", "Label (rgthree)", "Comment", "StickyNote"}

WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN"}


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
                if isinstance(first, list):
                    entries.append((k, 1))
                elif isinstance(first, str) and len(v) >= 2 and isinstance(v[1], dict):
                    if first in WIDGET_TYPES:
                        slots = 2 if v[1].get("control_after_generate") else 1
                        entries.append((k, slots))

        # 成功才缓存
        _widget_name_cache[node_type] = entries
    except Exception:
        traceback.print_exc()

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
        api[nid] = {"class_type": node_type, "inputs": {}}
        raw_inputs = node.get("inputs", [])
        wv = node.get("widgets_values", [])

        # 如果 inputs 已经是 dict 格式，直接使用
        if not isinstance(raw_inputs, list):
            if isinstance(raw_inputs, dict):
                api[nid]["inputs"] = dict(raw_inputs)
            continue

        # 根据 widget 顺序映射 widgets_values 到名称
        wv_by_name: dict[str, object] = {}
        if wv:
            w_entries = _get_widget_order(node_type)
            if w_entries:
                pos = 0
                for name, slots in w_entries:
                    if pos + slots <= len(wv):
                        wv_by_name[name] = wv[pos]
                    pos += slots

        for inp in raw_inputs:
            name = inp.get("name", "")
            if not name:
                continue
            link_id = inp.get("link")
            if link_id is not None:
                src = link_map.get(link_id)
                if src:
                    api[nid]["inputs"][name] = [src[0], src[1]]
            elif "widget" in inp:
                val = inp.get("widget", {}).get("value")
                if val is None and name in wv_by_name:
                    val = wv_by_name[name]
                if val is not None:
                    api[nid]["inputs"][name] = val

        # 补充仅有 widgets_values 没有 inputs 的节点
        if wv and (not isinstance(raw_inputs, list) or len(raw_inputs) == 0):
            for wname, _ in w_entries:
                if wname not in api[nid]["inputs"] and wname in wv_by_name:
                    api[nid]["inputs"][wname] = wv_by_name[wname]

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


def inject_prompt(api_workflow: dict, prompt_data: dict) -> dict:
    """
    向工作流注入提示词 / 种子 / 方向 / 画质。
    修改传入的 dict（就地修改）。
    """
    # 1. 注入提示词到 CLIPTextEncode 节点
    clip_nodes = []
    for node_id, node in api_workflow.items():
        if isinstance(node, dict) and node.get("class_type") == "CLIPTextEncode":
            if node.get("inputs", {}).get("clip") is not None:
                clip_nodes.append((node_id, node))

    if len(clip_nodes) == 0:
        raise RuntimeError("工作流中没有可用的 CLIPTextEncode 节点（全部悬空）")

    clip_nodes[0][1]["inputs"]["text"] = prompt_data["prompt"]
    if len(clip_nodes) >= 2:
        clip_nodes[1][1]["inputs"]["text"] = prompt_data["negative_prompt"]

    # 2. 注入种子
    seed_val = prompt_data.get("seed_override") or prompt_data.get("seed", 0)
    if seed_val and seed_val != 0:
        for node_id, node in api_workflow.items():
            if isinstance(node, dict) and node.get("class_type") in ("KSampler", "KSamplerAdvanced"):
                if "noise_seed" in node["inputs"]:
                    node["inputs"]["noise_seed"] = seed_val
                elif "seed" in node["inputs"]:
                    node["inputs"]["seed"] = seed_val

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
    quality_map = {
        "2K": (2160, 3840),
        "4K": (2560, 4096),
        "6K": (3200, 5120),
        "8K": (3840, 6400),
        "12K": (5120, 8192),
    }
    if quality in quality_map:
        res, max_res = quality_map[quality]
        for node_id, node in api_workflow.items():
            if isinstance(node, dict) and node.get("class_type") == "SeedVR2VideoUpscaler":
                node["inputs"]["resolution"] = res
                node["inputs"]["max_resolution"] = max_res
                break

    return api_workflow
