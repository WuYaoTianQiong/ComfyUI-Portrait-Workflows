"""工作流格式转换 —— 将 ComfyUI 内部格式转换为 API 格式"""
import json
import logging
import math
import re

from app.services.comfyui_client import get_object_info
from app.services.image_formats import convert_heif_to_png, is_heif
from app.services.prompt_compiler import compile_prompt
from app.services.quality_keys import normalize_quality, quality_scale

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

# 可注入宽高的空 latent 节点：SD3/Flux2/Z-Image 用各自的类名，宽高字段一致
_LATENT_NODE_TYPES = {"EmptyLatentImage", "EmptySD3LatentImage", "EmptyFlux2LatentImage"}

#: LoadImage 标题里的业务角色关键词（合成台靠它判定“哪张图放哪个槽”）。
#: 工作流标题是人工标注，中文/英文、Java 全角冒号都可能出现，统一小写后包含匹配。
_LOADIMAGE_ROLE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("portrait", ("人像", "portait", "portrait")),
    ("costume", ("服装", "costume", "outfit")),
    ("pose", ("姿势", "pose")),
    # 附加图放最后匹配，避免“配饰”等词抢在服装/姿势前面
    ("extra", ("附加", "第 4", "第4", "图4", "extra", "additional")),
)

#: 文本编码器里承载参考图的键名：
#:   TextEncodeQwenImage21        → images.image_1 .. images.image_16（autogrow）
#:   TextEncodeQwenImageEditPlus  → image1 / image2 / image3（optional）
_IMAGE_INPUT_KEY_RE = re.compile(r"^(?:images\.image_(\d+)|image(\d+))$")

#: LoadImage 实际像素尺寸缓存：{(绝对路径, mtime): (width, height) | None}
_loadimage_size_cache: dict[tuple[str, float], tuple[int, int] | None] = {}

# 项目统一比例；包含 ResolutionSelector 的 8 个选项 + 21:9 的竖版 9:21。
CANONICAL_RATIOS = ("1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9", "9:21")
_RATIO_VALUES = {
    ratio: int(ratio.split(":")[0]) / int(ratio.split(":")[1]) for ratio in CANONICAL_RATIOS
}

# ResolutionPresetPicker / ResolutionSelector 的真实选项；都没有 9:21。
# 固定放大链路（ZIT 1.7×）不允许 App 再用字面量硬塞 9:21：实测 9:16 就已经
# 有 1/3 底部拼贴，9:21 更差。单程工作流（Qwen/Krea2/Porn）才开放 9:21 扩展。
NATIVE_PRESET_RATIOS = ("1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9")
NATIVE_RESOLVER_RATIOS = ("1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9")

# 第二程（post_scale）输出长边上限。超过后 ZIT 用固定 1.7× 硬拉会出现
# 底部货架/地面拼贴；2048 是 9:16 三 seed 验证过的安全阈值。
MAX_FINAL_LONG_SIDE = 2048


class RatioNotSupported(ValueError):
    """请求的比例超出工作流安全范围（例如 ZIT 预设链路 + 9:21）。"""


def normalize_aspect_ratio(value: object) -> str | None:
    """把 '9:16 (Portrait Widescreen)' / '640x960（2:3）' 归一到 8 个标准比例之一。"""
    if not isinstance(value, str):
        return None
    m = _RATIO_RE.match(value) or _RATIO_RE.search(value)
    if not m:
        return None
    a, b = float(m.group(1)), float(m.group(2))
    if a <= 0 or b <= 0:
        return None
    got = a / b
    for ratio in CANONICAL_RATIOS:
        if abs(_RATIO_VALUES[ratio] - got) < 1e-6:
            return ratio
    return None


def _closest_ratio(width: int, height: int) -> str:
    if not width or not height:
        return "1:1"
    value = width / height
    return min(CANONICAL_RATIOS, key=lambda r: abs(math.log(value / _RATIO_VALUES[r])))


def _round_to(value: float, multiple: int) -> int:
    return max(multiple, int(round(value / multiple)) * multiple)


def compute_aspect_size(ratio: str, megapixels: float, multiple: int = 16,
                        unit: int = 1_000_000) -> tuple[int, int]:
    """按目标总像素和比例算宽高；对齐到 multiple，避免 VAE patch 非整除。

    unit 是调用方的 MP 单位：字面量/preset 用 1e6，ResolutionSelector 用 1024²（MiP）。
    """
    r = _RATIO_VALUES.get(ratio, 1.0)
    width = math.sqrt(max(0.01, megapixels) * unit * r)
    height = width / r
    return _round_to(width, multiple), _round_to(height, multiple)


