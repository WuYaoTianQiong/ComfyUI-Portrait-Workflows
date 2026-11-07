"""实时碎片池口径：从 prompts 正文解析，不再依赖已退役的 fragments 表。"""
from __future__ import annotations

from app.models import Prompt
from app.services.fragment_syntax import parse


def count_fragments() -> int:
    """去重后的碎片总数（类型 + 内容），与组合器随机池的 dedup 口径一致。"""
    seen: set[tuple[str, str]] = set()
    for (text,) in Prompt.select(Prompt.prompt).tuples():
        for fragment in parse(text or ""):
            ftype = fragment.get("type") or ""
            content = fragment.get("content") or ""
            if ftype:
                seen.add((ftype, content))
    return len(seen)
