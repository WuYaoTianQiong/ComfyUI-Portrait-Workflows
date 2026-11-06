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

#: 碎片池「安全模式」的启发式关键词（方案 §3 C8）。
#: 只匹配 `prompts.tags` / `prompts.note`，**不看正文** —— 正文里的正常描述
#: （如「裸色口红」「成人向？」）一旦被误伤，碎片池会莫名缺条目。
#: 这是启发式，无法保证全覆盖；命中即整条提示词的所有碎片一起隐藏。
NSFW_KEYWORDS: tuple[str, ...] = (
    "nsfw", "18+", "裸体", "裸露", "情色", "成人", "情趣", "内衣", "比基尼", "泳装",
)


def contains_nsfw_keyword(*texts: str | None) -> bool:
    """tags / note 是否命中 NSFW 启发式关键词（大小写不敏感）。"""
    haystack = " ".join(text for text in texts if text).lower()
    if not haystack:
        return False
    return any(keyword in haystack for keyword in NSFW_KEYWORDS)

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


# 分块：空行分隔（与库里的存量写法一致；允许行尾空白）
_BLOCK_SEP_RE = re.compile(r"\n\s*\n")
# 块首标题：`【类型】` 紧跟正文（正文可跨行）
_BLOCK_START_RE = re.compile(r"^\s*【([^】]+)】\s*([\s\S]*)$")


def split_marked(text: str | None) -> tuple[list[dict], str]:
    """把文本拆成「已标记块」与「未标记残留」。

    与 `parse()` 的区别：`parse()` 按标题切全文，认「任意位置的行首标题」；
    这里按**空行分块**，只有块首是 `【类型】` 才算已标记，其余整块算残留正文。
    页面上的「智能分段」必须先知道哪部分还没被标记（否则会把已有的类型标题
    当正文重新归类，越分越乱）。

    返回 (fragments, leftover)。fragments 形如 [{"type", "content"}]。
    """
    fragments: list[dict] = []
    leftovers: list[str] = []
    for block in _BLOCK_SEP_RE.split(text or ""):
        matched = _BLOCK_START_RE.match(block)
        if matched:
            ftype = matched.group(1).strip()
            content = matched.group(2).strip()
            if ftype:
                fragments.append({"type": ftype, "content": content})
            continue
        stripped = block.strip()
        if stripped:
            leftovers.append(stripped)
    return fragments, "\n\n".join(leftovers).strip()


def replace_type(text: str | None, fragment_type: str, content: str | None) -> str | None:
    """只替换指定类型的块正文，其他块**原样保留**（含原有的行内/inline 写法）。

    找不到该类型时返回 None —— 批量替换要据此跳过"本来就没有这一片"的提示词，
    而不是凭空给它加一段。

    刻意不做「解析→重建」：那会把 `【人物面部】黑色长发` 统一改写成
    `【人物面部】\\n黑色长发`，用户库里的格式会被无声重排。
    """
    if not text or not fragment_type:
        return None
    blocks = _BLOCK_SEP_RE.split(text)
    replaced = False
    out: list[str] = []
    for block in blocks:
        matched = _BLOCK_START_RE.match(block)
        if matched and matched.group(1).strip() == fragment_type:
            out.append(f"【{fragment_type}】\n{content or ''}")
            replaced = True
        else:
            out.append(block)
    if not replaced:
        return None
    return "\n\n".join(out).strip()


def replace_types(
    text: str | None,
    replacements: list[dict],
) -> tuple[str | None, list[dict]]:
    """按清单顺序应用多条「类型→内容」，返回最终全文与每条的命中结果。

    每条可选 `missing`：类型不存在时 `append` 在末尾补一段，`skip` 只记录跳过。
    后面的条目看到的是前面已改过的文本；类型或内容为空的条目直接忽略。
    全部条目都跳过时全文返回 None —— 批量替换据此不生成"什么都没改"的任务。
    """
    current = text or ""
    outcomes: list[dict] = []
    changed = False
    for item in replacements or []:
        ftype = (item.get("type") or "").strip()
        content = (item.get("content") or "").strip()
        if not ftype or not content:
            continue
        replaced = replace_type(current, ftype, content)
        if replaced is not None:
            outcomes.append({
                "type": ftype,
                "old_content": extract(current, ftype),
                "action": "replaced",
            })
            current = replaced
            changed = True
        elif item.get("missing") == "append":
            base = current.rstrip()
            current = f"{base}\n\n【{ftype}】\n{content}" if base else f"【{ftype}】\n{content}"
            outcomes.append({"type": ftype, "old_content": "", "action": "appended"})
            changed = True
        else:
            outcomes.append({"type": ftype, "old_content": "", "action": "skipped"})
    return (current.strip() if changed else None), outcomes


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