def _parse_preset(text: object) -> tuple[int, int, str] | None:
    """'640x960（2:3）' -> (640, 960, '2:3')。"""
    if not isinstance(text, str):
        return None
    m = _SIZE_RE.match(text)
    if not m:
        return None
    width, height = int(m.group(1)), int(m.group(2))
    if width <= 0 or height <= 0:
        return None
    return width, height, normalize_aspect_ratio(text) or _closest_ratio(width, height)


def _upstream_loadimage(api_workflow: dict, ref: object, seen: set[str] | None = None) -> str | None:
    """从连线引用向上游回溯，返回第一个 LoadImage 节点 id。

    LoadImage 与 GetImageSize 之间常隔着 ImageScaleToTotalPixels / VAEEncode，
    因此不能只看直接输入；找不到时返回 None，调用方退回字面量模式。
    """
    if seen is None:
        seen = set()
    src = _linked_node(api_workflow, ref)
    if not isinstance(src, dict):
        return None
    src_id = str((ref or [""])[0])
    if src_id in seen:
        return None
    if src.get("class_type") == "LoadImage":
        return src_id
    seen.add(src_id)
    for value in (src.get("inputs") or {}).values():
        found = _upstream_loadimage(api_workflow, value, seen)
        if found:
            return found
    return None


def _loadimage_size(api_workflow: dict, node_id: str | None) -> tuple[int, int] | None:
    """读取 LoadImage 指向的图片实际像素尺寸（ComfyUI input 目录内）；失败返回 None。

    `linked-image` 模式下用它当默认宽高，避免对 Flux 系工作流返回 None 后
    画质/方向旋钮整块消失。文件不存在或无法解码属正常降级，不抛异常。
    """
    if not node_id:
        return None
    node = api_workflow.get(str(node_id))
    if not isinstance(node, dict) or node.get("class_type") != "LoadImage":
        return None
    image_name = (node.get("inputs") or {}).get("image")
    if not isinstance(image_name, str) or not image_name.strip():
        return None

    # 延迟导入：config 依赖 settings 初始化，模块顶层导入会在部分测试/脚本里形成环
    from app.config import settings

    path = settings.input_dir / image_name
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = (str(path), mtime)
    if key in _loadimage_size_cache:
        return _loadimage_size_cache[key]

    size: tuple[int, int] | None = None
    try:
        from PIL import Image as PILImage

        with PILImage.open(path) as img:
            width, height = img.size
        if width > 0 and height > 0:
            size = (int(width), int(height))
    except Exception:  # noqa: BLE001 —— 解码失败只影响默认尺寸，不阻塞提交
        size = None
    _loadimage_size_cache[key] = size
    return size


def _latent_info(api_workflow: dict) -> dict | None:
    """找出空 latent 的真实尺寸来源。

    mode:
      - literal：width/height 是字面量，项目可直接改
      - resolver：上游有 aspect_ratio + megapixels（ResolutionSelector）
      - preset：上游是固定尺寸 preset（ResolutionPresetPicker）
      - megapixels：只有 megapixels，没有比例旋钮
      - linked-image：宽高来自 GetImageSize（Flux 系），默认值取该图实际像素

    unit：字面量/preset 用 1e6；ResolutionSelector 与 ImageScaleToTotalPixels
    的 megapixels 实际是 1024²（MiP），按错单位会偏小约 2.4%/边。
    """
    for node_id, node in api_workflow.items():
        if not isinstance(node, dict) or node.get("class_type") not in _LATENT_NODE_TYPES:
            continue
        inputs = node.get("inputs") or {}
        width = _as_int(inputs.get("width"))
        height = _as_int(inputs.get("height"))
        if width and height:
            return {
                "mode": "literal", "id": node_id, "node": node,
                "width": width, "height": height,
                "megapixels": width * height / 1_000_000,
                "ratio": _closest_ratio(width, height), "multiple": 16,
                "unit": 1_000_000,
            }

        src = _linked_node(api_workflow, inputs.get("width")) or \
            _linked_node(api_workflow, inputs.get("height"))
        if not isinstance(src, dict):
            continue
        src_inputs = src.get("inputs") or {}
        ratio_raw = src_inputs.get("aspect_ratio") or src_inputs.get("resolution") or \
            src_inputs.get("size")
        ratio = normalize_aspect_ratio(ratio_raw)
        mp = src_inputs.get("megapixels")
        raw_multiple = _as_int(src_inputs.get("multiple"))
        if ratio and isinstance(mp, (int, float)) and not isinstance(mp, bool):
            multiple = raw_multiple or 8  # ResolutionSelector 的默认 multiple 是 8
            unit = 1024 * 1024
            width, height = compute_aspect_size(ratio, float(mp), multiple, unit)
            return {
                "mode": "resolver", "id": node_id, "node": node, "src": src,
                "width": width, "height": height, "megapixels": float(mp),
                "ratio": ratio, "multiple": multiple, "unit": unit,
            }

        preset = _parse_preset(src_inputs.get("preset"))
        if preset:
            width, height, ratio = preset
            return {
                "mode": "preset", "id": node_id, "node": node, "src": src,
                "width": width, "height": height,
                "megapixels": width * height / 1_000_000,
                "ratio": ratio, "multiple": 16, "unit": 1_000_000,
            }

        if isinstance(mp, (int, float)) and not isinstance(mp, bool):
            ratio = _closest_ratio(1, 1)
            multiple = raw_multiple or 16
            unit = 1024 * 1024
            width, height = compute_aspect_size(ratio, float(mp), multiple, unit)
            return {
                "mode": "megapixels", "id": node_id, "node": node, "src": src,
                "width": width, "height": height, "megapixels": float(mp),
                "ratio": ratio, "multiple": multiple, "unit": unit,
            }

        # linked-image：宽高指向 GetImageSize（PornMaster/Flux 系）。
        # 向上回溯到 LoadImage，用该图实际像素作为默认尺寸；注入时仍写字面量覆盖，
        # 所以画质/方向旋钮对这类工作流同样有效。
        if isinstance(src, dict) and src.get("class_type") == "GetImageSize":
            image_node = _upstream_loadimage(
                api_workflow, (src.get("inputs") or {}).get("image"),
            )
            if not image_node:
                continue
            size = _loadimage_size(api_workflow, image_node)
            placeholder = size is None
            if placeholder:
                # 工作流里的默认图名往往只是占位（提交前才注入用户图），
                # 文件缺失时用 1024² 兜底，保证旋钮可用；真正注入会写字面量覆盖。
                size = (1024, 1024)
            width, height = size
            info = {
                "mode": "linked-image", "id": node_id, "node": node, "src": src,
                "width": width, "height": height,
                "megapixels": width * height / 1_000_000,
                "ratio": _closest_ratio(width, height),
                "multiple": 16, "unit": 1_000_000,
            }
            if placeholder:
                info["size_source"] = "placeholder"
            return info
    return None

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


