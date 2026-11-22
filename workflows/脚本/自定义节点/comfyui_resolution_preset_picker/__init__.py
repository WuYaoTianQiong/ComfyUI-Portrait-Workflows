class ResolutionPresetPicker:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "preset": (
                    [
                        "640x960 （2:3）",
                        "800x1200 （2:3）",
                        "768x1024 （3:4）",
                        "720x1280 （9:16）",
                        "960x640 （3:2）",
                        "1024x768 （4:3）",
                        "1280x720 （16:9）",
                        "1024x1024 （1:1）",
                    ],
                    {"default": "640x960 （2:3）"},
                ),
                # 新增（2026-10-04）：出图文件名基名。缺省仍是 MoodyZIT，老工作流不受影响；
                # Krea2 工作流可传 "MoodyKrea2"，把两条模型线的出图分开编号。
                "base_name": ("STRING", {"default": "MoodyZIT", "multiline": False}),
            }
        }

    RETURN_TYPES = ("INT", "INT", "STRING",)
    RETURN_NAMES = ("width", "height", "filename_prefix",)
    FUNCTION = "pick"
    CATEGORY = "utils"

    def pick(self, preset, base_name="MoodyZIT"):
        table = {
            "640x960 （2:3）": (640, 960),
            "800x1200 （2:3）": (800, 1200),
            "768x1024 （3:4）": (768, 1024),
            "720x1280 （9:16）": (720, 1280),
            "960x640 （3:2）": (960, 640),
            "1024x768 （4:3）": (1024, 768),
            "1280x720 （16:9）": (1280, 720),
            "1024x1024 （1:1）": (1024, 1024),
        }
        w, h = table[preset]
        # 从预设名中提取宽高比，如 "640x960 （2:3）" → "2-3"
        # 从预设名中提取宽高比，用 × 代替 :（Windows 文件名非法）
        ratio = preset.split("（")[1].rstrip("）").replace(":", "×")
        base = (base_name or "MoodyZIT").strip() or "MoodyZIT"
        prefix = f"{base}_{ratio}"
        return (w, h, prefix,)


NODE_CLASS_MAPPINGS = {
    "ResolutionPresetPicker": ResolutionPresetPicker,
}


# ---------------------------------------------------------------------------
# 画幅与倍率（下拉）：比例 + 原生像素量 + 画质倍率，三个都是下拉。
#
# 为什么不用原生 ResolutionSelector：它的 megapixels 是手填浮点，单位是 MiP
# （1024×1024），还得自己心算会出多大。这里拆成「原生像素量（该工作流本来多大）」
# × 「画质倍率（0.25x~2.0x）」——倍率与 Atelier 的画质档同名同义，1:1 对得上。
#
# 面积 = 原生面积 × 倍率²，所以 1.5x 是 2.25 倍面积，不是 1.5 倍。
# API 里同时保留 aspect_ratio / multiple 名称，Atelier 的 resolver 识别照旧可用。
# ---------------------------------------------------------------------------
import math

_ASPECTS = {
    "1:1 (Square)": (1, 1),
    "2:3 (Portrait Photo)": (2, 3),
    "3:2 (Landscape Photo)": (3, 2),
    "3:4 (Portrait Standard)": (3, 4),
    "4:3 (Standard)": (4, 3),
    "9:16 (Portrait Widescreen)": (9, 16),
    "16:9 (Widescreen)": (16, 9),
    "21:9 (Cinematic)": (21, 9),
}

# 原生像素量（MiP）。1.5 / 2.16 / 2.34 / 2.4 是本机 5 个文生图工作流的实际原生值。
BASE_MEGAPIXELS = [1.0, 1.25, 1.5, 1.8, 2.16, 2.34, 2.4, 3.0, 4.0]

# 与 Atelier app/services/quality_keys.py 的 QUALITY_SCALES 保持一致
QUALITY_SCALES = {
    "0.25x": 0.25,
    "0.5x": 0.5,
    "0.75x": 0.75,
    "1.0x": 1.0,
    "1.25x": 1.25,
    "1.5x": 1.5,
    "2.0x": 2.0,
}


class ResolutionSizer:
    """比例 × 原生像素量 × 画质倍率 → width / height"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "aspect_ratio": (list(_ASPECTS.keys()), {"default": "9:16 (Portrait Widescreen)"}),
                "base_megapixels": (BASE_MEGAPIXELS, {"default": 2.4}),
                "quality": (list(QUALITY_SCALES.keys()), {"default": "1.0x"}),
                "multiple": ("INT", {"default": 8, "min": 1, "max": 256, "step": 1}),
            }
        }

    RETURN_TYPES = ("INT", "INT")
    RETURN_NAMES = ("width", "height")
    FUNCTION = "size"
    CATEGORY = "utils"

    def size(self, aspect_ratio, base_megapixels, quality="1.0x", multiple=8):
        a, b = _ASPECTS.get(aspect_ratio, (9, 16))
        scale = QUALITY_SCALES.get(quality, 1.0)
        mp = float(base_megapixels) * scale * scale
        w = math.sqrt(mp * 1024 * 1024 * a / b)
        h = w * b / a
        m = max(1, int(multiple))
        return (max(m, int(round(w / m)) * m), max(m, int(round(h / m)) * m))


NODE_CLASS_MAPPINGS["ResolutionSizer"] = ResolutionSizer

NODE_DISPLAY_NAME_MAPPINGS = {
    "ResolutionPresetPicker": "分辨率预设选择器",
    "ResolutionSizer": "画幅与倍率（下拉）",
}

# 前端扩展：在节点底部实时显示当前下拉会出的像素（web/size_label.js）
WEB_DIRECTORY = "./web"
