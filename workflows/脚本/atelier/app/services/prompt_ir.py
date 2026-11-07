"""提示词 IR 影子解析：只读对照，不参与提交。

目标是把「文本 → 结构」这件事先定义清楚：一个 PromptDoc 由片段、负向词和
未标记正文组成。当前只用于审计与测试；等差异收敛后再切换写入链路。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.fragment_syntax import parse as parse_fragments

NEGATIVE_TYPES = {"避免", "负面", "负面提示", "negative"}
_NEG_SPLIT_RE = re.compile(r"[、,，;；\n]")
_INLINE_HEADER_RE = re.compile(r"【[^】]+】")


@dataclass(frozen=True)
class PromptSegment:
    kind: str  # fragment | negative
    type: str
    text: str


@dataclass
class PromptDoc:
    segments: list[PromptSegment] = field(default_factory=list)
    negative_terms: list[str] = field(default_factory=list)
    prose: str = ""
    raw: str = ""

    @property
    def fragment_types(self) -> list[str]:
        return [segment.type for segment in self.segments if segment.kind == "fragment"]


def _split_terms(text: str) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for part in _NEG_SPLIT_RE.split(text or ""):
        term = part.strip()
        if term and term not in seen:
            seen.add(term)
            terms.append(term)
    return terms


def _prose_prefix(text: str) -> str:
    """第一个【标题】之前的正文；没有标题时整段都是正文。"""
    from app.services.fragment_syntax import _HEADER_RE  # 单一标题正则来源

    match = _HEADER_RE.search(text)
    if match is None:
        return text.strip()
    return text[: match.start()].strip()


def _clean(text: str) -> str:
    return "\n".join(line.rstrip() for line in (text or "").replace("\r\n", "\n").split("\n")).strip()


def parse_prompt(text: str | None) -> PromptDoc:
    raw = text or ""
    doc = PromptDoc(raw=raw, prose=_prose_prefix(raw))
    for fragment in parse_fragments(raw):
        ftype = (fragment.get("type") or "").strip()
        content = (fragment.get("content") or "").strip()
        if ftype in NEGATIVE_TYPES:
            doc.segments.append(PromptSegment("negative", ftype, content))
            for term in _split_terms(content):
                if term not in doc.negative_terms:
                    doc.negative_terms.append(term)
        else:
            doc.segments.append(PromptSegment("fragment", ftype, content))
    return doc


def render_prompt(doc: PromptDoc) -> str:
    parts: list[str] = []
    if doc.prose:
        parts.append(doc.prose)
    for segment in doc.segments:
        if not segment.text:
            continue
        parts.append(f"【{segment.type}】\n{segment.text}")
    return "\n\n".join(parts).strip()


def shadow_report(text: str | None) -> dict:
    """对照“原文 / IR 渲染”的差异；空 issues 表示可无损往返。"""
    raw = text or ""
    doc = parse_prompt(raw)
    rendered = render_prompt(doc)
    issues: list[str] = []
    if doc.prose:
        issues.append("第一个标题之前有未标记正文")
    for segment in doc.segments:
        if _INLINE_HEADER_RE.search(segment.text):
            issues.append(f"「{segment.type}」正文里还有行内【标题】")
    whitespace_only = False
    if _clean(rendered) != _clean(raw):
        if re.sub(r"\s+", "", rendered) == re.sub(r"\s+", "", raw):
            whitespace_only = True
            issues.append("仅空白/分隔符差异（可安全归一）")
        else:
            issues.append("IR 渲染与原文不一致")
    return {
        "issues": issues,
        "whitespace_only": whitespace_only,
        "negative_terms": doc.negative_terms,
        "fragment_types": doc.fragment_types,
        "original": raw,
        "rendered": rendered,
    }