def _allowed_preset_ratios() -> list[str]:
    """ResolutionPresetPicker 实际支持的比例；拿不到 object_info 时退回静态表。"""
    options = _get_combo_options("ResolutionPresetPicker", "preset")
    ratios: list[str] = []
    for option in options:
        ratio = normalize_aspect_ratio(option)
        if ratio and ratio not in ratios:
            ratios.append(ratio)
    return ratios or list(NATIVE_PRESET_RATIOS)


def _allowed_resolver_ratios() -> list[str]:
    """ResolutionSelector 实际支持的比例；拿不到 object_info 时退回静态表。"""
    options = _get_combo_options("ResolutionSelector", "aspect_ratio")
    ratios: list[str] = []
    for option in options:
        ratio = normalize_aspect_ratio(option)
        if ratio and ratio not in ratios:
            ratios.append(ratio)
    return ratios or list(NATIVE_RESOLVER_RATIOS)


def _cap_latent_to_final_long_side(
    width: float, height: float, post_scale: float, multiple: int,
) -> tuple[int, int]:
    """按第二程倍率反推第一程尺寸，保证成品长边不超过 MAX_FINAL_LONG_SIDE。"""
    if post_scale <= 1.0 or max(width, height) * post_scale <= MAX_FINAL_LONG_SIDE:
        return int(round(width)), int(round(height))
    k = MAX_FINAL_LONG_SIDE / (max(width, height) * post_scale)
    return _round_to(width * k, multiple), _round_to(height * k, multiple)


def _reciprocal_ratio(ratio: str) -> str:
    """与 ratio 互为倒数的标准比例（2:3 ↔ 3:2，21:9 ↔ 9:21）。"""
    value = _RATIO_VALUES[ratio]
    return min(CANONICAL_RATIOS, key=lambda r: abs(_RATIO_VALUES[r] - 1 / value))


def _matches_orientation(ratio: str, orientation: str) -> bool:
    value = _RATIO_VALUES[ratio]
    if abs(value - 1.0) < 1e-9:
        return True
    return value > 1.0 if orientation == "landscape" else value < 1.0


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


