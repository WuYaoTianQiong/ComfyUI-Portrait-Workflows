"""系统资源 —— 运行状态 / 配置 / 统计。

这三条都不是某类实体的 CRUD，而是"这台机器、这个库现在什么样"，
按命名规范 §6.2 收到 `/api/system/*` 下。
其中 `/api/system/stats` 原在 `routers/stats.py`（P3 已并入本文件）。
"""
from pathlib import Path
import os
import sys

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.config import settings
from app.models import Fragment, GenJob, Image, Prompt, Tag
from app.schemas import StatsResponse
from app.services.comfyui_client import get_queue as fetch_queue, is_online
from app.services.output_location import OutputLocationError, sanitize_subfolder
from app.services.paths import _resolve_if_reparse
from app.services.workflow_catalog import find_default_workflow

router = APIRouter(tags=["系统"])


def _output_subdir(rel: str) -> Path:
    try:
        clean = sanitize_subfolder(rel)
    except OutputLocationError as e:
        raise HTTPException(400, str(e))
    base = settings.output_dir
    for part in (clean.split("/") if clean else []):
        base = base / part
    return _resolve_if_reparse(base)


class CreateOutputFolderRequest(BaseModel):
    parent: str = ""
    name: str


class OpenFolderRequest(BaseModel):
    path: str


@router.post("/system/open-folder")
def open_folder(req: OpenFolderRequest):
    """在资源管理器中打开一个已存在的目录（磁盘选图页用）。"""
    p = Path(req.path)
    try:
        if not p.is_absolute() or not p.is_dir():
            raise HTTPException(400, "不是有效目录")
    except OSError:
        raise HTTPException(400, "不是有效目录")
    if sys.platform != "win32":
        return {"success": False, "path": str(p), "message": "仅支持 Windows"}
    os.startfile(str(p))
    return {"success": True, "path": str(p)}


@router.get("/system/output-folders")
def list_output_folders(path: str = Query("")):
    """列出 output 下某一层的子目录（出图位置选择器用，只能看到 output 内）。"""
    try:
        clean = sanitize_subfolder(path)
    except OutputLocationError as e:
        raise HTTPException(400, str(e))
    base = _output_subdir(clean)
    if not base.is_dir():
        raise HTTPException(404, f"目录不存在: {clean or 'output'}")

    dirs = []
    try:
        with os.scandir(base) as it:
            for entry in sorted(it, key=lambda e: e.name):
                try:
                    if entry.is_dir(follow_symlinks=False) and not entry.name.startswith("."):
                        child = f"{clean}/{entry.name}".strip("/")
                        dirs.append({"name": entry.name, "path": child})
                except OSError:
                    continue
    except OSError as e:
        raise HTTPException(400, f"读取目录失败: {e}")

    parent = "/".join(clean.split("/")[:-1]) if clean else ""
    return {
        "root": str(settings.output_dir),
        "path": clean,
        "parent": parent,
        "dirs": dirs,
    }


@router.post("/system/output-folders")
def create_output_folder(req: CreateOutputFolderRequest):
    """在 output 下新建一级目录；已存在时直接返回。"""
    name = (req.name or "").strip()
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise HTTPException(400, "目录名不合法")
    try:
        rel = sanitize_subfolder(f"{req.parent}/{name}" if req.parent else name)
    except OutputLocationError as e:
        raise HTTPException(400, str(e))
    target = settings.output_dir / Path(*rel.split("/"))
    if target.is_dir():
        return {"success": True, "path": rel, "created": False}
    try:
        target.mkdir(parents=True, exist_ok=False)
    except OSError as e:
        raise HTTPException(400, f"创建目录失败: {e}")
    return {"success": True, "path": rel, "created": True}


@router.post("/system/open-output")
def open_output_dir():
    """在资源管理器中打开当前出图根目录（仅本机 Windows 有意义）。"""
    path = _resolve_if_reparse(settings.output_dir)
    if not path.is_dir():
        raise HTTPException(404, f"出图目录不存在: {path}")
    if sys.platform != "win32":
        return {"success": False, "path": str(path), "message": "仅支持 Windows"}
    os.startfile(str(path))
    return {"success": True, "path": str(path)}


@router.get("/system/status")
def get_system_status():
    # 参考库回滚开关与 Web 入口必须每个分支都返回：离线时前端也要能收起导航项。
    reference_enabled = settings.reference_enabled
    reference_web_url = settings.reference_web_url
    # 不能靠 get_queue() 判断在线：它在任何异常下都返回 {}，于是状态永远是 online，
    # 前端就会允许在 ComfyUI 离线时提交任务（历史 109 个任务里 27 个因此失败）。
    if not is_online():
        return {
            "comfyui": "offline",
            "queue_running": 0,
            "queue_pending": 0,
            "reference_enabled": reference_enabled,
            "reference_web_url": reference_web_url,
        }
    queue = fetch_queue()
    return {
        "comfyui": "online",
        "queue_running": len(queue.get("queue_running", [])),
        "queue_pending": len(queue.get("queue_pending", [])),
        "reference_enabled": reference_enabled,
        "reference_web_url": reference_web_url,
    }


@router.get("/system/config")
def get_system_config():
    """返回默认工作流和数据库路径等配置"""
    default = find_default_workflow()
    return {
        "workflow_path": default,
        "workflow_name": Path(default).name if default else "未设置",
        "db_path": str(settings.db_path),
        "output_dir": str(settings.output_dir),
    }


@router.get("/system/stats", response_model=StatsResponse)
def get_system_stats():
    """返回项目整体统计数据"""
    prompt_count = Prompt.select().count()
    image_count = Image.select().where(Image.is_deleted == False).count()  # noqa: E712
    job_count = GenJob.select().count()
    fragment_count = Fragment.select().count()

    # 热门标签（取前10）
    top_tags = Tag.select().order_by(Tag.usage_count.desc()).limit(10)
    tags_data = [{"name": t.name, "count": t.usage_count, "color": t.color} for t in top_tags]

    return {
        "prompt_count": prompt_count,
        "history_count": image_count,
        "job_count": job_count,
        "fragment_count": fragment_count,
        "top_tags": tags_data,
    }
