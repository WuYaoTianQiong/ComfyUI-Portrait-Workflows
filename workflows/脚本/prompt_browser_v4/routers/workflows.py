"""工作流列表"""
import json
from pathlib import Path
from fastapi import APIRouter, Query

from config import settings

router = APIRouter(tags=["工作流"])

WORKFLOW_BASE = settings.project_root
DEPRECATED_DIR = WORKFLOW_BASE / "废弃工作流"


def _is_valid_workflow(filepath: Path) -> bool:
    try:
        content = json.loads(filepath.read_text(encoding="utf-8"))
        return any(
            isinstance(v, dict) and "class_type" in v
            for v in content.values()
        )
    except Exception:
        return False


def _find_default_workflow() -> str:
    candidates = []
    for d in [WORKFLOW_BASE, DEPRECATED_DIR]:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.json")):
            try:
                if _is_valid_workflow(f):
                    candidates.append(str(f))
            except Exception:
                continue
    for c in candidates:
        if "文生图" in c:
            return c
    return candidates[0] if candidates else ""


@router.get("/workflows")
def list_workflows(sort: str = Query("mtime")):
    """列出所有可用工作流"""
    results: list[dict] = []
    seen: set[str] = set()

    for d in [WORKFLOW_BASE, DEPRECATED_DIR]:
        if not d.exists():
            continue
        for f in d.glob("*.json"):
            if not _is_valid_workflow(f):
                continue
            fp = str(f)
            if fp not in seen:
                seen.add(fp)
                results.append({
                    "path": fp,
                    "name": f.name,
                    "mtime": f.stat().st_mtime,
                })

    if sort == "mtime":
        results.sort(key=lambda x: x["mtime"], reverse=True)
    else:
        results.sort(key=lambda x: x["name"])

    return {"workflows": results, "default": _find_default_workflow()}


@router.get("/config")
def get_config():
    """返回默认工作流和数据库路径等配置"""
    default = _find_default_workflow()
    return {
        "workflow_path": default,
        "workflow_name": Path(default).name if default else "未设置",
        "db_path": str(settings.db_path),
    }
