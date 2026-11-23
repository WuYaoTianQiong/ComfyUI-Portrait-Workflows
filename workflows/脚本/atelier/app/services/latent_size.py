# -*- coding: utf-8 -*-
"""比例与 latent 尺寸的纯计算（从 workflow_parser 抽出，2026-11-22）。

为什么单独一文件：workflow_parser.py 已到 1800+ 行并被 tools/guard_limits.py 冻结，
尺寸相关的改动都在这里，抽出来以后改尺寸不再顶体量上限。

约定：
  - unit 是"百万像素"的单位：字面量/preset 用 1e6，ComfyUI 的 ResolutionSelector /
    ResolutionSizer 用 1024²（即 MiP），乘错单位会让每边偏小约 2.4%；
  - 所有宽高都对齐到 multiple，避免 VAE patch 非整除。
"""
from __future__ import annotations

import math
import re

# 第二程（post_scale）输出长边上限。超过后 ZIT 用固定 1.7× 硬拉会出现
# 底部货架/地面拼贴；2048 是 9:16 三 seed 验证过的安全阈值。
MAX_FINAL_LONG_SIDE = 2048

# 单程 latent 边长上限：写进 EmptyLatentImage 的宽高统一截断到该范围，
# 避免高倍率档位把边长推到显存红线；**预演必须用同一上限**，否则标注会虚高。
MAX_LATENT_SIDE = 4096
MIN_LATENT_SIDE = 256
# 0.1x 极低档专用下限：0.1x 在 1.5MP 基准下目标短边约 100px，
# 仍按 256 抬升会与 0.25x 夹成同一尺寸（0.1x 反而更大），档位就成摆设。
# 只对 0.1x 及更低倍率生效，其它档位（含 0.25x）的产出保持原样。
MIN_LATENT_SIDE_ULTRA_LOW = 128


def min_latent_side_for_scale(scale: float) -> int:
    """按倍率选 latent 短边下限：0.1x 及更小用 128，其它沿用 256。"""
    return MIN_LATENT_SIDE_ULTRA_LOW if scale <= 0.1 + 1e-9 else MIN_LATENT_SIDE

# 项目统一比例；包含 ResolutionSelector 的 8 个选项 + 21:9 的竖版 9:21。
CANONICAL_RATIOS = ("1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9", "9:21")
_RATIO_VALUES = {
    ratio: int(ratio.split(":")[0]) / int(ratio.split(":")[1]) for ratio in CANONICAL_RATIOS
}

_RATIO_RE = re.compile(r"\s*(\d+(?:\.\d+)?)\s*[:：]\s*(\d+(?:\.\d+)?)")


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


def _cap_latent_to_final_long_side(
    width: float, height: float, post_scale: float, multiple: int,
) -> tuple[int, int]:
    """按第二程倍率反推第一程尺寸，保证成品长边不超过 MAX_FINAL_LONG_SIDE。"""
    if post_scale <= 1.0 or max(width, height) * post_scale <= MAX_FINAL_LONG_SIDE:
        return int(round(width)), int(round(height))
    k = MAX_FINAL_LONG_SIDE / (max(width, height) * post_scale)
    return _round_to(width * k, multiple), _round_to(height * k, multiple)


def _fit_latent_size(
    width: float, height: float, multiple: int, min_side: int = MIN_LATENT_SIDE,
) -> tuple[int, int]:
    """把 latent 宽高收进 [min_side, MAX_LATENT_SIDE]，越界时**等比**缩放。

    不能只截断超限的那一边：9:16 的 2352×4176 截成 2352×4096 只有 0.574，
    用户选的比例被悄悄压走样，而档位本来只是相对倍率，少几个像素看不出来。
    所以越界时整体缩放到长边正好 4096（或短边抬到 min_side），再对齐 multiple；
    对齐若又顶出边界就逐格收回。未越界时保持原值，原生尺寸一个像素都不动。
    min_side 由调用方按倍率给（0.1x 档用 128，见 min_latent_side_for_scale）。
    """
    longest, shortest = max(width, height), min(width, height)
    if min_side <= shortest and longest <= MAX_LATENT_SIDE:
        return int(round(width)), int(round(height))

    k = (MAX_LATENT_SIDE / longest) if longest > MAX_LATENT_SIDE \
        else (min_side / shortest)
    out_w = _round_to(width * k, multiple)
    out_h = _round_to(height * k, multiple)
    while max(out_w, out_h) > MAX_LATENT_SIDE:
        if out_w >= out_h:
            out_w -= multiple
        else:
            out_h -= multiple
    while min(out_w, out_h) < min_side:
        if out_w <= out_h:
            out_w += multiple
        else:
            out_h += multiple
    return out_w, out_h