def _fill_required_defaults(api: dict) -> None:
    """按 ComfyUI object_info 给缺失的必填输入补默认值。

    工作流是 UI 里存的，某些自定义节点升级后新增了必填项（例如
    ResolutionPresetPicker.base_name），UI 会自动填默认值但不会写回旧 JSON；
    转成 API 后这些字段缺失，/prompt 会直接 400。这里只补 object_info 明确给出
    default 的必填项，不猜链接输入。
    """
    info = get_object_info()
    if not info:
        return
    for node in api.values():
        spec = info.get(node.get("class_type", ""))
        if not isinstance(spec, dict):
            continue
        required = (spec.get("input") or {}).get("required") or {}
        for name, desc in required.items():
            if name in node["inputs"] or not isinstance(desc, list) or not desc:
                continue
            first = desc[0]
            cfg = desc[1] if len(desc) >= 2 and isinstance(desc[1], dict) else {}
            # 链接输入（[["MODEL"]] 之类）没有 default，跳过；
            # COMBO 的 first 是选项数组，通常带 default。
            if isinstance(first, list):
                if "default" in cfg:
                    node["inputs"][name] = cfg["default"]
                continue
            if first == "COMBO":
                if "default" in cfg:
                    node["inputs"][name] = cfg["default"]
                elif isinstance(desc[1], list) and desc[1]:
                    node["inputs"][name] = desc[1][0]
                continue
            if "default" in cfg:
                node["inputs"][name] = cfg["default"]


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
    api = _expand_subgraphs(workflow, api)
    _fill_required_defaults(api)
    return api


def _build_link_resolver(nodes: list, link_map: dict[int, tuple[str, int]]):
    """把 UI 的 bypass/mute 语义带到 API 连线解析里。

    ComfyUI 的 `mode=4`（bypass）和 `mode=2`（mute）只存在于 UI 格式；API 格式
    没有 mode 字段。旧实现直接把被 bypass 的节点也塞进 /prompt，导致「第二程已
    bypass」的单程工作流实际仍会执行第二程（Krea2 的 8+4 就是这样被跑出来的）。

    bypass 的语义是「把同类型输入直通到输出」，因此这里沿输出槽类型找到第一个
    同类型输入，递归解析它的上游连线；mute/never 直接丢弃。
    """
    node_by_id = {
        str(node.get("id")): node
        for node in nodes
        if isinstance(node, dict) and node.get("id") is not None
    }

    def resolve(link_id, depth: int = 0):
        if link_id is None or depth > 16:
            return None
        src = link_map.get(link_id)
        if not src:
            return None
        src_id, src_slot = src
        node = node_by_id.get(src_id)
        if node is None:
            return src
        mode = node.get("mode", 0)
        if mode == 2:  # mute
            return None
        if mode != 4:  # active
            return src

        outputs = node.get("outputs") or []
        out_type = None
        if isinstance(outputs, list) and 0 <= src_slot < len(outputs):
            out = outputs[src_slot]
            if isinstance(out, dict):
                out_type = out.get("type")

        for inp in node.get("inputs") or []:
            if not isinstance(inp, dict) or inp.get("link") is None:
                continue
            inp_type = inp.get("type")
            if out_type is None or inp_type in (out_type, "*"):
                return resolve(inp["link"], depth + 1)

        # 找不到同类型输入：断掉这条线，而不是把 bypass 节点本身提交执行
        return None

    return resolve


def _nodes_to_api(nodes: list, link_map: dict[int, tuple[str, int]]) -> dict[str, dict]:
    """把 UI 格式的 node 列表转成 API 节点；link_map 用于把连线编号还原成 [源节点, 槽位]。"""
    resolve_link = _build_link_resolver(nodes, link_map)
    api: dict[str, dict] = {}
    for node in nodes:
        node_type = node.get("type", "unknown")
        if node_type in SKIP_NODE_TYPES:
            continue
        if node.get("mode", 0) in (2, 4):
            # mute/bypass 的节点不进入 API；下游连线已由 resolve_link 直通或断开
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
                    src = resolve_link(link_id)
                    if src:
                        api[nid]["inputs"][name] = [src[0], src[1]]
                continue

            # 跳过 widgets_values 中类型不匹配的隐藏值
            while wv_idx < len(wv) and not _pytype_matches_comfy(wv[wv_idx], inp_type):
                wv_idx += 1

            if link_id is not None:
                # 有连线的 widget 类型输入：使用 link 值，但仍消耗位置
                src = resolve_link(link_id)
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


def is_video_workflow(api_workflow: dict) -> bool:
    """是否包含视频保存节点（SaveVideo / *VideoCombine*）。

    Atelier 的结果中心/画廊只处理图片，视频工作流默认不进入工作流下拉；
    需要视频时直接去 ComfyUI 跑。
    """
    for node in api_workflow.values():
        if not isinstance(node, dict):
            continue
        cls = str(node.get("class_type", ""))
        if cls == "SaveVideo" or "VideoCombine" in cls or "SaveVideo" in cls:
            return True
    return False


#: 带 negative 槽的引导节点。KSampler 系直接吃 negative；CFGGuider 供
#: SamplerCustomAdvanced 这类链路使用。
_GUIDANCE_NODES = {"KSampler", "KSamplerAdvanced", "CFGGuider"}


def _as_float(val: object) -> float | None:
    """把 widget 字面量解析成 float；连线引用 / 非数字字符串一律返回 None。"""
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val.strip())
        except ValueError:
            return None
    return None


