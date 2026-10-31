"""工作流格式转换 —— 将 ComfyUI 内部格式转换为 API 格式"""
import json
import logging
import math
import re

from app.services.comfyui_client import get_object_info

logger = logging.getLogger("atelier.workflow")

# widget 名称顺序缓存
_widget_name_cache: dict[str, list[tuple[str, int]]] = {}
# COMBO 可选值缓存 {(节点类型, 输入名): [选项...]}
_combo_options_cache: dict[tuple[str, str], list[str]] = {}

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

# 文本编码节点：类名 → (正面字段, 负面粉字段 / None)
# 新模型常带专用编码节点（如 Qwen-Image 2.1 的 TextEncodeQwenImage21，提示词是
# prompt / negative_prompt 两个字段且自带负面，不能只认 CLIPTextEncode 的 text）。
_TEXT_ENCODE_NODES: dict[str, tuple[str, str | None]] = {
    "CLIPTextEncode": ("text", None),
    "TextEncodeQwenImage21": ("prompt", "negative_prompt"),
    "TextEncodeQwenImageEdit": ("prompt", None),
    "TextEncodeQwenImageEditPlus": ("prompt", None),
}


def _as_int(val: object) -> int | None:
    """把 widget 字面量解析成 int；连线引用 / 非数字字符串一律返回 None。"""
    if isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    if isinstance(val, str):
        try:
            return int(val.strip())
        except ValueError:
            return None
    return None


def _linked_node(api_workflow: dict, val: object) -> dict | None:
    """若 val 是 ["节点id", 输出槽] 形式的连线引用，返回源节点；否则 None。"""
    if isinstance(val, (list, tuple)) and len(val) == 2 and isinstance(val[0], str):
        src = api_workflow.get(val[0])
        if isinstance(src, dict):
            return src
    return None


_RATIO_RE = re.compile(r"\s*(\d+(?:\.\d+)?)\s*[:：]\s*(\d+(?:\.\d+)?)")
_SIZE_RE = re.compile(r"\s*(\d+)\s*[x×*]\s*(\d+)", re.IGNORECASE)


def _extract_options(spec: object) -> list[str]:
    """从 object_info 的 COMBO 描述里取选项。

    新版是 ["COMBO", {"options": [...]}]，旧版是 [[opt, ...], {...}]，两种都要认。
    """
    if not isinstance(spec, (list, tuple)) or not spec:
        return []
    first = spec[0]
    if isinstance(first, str) and first == "COMBO":
        if len(spec) > 1 and isinstance(spec[1], dict):
            opts = spec[1].get("options")
            if isinstance(opts, list):
                return [str(o) for o in opts]
        return []
    if isinstance(first, list):
        return [str(o) for o in first]
    return []


def _get_combo_options(node_type: str, input_name: str) -> list[str]:
    """取某节点某 COMBO 输入的全部合法选项（带缓存）。

    拿不到（ComfyUI 离线 / 自定义节点未装）时返回空列表，调用方据此降级跳过，
    绝不自己拼一个字符串——ComfyUI 会因非法枚举值直接拒收整个 prompt。
    """
    key = (node_type, input_name)
    if key in _combo_options_cache:
        return _combo_options_cache[key]
    try:
        info = get_object_info().get(node_type, {})
        options: list[str] = []
        for group in ("required", "optional"):
            spec = info.get("input", {}).get(group, {}).get(input_name)
            options = _extract_options(spec)
            if options:
                break
        if options:
            _combo_options_cache[key] = options
        return options
    except Exception as exc:
        logger.debug("取 %s.%s 可选值失败：%s", node_type, input_name, type(exc).__name__)
        return []


def _parse_ratio(text: str) -> float | None:
    """'9:16 (Portrait Widescreen)' -> 0.5625"""
    m = _RATIO_RE.match(str(text))
    if not m:
        return None
    a, b = float(m.group(1)), float(m.group(2))
    if a <= 0 or b <= 0:
        return None
    return a / b


def _parse_size_ratio(text: str) -> float | None:
    """'640x960 （2:3）' -> 0.6667"""
    m = _SIZE_RE.match(str(text))
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    if w <= 0 or h <= 0:
        return None
    return w / h


# 尺寸由上游节点计算时，按顺序尝试这些「横竖比旋钮」：(输入名, 选项解析方式)
_ORIENTATION_KNOBS = (
    ("aspect_ratio", _parse_ratio),   # ResolutionSelector: "9:16 (Portrait Widescreen)"
    ("resolution", _parse_ratio),     # 部分自定义节点沿用这个命名
    ("preset", _parse_size_ratio),    # ResolutionPresetPicker: "640x960 （2:3）"
    ("size", _parse_size_ratio),
)


