"""结构化提示词（Composition）的唯一解析/渲染实现。

审计 01 发现同一套 `【类型】内容` 格式在项目里有 4 份不同的正则：
  shared.py 的 parse / extract、models.py 的 classify、comfyui.py 的三处 strip。
本模块把它们收成一份，任何格式变化只改这里。

约定（与现有 308 条提示词一致）：
  · 一个 fragment = 【类型】 + 换行 + 内容，fragment 之间用空行分隔
  · 类型固定为 FRAGMENT_TYPES 的 8 类；未知类型只做保留，不报错
  · 允许正文里出现普通方括号，只有 【...】 算标题
"""

from __future__ import annotations

import re

FRAGMENT_TYPES = [
    "人物面部", "人物身材", "人物服饰", "姿态动作",
    "拍摄视角", "场景环境", "光影色调", "画风技术",
]

# 标题：任意非空、不含 】 的类型名
_HEADER_RE = re.compile(r"【([^】]+)】")
# 块：标题到下一个「行首标题」或文本末尾
_BLOCK_RE = re.compile(r"【([^】]+)】\s*(.*?)(?=\n【|$)", re.DOTALL)


def parse(text: str | None) -> list[dict]:
    """把提示词文本解析成 [{type, content}]。空文本返回 []。"""
    if not text:
        return []
    fragments: list[dict] = []
    for match in _BLOCK_RE.finditer(text):
        ftype = match.group(1).strip()
        content = match.group(2).strip()
        if content:
            fragments.append({"type": ftype, "content": content})
    return fragments


def extract(text: str | None, fragment_type: str) -> str:
    """取指定类型的碎片内容；没有则返回空串。"""
    if not text or not fragment_type:
        return ""
    for fragment in parse(text):
        if fragment["type"] == fragment_type:
            return fragment["content"]
    return ""


def types_in(text: str | None) -> list[str]:
    """文本中出现过的类型名（按出现顺序，含重复）。"""
    if not text:
        return []
    return [m.group(1).strip() for m in _HEADER_RE.finditer(text)]


def is_structured(text: str | None) -> bool:
    return bool(text) and bool(_HEADER_RE.search(text))


def strip_headers(text: str | None) -> str:
    """去掉所有【类型】标题，只留正文 —— 提交给 ComfyUI 的就是这个形态。"""
    if not text:
        return ""
    return _HEADER_RE.sub("", text).strip()


def render(fragments: list[dict]) -> str:
    """把碎片列表渲染回标准文本。与前端组合创作使用同一格式。"""
    parts = []
    for fragment in fragments or []:
        ftype = (fragment.get("type") or "").strip()
        content = (fragment.get("content") or "").strip()
        if not ftype or not content:
            continue
        parts.append(f"【{ftype}】\n{content}")
    return "\n\n".join(parts)


def classify(text: str | None) -> str | None:
    """按类型数量分档：>=4 组合 / 1-3 单项 / 0 零散。与旧版 models.classify_prompt_text 等价。"""
    if not text:
        return None
    n_types = len(set(types_in(text)))
    if n_types == 0:
        return "scattered"
    if n_types >= 4:
        return "composite"
    return "single"


def validate(text: str | None) -> list[str]:
    """返回问题列表（空列表 = 没问题）。用于导入/编辑时的提示，不做强制拦截。"""
    problems: list[str] = []
    if not text:
        return problems

    fragments = parse(text)
    headers = types_in(text)

    if headers and not fragments:
        problems.append("有【类型】标题但没有正文内容")
    if len(headers) != len(fragments):
        problems.append(f"检测到 {len(headers)} 个标题，但只有 {len(fragments)} 段有内容")

    seen: set[str] = set()
    for fragment in fragments:
        ftype = fragment["type"]
        if ftype in seen:
            problems.append(f"类型「{ftype}」重复出现")
        seen.add(ftype)
        if ftype not in FRAGMENT_TYPES:
            problems.append(f"类型「{ftype}」不在标准 8 类中")

    return problems