def _negative_has_text(api_workflow: dict, ref: object, seen: set[str] | None = None) -> bool:
    """负向连线是否最终来自文本编码节点。

    `ConditioningZeroOut` 会切断判断：即使它上游是提示词，也已经被清零。
    其他条件节点（Combine / SetArea / ControlNetApply 等）继续沿条件输入回溯。
    """
    if seen is None:
        seen = set()
    if not isinstance(ref, (list, tuple)) or len(ref) != 2:
        return False
    src_id = str(ref[0])
    if src_id in seen:
        return False
    seen = seen | {src_id}
    node = api_workflow.get(src_id)
    if not isinstance(node, dict):
        return False
    cls = node.get("class_type", "")
    if cls == "ConditioningZeroOut":
        return False
    if cls in _TEXT_ENCODE_NODES:
        return True
    inputs = node.get("inputs") or {}
    for key, val in inputs.items():
        if key in ("model", "clip", "vae", "positive", "control_net", "image"):
            continue
        if _negative_has_text(api_workflow, val, seen):
            return True
    return False


def _detect_negative_effectiveness(api_workflow: dict) -> tuple[bool, float | None]:
    """负向条件是否真的参与采样，以及真实负向路径上的最大 CFG。

    - 负向来自 `ConditioningZeroOut` → 没接入，返回 (False, None)；
    - 负向来自文本节点但 cfg<=1 → 字段存在但不生效，返回 (False, cfg)；
    - 任一采样器 cfg>1 且负向来自文本节点 → 生效，返回 (True, 最大 cfg)。
    """
    cfgs: list[float] = []
    unknown_cfg = False
    for node in api_workflow.values():
        if not isinstance(node, dict) or node.get("class_type") not in _GUIDANCE_NODES:
            continue
        inputs = node.get("inputs") or {}
        if not _negative_has_text(api_workflow, inputs.get("negative")):
            continue
        cfg = _as_float(inputs.get("cfg"))
        if cfg is None:
            unknown_cfg = True
        else:
            cfgs.append(cfg)
    if unknown_cfg:
        return True, (max(cfgs) if cfgs else None)
    if not cfgs:
        return False, None
    best = max(cfgs)
    return best > 1.0, best


def _latent_size_overridable(api_workflow: dict, node: dict) -> bool:
    """空 latent 的宽高是否能被字面量覆盖（含 linked-image 场景）。

    - 宽高已是字面量：直接可改；
    - 宽高指向 GetImageSize：只要上游能回溯到 LoadImage，就能拿到默认像素并改写；
    - 其它上游计算节点（ResolutionSelector / preset 等）：沿用原有可覆盖判定。
    """
    inputs = node.get("inputs") or {}
    if _as_int(inputs.get("width")) is not None and _as_int(inputs.get("height")) is not None:
        return True
    for key in ("width", "height"):
        src = _linked_node(api_workflow, inputs.get(key))
        if not isinstance(src, dict):
            continue
        if src.get("class_type") == "GetImageSize":
            image_node = _upstream_loadimage(
                api_workflow, (src.get("inputs") or {}).get("image"),
            )
            # 只要有 LoadImage 就可写字面量覆盖；默认图文件缺失不影响可覆盖性
            if image_node:
                return True
            continue
        return True
    return False


def detect_workflow_caps(api_workflow: dict) -> dict[str, object]:
    """探测工作流能接受哪些注入项。

    判定规则与 `inject_prompt` 完全一致：只标记真正会被改到的项。
    否则前端会显示一个点了也不生效的"横竖/画质"旋钮
    （例如视频工作流没有 EmptyLatentImage，超分工作流没有横竖比旋钮）。

    `negative` 只表示结构上有没有负向输入；`negative_effective` 才表示它
    是否真的参与采样（负向来自文本节点且 cfg>1）。两者分开，UI 才能提示
    "有输入框但不会生效"，而不是假装支持。
    """
    text_nodes = [
        node for node in api_workflow.values()
        if isinstance(node, dict)
        and node.get("class_type") in _TEXT_ENCODE_NODES
        and node.get("inputs", {}).get("clip") is not None
    ]
    negative_effective, negative_cfg = _detect_negative_effectiveness(api_workflow)
    caps = {
        "prompt": bool(text_nodes),
        "negative": False,
        "negative_effective": negative_effective,
        "negative_cfg": negative_cfg,
        "quality": False,
        "orientation": False,
    }
    if text_nodes:
        spec = _TEXT_ENCODE_NODES[text_nodes[0].get("class_type")]
        caps["negative"] = bool(spec[1]) or len(text_nodes) >= 2

    has_image_input = any(
        isinstance(n, dict) and str(n.get("class_type", "")).startswith("LoadImage")
        for n in api_workflow.values()
    )

    for node in api_workflow.values():
        if not isinstance(node, dict):
            continue
        cls = node.get("class_type")
        if cls == "SeedVR2VideoUpscaler":
            caps["quality"] = True  # 4a：超分分辨率
        if cls not in _LATENT_NODE_TYPES:
            continue
        # 图生图/编辑工作流的尺寸通常由输入图决定，不暴露比例和画质；
        # 但只要独立 latent 的宽高可覆盖（字面量，或 linked-image 能回溯到输入图），
        # 就仍然暴露旋钮——PornMaster/Flux2 属于后者。
        if has_image_input and not _latent_size_overridable(api_workflow, node):
            continue
        inputs = node.get("inputs") or {}
        w = _as_int(inputs.get("width"))
        h = _as_int(inputs.get("height"))
        if w is not None and h is not None:
            caps["quality"] = True  # 按比例缩放字面量尺寸
            # 统一比例契约下，方图也能切到 9:16 等非方图
            caps["orientation"] = True
            continue
        # 尺寸由上游节点计算：无论有没有旋钮，都能按比例退回字面量宽高
        src = _linked_node(api_workflow, inputs.get("width")) or \
            _linked_node(api_workflow, inputs.get("height"))
        if not isinstance(src, dict):
            continue
        caps["quality"] = True
        caps["orientation"] = True
    return caps


