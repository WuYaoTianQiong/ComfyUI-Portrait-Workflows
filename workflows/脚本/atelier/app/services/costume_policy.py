"""随机配方的服装完整性启发式（P4 safety）。

背景（2026-11-06 实测）：只描述上衣的配方（例如「正装衬衫」）在
`body_mode=costume` 下会让模型补出下装甚至裸露；这是数据不完整，不是
工作流错误。随机整套必须跳过这类配方，手动碎片弹层则给警告。

这里只做**保守关键词判定**：命中下装/连体/长袍类词才算覆盖下半身；
命中明确的“无下装/赤裸”短语直接判不完整。它不是语义模型，无法保证
全覆盖；新增配方仍应人工抽检。
"""

from __future__ import annotations

#: 足以覆盖下半身的服装词（裙/裤/连体/长袍类）。
LOWER_COVERAGE_KEYWORDS: tuple[str, ...] = (
    "裤", "裙", "连衣裙", "连体", "套装", "汉服", "和服", "浴衣",
    "婚纱", "礼服", "长袍", "长衫", "下摆", "衣摆",
    "短裤", "长裤", "半身裙", "牛仔裤", "百褶裙", "包臀裙",
    "比基尼", "泳装", "丝袜", "打底",
)

#: 明确的“没有下装 / 裸露”措辞，优先级高于上面关键词。
UNSAFE_PHRASES: tuple[str, ...] = (
    "无可见的下装", "无下装", "没有下装", "里面什么都没穿",
    "全身赤裸", "赤裸", "裸体",
)

#: “只穿内裤/内衣”类措辞：含「内裤/内衣」且带 only 语义时，不算覆盖。
UNDERWEAR_TERMS: tuple[str, ...] = ("内裤", "内衣")
UNDERWEAR_ONLY_PHRASES: tuple[str, ...] = (
    "下身只穿", "下半身只穿", "只穿内裤", "仅穿内裤",
    "只穿内衣", "仅穿内衣", "只穿一条内裤",
)

#: safe_mode 随机的明确裸露内容词（窄口径，避免误伤「裸色口红」等正常描述）。
EXPLICIT_CONTENT_TERMS: tuple[str, ...] = (
    "全身赤裸", "赤裸", "裸体", "乳房", "乳头", "下体", "阴部",
    "性交", "做爱", "情趣", "胸部裸露", "下体裸露",
)


def costume_covers_lower(text: str | None) -> bool:
    """服装描述是否覆盖下半身；空文本视为不完整。"""
    value = (text or "").strip()
    if not value:
        return False
    if any(phrase in value for phrase in UNSAFE_PHRASES):
        return False
    if any(phrase in value for phrase in UNDERWEAR_ONLY_PHRASES):
        return False
    if any(term in value for term in UNDERWEAR_TERMS) and any(
        phrase in value for phrase in ("下身只穿", "下半身只穿", "只穿", "仅穿", "只有一条")
    ):
        return False
    return any(keyword in value for keyword in LOWER_COVERAGE_KEYWORDS)


def has_explicit_content(text: str | None) -> bool:
    """safe_mode 随机用的明确裸露内容判定（仅覆盖窄口径词）。"""
    value = text or ""
    return any(term in value for term in EXPLICIT_CONTENT_TERMS)


def costume_coverage_warning(text: str | None) -> str:
    """手动碎片弹层用的警告；空文本不提示（可能用图片补服装）。"""
    value = (text or "").strip()
    if not value or costume_covers_lower(value):
        return ""
    return "服装描述不完整：未写明下装，可能生成裸露"
