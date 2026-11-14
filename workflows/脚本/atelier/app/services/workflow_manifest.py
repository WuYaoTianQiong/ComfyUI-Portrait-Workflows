"""工作流清单：稳定的 workflow_id + 内容哈希。

文件名只是显示标签，不能当身份：改名/换目录会让历史任务失联。清单给每个
工作流一个稳定 id（由相对路径派生，内容变化不变），sha256 则标识具体版本。
自定义工作流没有稳定路径，用内容哈希当 id。

清单是运行数据（可由 tools/gen_workflow_manifest.py 重建），落在 `data_dir`
（默认 `脚本/atelier/data/`），不放在库根：库根就是 ComfyUI 的
`user/default/workflows`，放里面的 .json 会被它的工作流列表列出来、点开报错。
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

logger = logging.getLogger("atelier.workflow_manifest")

MANIFEST_FILENAME = "工作流清单.json"
_MANIFEST_CACHE: dict[str, tuple[float, dict]] = {}


def manifest_path(base_dir: Path | None = None) -> Path:
    """清单落点：`data_dir`（运行数据根），测试/工具可传 base_dir 显式覆盖。"""
    return (base_dir or settings.data_dir) / MANIFEST_FILENAME


def load_manifest(base_dir: Path | None = None) -> dict:
    path = manifest_path(base_dir)
    if not path.is_file():
        return {"schema": 1, "workflows": []}
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {"schema": 1, "workflows": []}
    cached = _MANIFEST_CACHE.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.exception("工作流清单读取失败: %s", path)
        return {"schema": 1, "workflows": []}
    if not isinstance(data, dict):
        return {"schema": 1, "workflows": []}
    data.setdefault("workflows", [])
    _MANIFEST_CACHE[str(path)] = (mtime, data)
    return data


def content_sha256(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_id_for_path(relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/").strip().casefold()
    return "wf-" + hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.name


def _entry_by_rel(manifest: dict, relative_path: str) -> dict | None:
    wanted = relative_path.replace("\\", "/").casefold()
    for entry in manifest.get("workflows") or []:
        if not isinstance(entry, dict):
            continue
        candidate = str(entry.get("file") or "").replace("\\", "/").casefold()
        if candidate == wanted:
            return entry
    return None


@dataclass(frozen=True)
class WorkflowIdentity:
    id: str
    sha256: str
    rel_path: str | None
    source: str


def identify(workflow_path: str, workflow_content: str | None = None) -> WorkflowIdentity | None:
    """返回提交内容对应的稳定身份；路径不存在且无内容时返回 None。

    有 `workflow_content` 时以实际提交内容为准（自定义工作流或前端上传）。
    磁盘文件优先在清单里找 id；未登记时用相对路径派生，仍然稳定。
    """
    if workflow_content:
        raw = workflow_content.encode("utf-8")
        sha = hashlib.sha256(raw).hexdigest()
        return WorkflowIdentity(
            id=f"custom-{sha[:12]}", sha256=sha, rel_path=None, source="custom",
        )
    if not workflow_path:
        return None
    path = Path(workflow_path)
    if not path.is_file():
        return None
    try:
        sha = content_sha256(path)
    except OSError:
        return None
    rel = _relative(path, settings.library_root)
    entry = _entry_by_rel(load_manifest(), rel)
    if entry and entry.get("id"):
        return WorkflowIdentity(
            id=str(entry["id"]), sha256=sha, rel_path=rel, source="manifest",
        )
    return WorkflowIdentity(
        id=stable_id_for_path(rel), sha256=sha, rel_path=rel, source="file",
    )