def _output_scale(api_workflow: dict, latent_id: str) -> float:
    """沿 latent 到输出节点的路径累计 LatentUpscaleBy 的倍率。

    只看 API 图：被 bypass（mode=4）的节点不会出现在这里，所以 Krea2 里
    那个失效的 1.5× 不会被误算，ZIT 的 1.7× 会被算进来。
    """
    scale = 1.0
    seen: set[str] = set()
    stack = [latent_id]
    while stack:
        nid = stack.pop()
        if nid in seen:
            continue
        seen.add(nid)
        for cid, cnode in api_workflow.items():
            if not isinstance(cnode, dict):
                continue
            inputs = cnode.get("inputs") or {}
            if not any(
                isinstance(v, (list, tuple)) and len(v) == 2 and str(v[0]) == str(nid)
                for v in inputs.values()
            ):
                continue
            if cnode.get("class_type") == "LatentUpscaleBy":
                value = inputs.get("scale_by")
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    scale *= float(value)
            stack.append(cid)
    return round(scale, 4)


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
        "mp_unit": "mp",
        "post_scale": 1.0,
        "orientation_mode": "none",
        "aspect_ratios": [],
        "default_ratio": "",
        "multiple": 16,
    }
    has_seedvr = any(
        isinstance(n, dict) and n.get("class_type") == "SeedVR2VideoUpscaler"
        for n in api_workflow.values()
    )
    if has_seedvr:
        params["quality_mode"] = "seedvr"

    info = _latent_info(api_workflow)
    if info is not None and not has_seedvr:
        params["base_width"] = info["width"]
        params["base_height"] = info["height"]
        params["base_megapixels"] = round(float(info["megapixels"]), 3)
        params["mp_unit"] = "mip" if info["unit"] == 1024 * 1024 else "mp"
        post_scale = _output_scale(api_workflow, info["id"])
        params["post_scale"] = post_scale
        params["default_ratio"] = info["ratio"]
        # 按节点真实选项检测：preset 永远用 picker 自己的比例；
        # resolver 只有固定放大时才收紧，单程 resolver 允许 9:21 的字面量扩展。
        if info["mode"] == "preset":
            params["aspect_ratios"] = _allowed_preset_ratios()
        elif info["mode"] == "resolver" and post_scale > 1.0:
            params["aspect_ratios"] = _allowed_resolver_ratios()
        else:
            params["aspect_ratios"] = list(CANONICAL_RATIOS)
        params["multiple"] = info["multiple"]
        params["quality_mode"] = "megapixels" if info["mode"] in ("resolver", "megapixels") else "scale"
        params["orientation_mode"] = "swap" if info["mode"] == "literal" else "knob"
    return params


def _set_latent_size(info: dict, width: float, height: float) -> None:
    inputs = info["node"].setdefault("inputs", {})
    inputs["width"] = max(256, min(4096, int(round(width))))
    inputs["height"] = max(256, min(4096, int(round(height))))


def _pick_ratio_option(options: list[str], ratio: str) -> str | None:
    for option in options:
        if normalize_aspect_ratio(option) == ratio:
            return option
    return None