def _pick_orientation_option(options: list[str], current: str, orientation: str,
                             parser) -> str | None:
    """在合法选项里挑一个「与当前比例互为倒数、且处于目标方向」的值。

    已经是目标方向 / 1:1 方图时返回 None（无需改动）。
    """
    if orientation not in ("portrait", "landscape"):
        return None
    want_landscape = orientation == "landscape"
    cur = parser(current)
    if cur is None or cur <= 0:
        return None
    if abs(cur - 1.0) < 1e-9:
        return None  # 方图无横竖可分
    if (cur > 1) == want_landscape:
        return None  # 已经是目标方向
    target = 1.0 / cur
    best, best_score = None, None
    for opt in options:
        r = parser(opt)
        if r is None or r <= 0:
            continue
        if (r > 1) != want_landscape:
            continue
        score = abs(math.log(r / target))
        if best_score is None or score < best_score:
            best, best_score = opt, score
    return best


def _apply_orientation_to_size_source(api_workflow: dict, latent_inputs: dict,
                                      orientation: str) -> bool:
    """尺寸由上游节点计算时（EmptyLatentImage 的 width/height 是连线），
    改上游那个决定比例的旋钮来实现横竖屏切换。"""
    src = _linked_node(api_workflow, latent_inputs.get("width")) or \
        _linked_node(api_workflow, latent_inputs.get("height"))
    if src is None:
        return False
    src_inputs = src.get("inputs") or {}
    cls = src.get("class_type", "")
    for key, parser in _ORIENTATION_KNOBS:
        current = src_inputs.get(key)
        if not isinstance(current, str) or not current:
            continue
        options = _get_combo_options(cls, key)
        if not options:
            logger.debug("%s.%s 拿不到合法选项，跳过横竖屏切换", cls, key)
            return False
        picked = _pick_orientation_option(options, current, orientation, parser)
        if picked and picked != current:
            src_inputs[key] = picked
            logger.info("横竖屏 %s：%s.%s = %s", orientation, cls, key, picked)
            return True
        return False
    logger.debug("%s 没有可切换的横竖比旋钮，跳过横竖屏切换", cls)
    return False


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
        nd = get_object_info().get(node_type, {})
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

    api = _nodes_to_api(workflow["nodes"], link_map)
    return _expand_subgraphs(workflow, api)


def _nodes_to_api(nodes: list, link_map: dict[int, tuple[str, int]]) -> dict[str, dict]:
    """把 UI 格式的 node 列表转成 API 节点；link_map 用于把连线编号还原成 [源节点, 槽位]。"""
    api: dict[str, dict] = {}
    for node in nodes:
        node_type = node.get("type", "unknown")
        if node_type in SKIP_NODE_TYPES:
            continue

        nid = str(node.get("id", 0))
        # 保留节点标题（_meta 是官方 API 导出格式的标准字段，后端会忽略）：
        # 多图工作流要靠这些标题给用户展示节点映射
        api[nid] = {"class_type": node_type, "inputs": {},
                    "_meta": {"title": node.get("title") or node_type}}
        raw_inputs = node.get("inputs", [])
        wv = node.get("widgets_values") or []

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


