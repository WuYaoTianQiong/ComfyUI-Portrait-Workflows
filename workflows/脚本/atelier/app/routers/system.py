"""系统资源 —— 运行状态 / 配置 / 统计。

这三条都不是某类实体的 CRUD，而是"这台机器、这个库现在什么样"，
按命名规范 §6.2 收到 `/api/system/*` 下。
其中 `/api/system/stats` 原在 `routers/stats.py`（P3 已并入本文件）。
"""
from pathlib import Path

from fastapi import APIRouter

from app.config import settings
from app.models import Fragment, GenJob, Image, Prompt, Tag
from app.schemas import StatsResponse
from app.services.comfyui_client import get_queue as fetch_queue, is_online
from app.services.workflow_catalog import find_default_workflow

router = APIRouter(tags=["系统"])


@router.get("/system/status")
def get_system_status():
    # 不能靠 get_queue() 判断在线：它在任何异常下都返回 {}，于是状态永远是 online，
    # 前端就会允许在 ComfyUI 离线时提交任务（历史 109 个任务里 27 个因此失败）。
    if not is_online():
        return {"comfyui": "offline", "queue_running": 0, "queue_pending": 0}
    queue = fetch_queue()
    return {
        "comfyui": "online",
        "queue_running": len(queue.get("queue_running", [])),
        "queue_pending": len(queue.get("queue_pending", [])),
    }


@router.get("/system/config")
def get_system_config():
    """返回默认工作流和数据库路径等配置"""
    default = find_default_workflow()
    return {
        "workflow_path": default,
        "workflow_name": Path(default).name if default else "未设置",
        "db_path": str(settings.db_path),
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
