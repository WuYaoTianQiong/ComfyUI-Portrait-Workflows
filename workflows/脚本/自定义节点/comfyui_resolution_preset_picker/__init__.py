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
# 画幅与倍率（下拉）：把 ComfyUI 原生 ResolutionSelector 的 megapixels 数字框
# 换成下拉。宽高由「比例 × 像素量」算出，单位与 ResolutionSelector 一致：
# megapixels 是 MiP（1024×1024），不是 100 万像素。
#
# 为什么要有它：原生节点要手动填 2.4 这种浮点，还得心算会出多大；两个下拉
# 一眼可选。API 里 aspect_ratio / megapixels / multiple 的名称与原生节点一致，
# Atelier 的 resolver 识别逻辑不用改（megapixels 仍是浮点数）。
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

# 下拉里的像素量档位（MiP）。0.55 草稿 ~ 3.0 大图，覆盖 12G 卡的实际可用区间。
MEGAPIXEL_STEPS = [0.4, 0.55, 0.75, 1.0, 1.25, 1.5, 1.8, 2.16, 2.34, 2.4, 3.0, 4.0]


class ResolutionSizer:
    """比例 + 倍率两个下拉 → 直接输出 width / height"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "aspect_ratio": (list(_ASPECTS.keys()), {"default": "9:16 (Portrait Widescreen)"}),
                "megapixels": (MEGAPIXEL_STEPS, {"default": 2.4}),
                "multiple": ("INT", {"default": 8, "min": 1, "max": 256, "step": 1}),
            }
        }

    RETURN_TYPES = ("INT", "INT")
    RETURN_NAMES = ("width", "height")
    FUNCTION = "size"
    CATEGORY = "utils"

    def size(self, aspect_ratio, megapixels, multiple=8):
        a, b = _ASPECTS.get(aspect_ratio, (9, 16))
        unit = 1024 * 1024
        w = math.sqrt(float(megapixels) * unit * a / b)
        h = w * b / a
        m = max(1, int(multiple))
        return (max(m, int(round(w / m)) * m), max(m, int(round(h / m)) * m))


NODE_CLASS_MAPPINGS["ResolutionSizer"] = ResolutionSizer

NODE_DISPLAY_NAME_MAPPINGS = {
    "ResolutionPresetPicker": "分辨率预设选择器",
    "ResolutionSizer": "画幅与倍率（下拉）",
}