def _inject_resolution(api_workflow: dict, prompt_data: dict) -> None:
    """统一分辨率注入：比例 + 画质；未传比例时按工作流默认比例 + 横竖推导。"""
    quality = prompt_data.get("quality", "1.0x")
    scale = quality_scale(quality)
    quality_key = normalize_quality(quality)

    seedvr_quality_map = {
        "0.75x": (2160, 3840), "1.0x": (2560, 4096),
        "1.25x": (3200, 5120), "1.5x": (3840, 6400), "2.0x": (5120, 8192),
    }
    if quality_key in seedvr_quality_map:
        res, max_res = seedvr_quality_map[quality_key]
        for node in api_workflow.values():
            if isinstance(node, dict) and node.get("class_type") == "SeedVR2VideoUpscaler":
                node["inputs"]["resolution"] = res
                node["inputs"]["max_resolution"] = max_res
                return

    info = _latent_info(api_workflow)
    if info is None:
        return

    requested = normalize_aspect_ratio(prompt_data.get("aspect_ratio"))
    orientation = prompt_data.get("orientation", "portrait")
    implicit_ratio = requested is None

    # 没传比例时按工作流默认比例；横竖只决定用默认比例还是它的倒数比例。
    # 不再退回"宽高 × 倍率"，否则同一个档位会因调用方是否传比例产生两种尺寸。
    if implicit_ratio:
        requested = info["ratio"]
        if not _matches_orientation(requested, orientation):
            requested = _reciprocal_ratio(requested)

    post_scale = _output_scale(api_workflow, info["id"])
    if post_scale > 1.0:
        if info["mode"] == "preset":
            allowed = _allowed_preset_ratios()
        elif info["mode"] == "resolver":
            allowed = _allowed_resolver_ratios()
        else:
            allowed = None
        if allowed and requested not in allowed:
            raise RatioNotSupported(
                f"该工作流只支持 {', '.join(allowed)}，已拒绝 {requested}；"
                "请改用支持该比例的工作流"
            )

    target_mp = float(info["megapixels"]) * scale * scale

    if info["mode"] == "resolver":
        src = info.get("src") or {}
        src_inputs = src.get("inputs", {}) if isinstance(src, dict) else {}
        picked = _pick_ratio_option(
            _get_combo_options(src.get("class_type", ""), "aspect_ratio"), requested,
        )
        if picked and isinstance(src_inputs.get("megapixels"), (int, float)):
            width, height = compute_aspect_size(
                requested, target_mp, info["multiple"], info["unit"],
            )
            capped_w, capped_h = _cap_latent_to_final_long_side(
                width, height, post_scale, info["multiple"],
            )
            # 未触发上限时保留原始 target_mp，避免宽高取整带来 2.16 → 2.159 的漂移。
            capped_mp = target_mp if (capped_w, capped_h) == (width, height) \
                else (capped_w * capped_h) / info["unit"]
            src_inputs["aspect_ratio"] = picked
            src_inputs["megapixels"] = round(max(0.1, min(16.0, capped_mp)), 3)
            logger.info("分辨率：%s aspect_ratio=%s, megapixels=%s",
                        src.get("class_type"), picked, src_inputs["megapixels"])
            return
        # 旋钮不支持该比例时退回字面量，单位与旋钮一致（MiP）
        width, height = compute_aspect_size(requested, target_mp, info["multiple"], info["unit"])
        width, height = _cap_latent_to_final_long_side(
            width, height, post_scale, info["multiple"],
        )
        _set_latent_size(info, width, height)
        return

    # literal / preset / megapixels：默认比例 + 1.0× 保持原生尺寸，其余按比例重算
    if requested == info["ratio"] and abs(scale - 1.0) < 1e-9:
        width, height = _cap_latent_to_final_long_side(
            info["width"], info["height"], post_scale, info["multiple"],
        )
        _set_latent_size(info, width, height)
        return
    # 旧调用只给横竖时，倒数比例 + 1.0× 仍是"原生宽高交换"，与历史输出逐像素一致
    if implicit_ratio and info["mode"] == "literal" and abs(scale - 1.0) < 1e-9 \
            and requested == _reciprocal_ratio(info["ratio"]):
        width, height = _cap_latent_to_final_long_side(
            info["height"], info["width"], post_scale, info["multiple"],
        )
        _set_latent_size(info, width, height)
        return
    width, height = compute_aspect_size(requested, target_mp, info["multiple"], info["unit"])
    width, height = _cap_latent_to_final_long_side(
        width, height, post_scale, info["multiple"],
    )
    _set_latent_size(info, width, height)


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
        negative_effective, _negative_cfg = _detect_negative_effectiveness(api_workflow)
        compiled = compile_prompt(
            str(prompt_data.get("prompt") or ""),
            str(prompt_data.get("negative_prompt") or ""),
            negative_effective=negative_effective,
        )
        _nid, _node, (_pos_field, _neg_field) = text_nodes[0]
        _node["inputs"][_pos_field] = compiled.positive
        # 负向不生效时不提交任何负向内容，避免留下"写了但没用"的假象。
        _negative = compiled.negative if negative_effective else ""
        if _neg_field:
            # 单节点自带负面字段（如 Qwen-Image 2.1），直接写同一个节点
            _node["inputs"][_neg_field] = _negative
        elif len(text_nodes) >= 2:
            # 旧行为：第二个文本编码节点当负面
            text_nodes[1][1]["inputs"][text_nodes[1][2][0]] = _negative
        prompt_data["compiled"] = compiled.as_dict()

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

    # 3. 注入分辨率（比例 + 画质）；旧调用只传 orientation 时行为保持一致
    _inject_resolution(api_workflow, prompt_data)

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


