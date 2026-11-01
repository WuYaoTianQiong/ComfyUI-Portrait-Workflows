"""出图归档位置：子目录清洗、变量展开、保存节点前缀拼接。

设计边界：
- 只允许 ComfyUI output 根**之下**的相对子目录；拒绝绝对路径、盘符与 `..`。
- 默认空字符串 = 保持旧的平铺行为，避免历史文件名/测试基线漂移。
- 变量在服务端展开，前端只传模板，不传最终路径。
"""
from __future__ import annotations

import re
from datetime import datetime

from app.services.workflow_parser import prepend_output_subfolder

MAX_DEPTH = 3
MAX_SEGMENT = 60
MAX_TOTAL = 180

_VAR_RE = re.compile(r"\{([a-zA-Z_]+)\}")
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class OutputLocationError(ValueError):
    """用户提供的出图子目录不合法。"""


def sanitize_subfolder(raw: str) -> str:
    """校验并规范化用户输入的子目录；空字符串表示 output 根。"""
    text = (raw or "").replace("\\", "/").strip()
    if not text:
        return ""
    if text.startswith("/") or text.startswith("//") or _DRIVE_RE.match(text):
        raise OutputLocationError("出图目录必须是 output 下的相对路径")

    parts: list[str] = []
    for part in text.split("/"):
        part = part.strip()
        if not part or part == ".":
            continue
        if part == "..":
            raise OutputLocationError("出图目录不能包含 ..")
        if _INVALID_CHARS.search(part) or ":" in part or any(ord(ch) < 32 for ch in part):
            raise OutputLocationError("出图目录包含非法字符")
        if len(part) > MAX_SEGMENT:
            raise OutputLocationError(f"出图目录每一级不能超过 {MAX_SEGMENT} 个字符")
        parts.append(part)

    if len(parts) > MAX_DEPTH:
        raise OutputLocationError(f"出图目录最多 {MAX_DEPTH} 级")
    result = "/".join(parts)
    if len(result) > MAX_TOTAL:
        raise OutputLocationError(f"出图目录总长度不能超过 {MAX_TOTAL} 个字符")
    return result


def _workflow_stem(workflow_path: str) -> str:
    raw = (workflow_path or "").replace("\\", "/").strip()
    if raw.startswith("custom://"):
        raw = raw[len("custom://"):]
    name = raw.rsplit("/", 1)[-1]
    if name.lower().endswith(".json"):
        name = name[:-5]
    return _INVALID_CHARS.sub("_", name).strip(". ") or "workflow"


def expand_subfolder(
    template: str,
    *,
    workflow_path: str = "",
    job_id: int | None = None,
    quality: str = "",
    orientation: str = "",
    now: datetime | None = None,
) -> str:
    """展开 {date}/{month}/{year}/{workflow}/{job_id}/{quality}/{orientation}。

    未知变量直接报错，避免用户打错字后得到一个带花括号的怪目录。
    """
    current = now or datetime.now()
    context = {
        "date": current.strftime("%Y-%m-%d"),
        "month": current.strftime("%Y-%m"),
        "year": current.strftime("%Y"),
        "workflow": _workflow_stem(workflow_path),
        "job_id": "" if job_id is None else str(job_id),
        "quality": quality or "",
        "orientation": orientation or "",
    }

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in context:
            raise OutputLocationError(f"未知变量: {{{key}}}")
        return context[key]

    expanded = _VAR_RE.sub(repl, template or "")
    if "{" in expanded or "}" in expanded:
        raise OutputLocationError("出图目录包含未闭合的变量")
    return sanitize_subfolder(expanded)


def with_subfolder(subfolder: str, prefix: str) -> str:
    """把相对子目录拼到文件名前缀前面；空子目录时原样返回。"""
    clean = (subfolder or "").strip().strip("/")
    return f"{clean}/{prefix}" if clean else prefix


def apply_output_subfolder(api_workflow: dict, subfolder: str) -> int:
    """给工作流的所有保存节点加相对子目录；空子目录不改变行为。"""
    return prepend_output_subfolder(api_workflow, subfolder)
