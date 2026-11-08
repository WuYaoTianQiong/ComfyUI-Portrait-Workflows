"""画质档位键的唯一归一规则。

内部历史键 `2K/4K/6K/8K/12K` 只是倍率别名，不是真实像素，也不该进库/进界面。
统一存 `0.75x/1.0x/1.25x/1.5x/2.0x`；旧键在写入与迁移时归一，读取时两边都认。
"""

from __future__ import annotations

QUALITY_SCALES: dict[str, float] = {
    # 0.25x / 0.5x 是 2026-11-08 新增的「低画质快速验证」档：
    # 0.25x 约 0.066MP、0.5x 约 0.26MP，仅用于人眼/检测器能看清基本要素的场景。
    "0.25x": 0.25,
    "0.5x": 0.5,
    "0.75x": 0.75,
    "1.0x": 1.0,
    "1.25x": 1.25,
    "1.5x": 1.5,
    "2.0x": 2.0,
}

# 旧 UI / 历史库里的内部键；"high" 是更早版本的遗留值。
ALIASES: dict[str, str] = {
    "2K": "0.75x",
    "4K": "1.0x",
    "6K": "1.25x",
    "8K": "1.5x",
    "12K": "2.0x",
    "high": "1.0x",
}


def normalize_quality(value: str | None) -> str:
    """把任意历史写法归一成 `0.25x…2.0x`；未知值原样保留，避免静默改数据。"""
    if not value:
        return "1.0x"
    text = str(value).strip()
    if text in ALIASES:
        return ALIASES[text]
    return text


def quality_scale(value: str | None) -> float:
    """取倍率；未知值按 1.0× 处理（与旧注入行为一致）。"""
    return QUALITY_SCALES.get(normalize_quality(value), 1.0)