def set_save_subfolder(api_workflow: dict, subfolder: str) -> int:
    """把输出子目录写进自带 `subfolder` 输入的自定义保存节点。

    常见 `SaveImage` 用 `filename_prefix` 承载子目录（见 `prepend_output_subfolder`），
    但 `SaveImageFromSource` 用的是独立的 `subfolder` 字段，前两个函数对它都是空转。
    这里只认这一个已知类名，避免误改其它自定义保存节点的同名输入。
    """
    prefix = (subfolder or "").strip().strip("/\\")
    if not prefix:
        return 0
    n = 0
    for node in api_workflow.values():
        if not isinstance(node, dict):
            continue
        if node.get("class_type") != "SaveImageFromSource":
            continue
        inputs = node.get("inputs")
        if isinstance(inputs, dict) and isinstance(inputs.get("subfolder"), str):
            inputs["subfolder"] = prefix
            n += 1
    return n


def prepend_output_subfolder(api_workflow: dict, subfolder: str) -> int:
    """给所有保存节点的 filename_prefix 加一层相对子目录，返回改动节点数。

    与 `set_output_prefix` 的区别：这里保留工作流原前缀和 `inject_prompt`
    追加的唯一后缀，只在最前面加目录。subfolder 为空时完全不动。
    """
    prefix = (subfolder or "").strip().strip("/")
    if not prefix:
        return 0
    n = 0
    for node in api_workflow.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict) or "filename_prefix" not in inputs:
            continue
        cls = node.get("class_type", "")
        if cls in _SAVE_NODE_TYPES or "Save" in cls or "Export" in cls or "Output" in cls:
            original = inputs.get("filename_prefix") or ""
            inputs["filename_prefix"] = f"{prefix}/{original}" if original else prefix
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


def loadimage_role(title: str) -> str | None:
    """按 LoadImage 标题判定业务角色：portrait / costume / pose / extra。

    工作流标题是人写的（例如“图3：姿势参考 (Pose) · 深度图”），这里的“图3”
    是提示词编号而不是槽位编号，所以只认角色关键词，不解析标题里的数字。
    """
    text = (title or "").lower()
    for role, keywords in _LOADIMAGE_ROLE_KEYWORDS:
        if any(word in text for word in keywords):
            return role
    return None


def image_input_key_index(key: str) -> int | None:
    """解析文本编码器的参考图键名，返回图号：images.image_3 / image3 → 3。"""
    match = _IMAGE_INPUT_KEY_RE.match(key or "")
    if not match:
        return None
    return int(match.group(1) or match.group(2))


def find_image_input_keys(api_workflow: dict, node_id: str) -> list[tuple[str, str]]:
    """找出所有文本编码器里指向该 LoadImage 的参考图键 [(编码节点 id, 键名)]。"""
    target = str(node_id)
    out: list[tuple[str, str]] = []
    for enc_id, node in api_workflow.items():
        if not isinstance(node, dict) or node.get("class_type") not in _TEXT_ENCODE_NODES:
            continue
        for key, value in (node.get("inputs") or {}).items():
            if image_input_key_index(key) is None:
                continue
            if isinstance(value, (list, tuple)) and len(value) == 2 \
                    and str(value[0]) == target:
                out.append((str(enc_id), key))
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

    # HEIC/HEIF（包括改名成 .jpg 的）ComfyUI 读不了：先转成 PNG 再注入
    heif = is_heif(src)

    def materialize(dst: Path) -> None:
        if heif:
            convert_heif_to_png(src, dst)
        else:
            shutil.copy2(str(src), str(dst))

    if dest_name:
        dst_name = dest_name
        if heif:
            # 只换扩展名，保留 atelier_upscale/... 这种子目录写法与原分隔符
            base, dot, _ = dst_name.rpartition(".")
            dst_name = f"{base}.png" if dot else f"{dst_name}.png"
        dst_path = Path(dest_dir) / dst_name
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        if not dst_path.exists():  # 同名已存在则复用，不重复拷贝
            materialize(dst_path)
    else:
        # 生成唯一文件名，避免覆盖
        ts = int(time.time() * 1000)
        name = f"{src.stem}.png" if heif else src.name
        dst_name = f"atelier_process_{ts}_{name}"
        dst_path = Path(dest_dir) / dst_name
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        materialize(dst_path)

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