def _expand_subgraphs(workflow: dict, api: dict) -> dict:
    """展开 definitions.subgraphs 里的子图实例节点。

    ComfyUI 新版 UI 允许把一组节点存成「子图」，保存的 JSON 里表现为一个
    type=<子图 uuid> 的节点。前端提交时会展开，但后端直接转 API 格式不会，
    /prompt 就会报 missing_node_type。这里按子图定义把它内联成真实节点。

    改写规则：
    · 内部节点 id 加外层节点前缀，避免与主图节点撞号；
    · 子图输入槽 → 外层实例对应输入端口的上游连线；
    · 子图输出槽 → 产出该输出的内部节点，并替换所有消费方的引用。
    """
    sub_defs = {
        sg.get("id"): sg
        for sg in ((workflow.get("definitions") or {}).get("subgraphs") or [])
        if isinstance(sg, dict) and sg.get("id")
        and isinstance(sg.get("nodes"), list)
    }
    if not sub_defs:
        return api

    raw_nodes = {str(n.get("id")): n for n in workflow["nodes"]}

    # 支持嵌套子图：每轮展开当前层的实例，最多 8 层（真实工作流远达不到）
    for _ in range(8):
        instances = [
            (nid, node) for nid, node in api.items()
            if node.get("class_type") in sub_defs
        ]
        if not instances:
            break

        for outer_id, outer_api in instances:
            sg = sub_defs[outer_api["class_type"]]
            raw_outer = raw_nodes.get(outer_id) or {}

            inner_links = {
                link["id"]: (str(link.get("origin_id")), int(link.get("origin_slot", 0)))
                for link in (sg.get("links") or [])
                if isinstance(link, dict) and link.get("id") is not None
            }
            inner = _nodes_to_api(sg.get("nodes") or [], inner_links)

            prefix = f"{outer_id}_"
            mapped: dict[str, dict] = {}
            for inner_id, inner_node in inner.items():
                mapped[prefix + inner_id] = {
                    "class_type": inner_node["class_type"],
                    "inputs": dict(inner_node["inputs"]),
                    "_meta": dict(inner_node.get("_meta") or {}),
                }

            # 子图输入槽（-10 的 origin_slot）→ 外层实例输入端的连线。
            # 必须读 api 里已经转换过的值：若上游也是子图，它可能已被改写为内部节点 id，
            # 再用原始 link id 回查会得到已经删除的实例 id。
            slot_source: dict[int, object] = {}
            for slot, inp in enumerate(raw_outer.get("inputs") or []):
                if not isinstance(inp, dict):
                    continue
                name = inp.get("name")
                value = (outer_api.get("inputs") or {}).get(name)
                if isinstance(value, list) and len(value) == 2:
                    slot_source[slot] = (str(value[0]), int(value[1]))
                elif value is not None:
                    slot_source[slot] = value

            for node in mapped.values():
                for name, value in list(node["inputs"].items()):
                    if not (isinstance(value, list) and len(value) == 2):
                        continue
                    src, slot = str(value[0]), int(value[1])
                    if src == "-10":
                        outer_src = slot_source.get(slot)
                        if isinstance(outer_src, tuple):
                            node["inputs"][name] = [outer_src[0], outer_src[1]]
                        elif outer_src is not None:
                            node["inputs"][name] = outer_src
                        else:
                            node["inputs"].pop(name)
                    elif src == "-20":
                        node["inputs"].pop(name)
                    else:
                        node["inputs"][name] = [prefix + src, slot]

            # 子图输出槽（-20 的 target_slot）→ 内部产出节点
            output_producers: dict[int, tuple[str, int]] = {}
            for link in sg.get("links") or []:
                if isinstance(link, dict) and link.get("target_id") == -20:
                    output_producers[int(link.get("target_slot", 0))] = (
                        prefix + str(link.get("origin_id")),
                        int(link.get("origin_slot", 0)),
                    )

            # 替换所有消费该子图输出的连线（主图节点 + 之前展开的节点）
            for node in api.values():
                for name, value in list((node.get("inputs") or {}).items()):
                    if not (isinstance(value, list) and len(value) == 2):
                        continue
                    if str(value[0]) != outer_id:
                        continue
                    producer = output_producers.get(int(value[1]))
                    if producer:
                        node["inputs"][name] = [producer[0], producer[1]]
                    else:
                        node["inputs"].pop(name)

            del api[outer_id]
            api.update(mapped)

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


def detect_workflow_caps(api_workflow: dict) -> dict[str, bool]:
    """探测工作流能接受哪些注入项。

    判定规则与 `inject_prompt` 完全一致：只标记真正会被改到的项。
    否则前端会显示一个点了也不生效的"横竖/画质"旋钮
    （例如视频工作流没有 EmptyLatentImage，超分工作流没有横竖比旋钮）。
    """
    text_nodes = [
        node for node in api_workflow.values()
        if isinstance(node, dict)
        and node.get("class_type") in _TEXT_ENCODE_NODES
        and node.get("inputs", {}).get("clip") is not None
    ]
    caps = {
        "prompt": bool(text_nodes),
        "negative": False,
        "quality": False,
        "orientation": False,
    }
    if text_nodes:
        spec = _TEXT_ENCODE_NODES[text_nodes[0].get("class_type")]
        caps["negative"] = bool(spec[1]) or len(text_nodes) >= 2

    for node in api_workflow.values():
        if not isinstance(node, dict):
            continue
        cls = node.get("class_type")
        if cls == "SeedVR2VideoUpscaler":
            caps["quality"] = True  # 4a：超分分辨率
        if cls != "EmptyLatentImage":
            continue
        inputs = node.get("inputs") or {}
        w = _as_int(inputs.get("width"))
        h = _as_int(inputs.get("height"))
        if w is not None and h is not None:
            caps["quality"] = True  # 4b：按比例缩放字面量尺寸
            # 方图没有横竖可分，inject_prompt 也只是交换 w/h，换不出方向
            caps["orientation"] = w != h
            continue
        # 尺寸由上游节点计算：改横竖比旋钮 / megapixels
        src = _linked_node(api_workflow, inputs.get("width")) or \
            _linked_node(api_workflow, inputs.get("height"))
        if not isinstance(src, dict):
            continue
        src_inputs = src.get("inputs") or {}
        if any(isinstance(src_inputs.get(key), str) for key, _ in _ORIENTATION_KNOBS):
            caps["orientation"] = True
        mp = src_inputs.get("megapixels")
        if isinstance(mp, (int, float)) and not isinstance(mp, bool):
            caps["quality"] = True
    return caps


