"""统计 API —— 数据看板"""
from fastapi import APIRouter
from models import Prompt, GenHistory, GenJob, Tag, Fragment
from peewee import fn

router = APIRouter(tags=["统计"])


@router.get("/stats")
def get_stats():
    """返回项目整体统计数据"""
    prompt_count = Prompt.select().count()
    history_count = GenHistory.select().where(GenHistory.is_deleted == False).count()
    job_count = GenJob.select().count()
    fragment_count = Fragment.select().count()

    # 热门标签（取前10）
    top_tags = (
        Tag.select()
        .order_by(Tag.usage_count.desc())
        .limit(10)
    )
    tags_data = [{"name": t.name, "count": t.usage_count, "color": t.color} for t in top_tags]

    return {
        "prompt_count": prompt_count,
        "history_count": history_count,
        "job_count": job_count,
        "fragment_count": fragment_count,
        "top_tags": tags_data,
    }