def detect_workflow_params(api_workflow: dict) -> dict:
    """探测画质 / 方向旋钮的实际作用方式，供前端生成"真实档位"。

    quality_mode:
      - seedvr：SeedVR 超分，档位直接对应真实输出分辨率
      - scale：EmptyLatentImage 有字面宽高，注入时按倍率缩放
      - megapixels：尺寸由上游节点算，注入时按 megapixels 面积缩放
      - none：没有可调尺寸
    orientation_mode:
      - swap：字面宽高交换
      - knob：改上游节点的比例旋钮
      - none：方图 / 没有可切换的旋钮

    判定范围与 `inject_prompt` 保持一致：只描述真正会被改到的位置。
    """
    params = {
        "quality_mode": "none",
        "base_width": None,
        "base_height": None,
        "base_megapixels": None,
        "orientation_mode": "none",
    }
    has_seedvr = any(
        isinstance(n, dict) and n.get("class_type") == "SeedVR2VideoUpscaler"
        for n in api_workflow.values()
    )
    if has_seedvr:
        params["quality_mode"] = "seedvr"

    for node in api_workflow.values():
        if not isinstance(node, dict) or node.get("class_type") != "EmptyLatentImage":
            continue
        inputs = node.get("inputs") or {}
        w = _as_int(inputs.get("width"))
        h = _as_int(inputs.get("height"))
        if w is not None and h is not None:
            if not has_seedvr:
                params["quality_mode"] = "scale"
                params["base_width"] = w
                params["base_height"] = h
            params["orientation_mode"] = "swap" if w != h else "none"
            break

        src = _linked_node(api_workflow, inputs.get("width")) or \
            _linked_node(api_workflow, inputs.get("height"))
        if not isinstance(src, dict):
            break
        src_inputs = src.get("inputs") or {}
        if any(isinstance(src_inputs.get(key), str) for key, _ in _ORIENTATION_KNOBS):
            params["orientation_mode"] = "knob"
        mp = src_inputs.get("megapixels")
        if not has_seedvr and isinstance(mp, (int, float)) and not isinstance(mp, bool):
            params["quality_mode"] = "megapixels"
            params["base_megapixels"] = round(float(mp), 3)
        break
    return params


def inject_prompt(api_workflow: dict, prompt_data: dict) -> dict:
    """
    向工作流注入提示词 / 种子 / 方向 / 画质。
    修改传入的 dict（就地修改）。
    """
    # 1. 注入提示词到文本编码节点（CLIPTextEncode 或专用的 TextEncodeQwenImage21 等）
    #    若无文本编码节点（如纯图片超分工作流），则跳过提示词注入
    text_nodes = []
    for node_id, node in api_workflow.items():
        if not isinstance(node, dict):
            continue
        spec = _TEXT_ENCODE_NODES.get(node.get("class_type", ""))
        if spec is None:
            continue
        if node.get("inputs", {}).get("clip") is not None:
            text_nodes.append((node_id, node, spec))

    if len(text_nodes) == 0:
        # 纯图像工作流（如 SeedVR2 超分）不含文本编码节点，跳过提示词注入
        print("[workflow_parser] 警告：未找到文本编码节点（CLIPTextEncode / TextEncodeQwenImage21 等），跳过提示词注入")
    else:
        _nid, _node, (_pos_field, _neg_field) = text_nodes[0]
        _node["inputs"][_pos_field] = prompt_data["prompt"]
        _negative = prompt_data.get("negative_prompt") or ""
        if _neg_field:
            # 单节点自带负面字段（如 Qwen-Image 2.1），直接写同一个节点
            _node["inputs"][_neg_field] = _negative
        elif len(text_nodes) >= 2:
            # 旧行为：第二个文本编码节点当负面
            text_nodes[1][1]["inputs"][text_nodes[1][2][0]] = _negative

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
    #    EmptyLatentImage 的 width/height 可能是 ["节点id", 槽位] 连线引用
    #    （如 ResolutionSelector / ResolutionPresetPicker 算出的尺寸）：
    #    这时改不了字面量，改为切换上游节点的横竖比旋钮。
    orientation = prompt_data.get("orientation", "portrait")
    for node_id, node in api_workflow.items():
        if isinstance(node, dict) and node.get("class_type") == "EmptyLatentImage":
            inputs = node["inputs"]
            w = _as_int(inputs.get("width"))
            h = _as_int(inputs.get("height"))
            if w is not None and h is not None:
                if orientation == "landscape" and h > w:
                    inputs["width"], inputs["height"] = h, w
                elif orientation == "portrait" and w > h:
                    inputs["width"], inputs["height"] = h, w
            else:
                _apply_orientation_to_size_source(api_workflow, inputs, orientation)
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
                inputs = node["inputs"]
                w = _as_int(inputs.get("width"))
                h = _as_int(inputs.get("height"))
                if w is not None and h is not None:
                    inputs["width"] = max(256, min(4096, int(w * scale)))
                    inputs["height"] = max(256, min(4096, int(h * scale)))
                else:
                    # 尺寸由上游节点计算（如 ResolutionSelector：aspect_ratio + megapixels），
                    # 无法直接改字面量；只能改上游的 megapixels，且面积按 scale² 缩放
                    # 才等价于两轴同时乘 scale。
                    for key in ("width", "height"):
                        src = _linked_node(api_workflow, inputs.get(key))
                        if src is None:
                            continue
                        src_inputs = src.get("inputs", {})
                        mp = src_inputs.get("megapixels")
                        if isinstance(mp, (int, float)) and not isinstance(mp, bool):
                            src_inputs["megapixels"] = round(float(mp) * scale * scale, 3)
                            logger.info("画质 %s：%s.megapixels = %s（尺寸由上游节点决定）",
                                        quality, src.get("class_type"), src_inputs["megapixels"])
                        break
                break

    # 5. 为输出节点注入唯一文件名前缀，避免批量跑图时文件互相覆盖
    import time
    import random as _random
    _ts = int(time.time() * 1000)
    _rand = _random.randint(1000, 9999)
    _unique_prefix = f"atelier_{_ts}_{_rand}"
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
    """返回工作流里的 LoadImage 节点 [(node_id, 标题)]，按节点创建顺序。"""
    out: list[tuple[str, str]] = []
    for node_id, node in api_workflow.items():
        if isinstance(node, dict) and node.get("class_type") == "LoadImage":
            title = (node.get("_meta") or {}).get("title") or "LoadImage"
            out.append((str(node_id), str(title)))
    return out


def find_size_source_loadimage(api_workflow: dict) -> str | None:
    """找出决定输出尺寸的 LoadImage（多图工作流里的「目标图」）。

    多图参考类工作流通常由 GetImageSize → EmptyLatent/Scheduler 决定输出尺寸，
    而这个尺寸来源不一定是节点顺序上的第一个 LoadImage。从 GetImageSize 的
    image 输入向上游回溯，命中的第一个 LoadImage 就是尺寸基准。
    找不到时返回 None，调用方退回节点顺序。
    """

    def walk(node_id: str, seen: set[str]) -> str | None:
        node = api_workflow.get(node_id)
        if not isinstance(node, dict) or node_id in seen:
            return None
        if node.get("class_type") == "LoadImage":
            return node_id
        seen.add(node_id)
        for value in (node.get("inputs") or {}).values():
            if isinstance(value, (list, tuple)) and len(value) == 2 and isinstance(value[0], str):
                found = walk(value[0], seen)
                if found:
                    return found
        return None

    for node_id, node in api_workflow.items():
        if not isinstance(node, dict) or node.get("class_type") != "GetImageSize":
            continue
        image = (node.get("inputs") or {}).get("image")
        if isinstance(image, (list, tuple)) and len(image) == 2 and isinstance(image[0], str):
            found = walk(image[0], set())
            if found:
                return found
    return None


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
