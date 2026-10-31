"""gen_history upsert 语义测试。

这一组锁死的是历史上两次静默失败的地方：部分唯一索引 + ON CONFLICT 的方言细节
一旦写错，异常会被外层 `except Exception: pass` 吞掉，表现为"同步永远写不进库、
画廊永远没有新图"，而界面上没有任何报错。
"""

from services.history_store import upsert_history


def _count(filename="dup.png"):
    from models import GenHistory

    return GenHistory.select().where(GenHistory.filename == filename).count()


def test_insert_then_upsert_updates_same_row(api):
    """同名文件重复 upsert 只保留一行，字段被更新而不是新增。"""
    from models import GenHistory

    values = {
        "filename": "dup.png", "subfolder": "", "img_type": "output",
        "job_id": None, "prompt_id": 1, "comfyui_prompt_id": "p1",
        "view_url": "/a", "preview": "", "prompt_params": None,
        "captured_at": None, "source": "comfyui_sync",
    }
    upsert_history(values, {GenHistory.view_url: "/a"})
    assert _count() == 1

    values["comfyui_prompt_id"] = "p2"
    upsert_history(values, {GenHistory.comfyui_prompt_id: "p2"})
    assert _count() == 1
    assert GenHistory.get(GenHistory.filename == "dup.png").comfyui_prompt_id == "p2"


def test_soft_deleted_row_does_not_block_new_insert(api):
    """部分唯一索引只覆盖 is_deleted=0：软删过的同名文件应插入新行，而不是复活墓碑。"""
    from models import GenHistory

    values = {
        "filename": "dup.png", "subfolder": "", "img_type": "output",
        "job_id": None, "prompt_id": 1, "comfyui_prompt_id": "p1",
        "view_url": "/a", "preview": "", "prompt_params": None,
        "captured_at": None, "source": "comfyui_sync",
    }
    upsert_history(values, {GenHistory.view_url: "/a"})
    GenHistory.update(is_deleted=True).where(GenHistory.filename == "dup.png").execute()

    upsert_history(values, {GenHistory.view_url: "/a"})
    assert _count() == 2
    live = GenHistory.select().where(
        (GenHistory.filename == "dup.png") & (GenHistory.is_deleted == False)
    ).count()
    assert live == 1


def test_only_when_job_null_does_not_touch_job_rows(api):
    """已被任务写入的行（job_id 非空）不能被较弱的同步数据覆盖。"""
    from models import GenHistory

    values = {
        "filename": "dup.png", "subfolder": "", "img_type": "output",
        "job_id": 7, "prompt_id": 1, "comfyui_prompt_id": "rich",
        "view_url": "/rich", "preview": "", "prompt_params": None,
        "captured_at": None, "source": "composer",
    }
    upsert_history(values, {GenHistory.view_url: "/rich"})

    upsert_history(
        {**values, "job_id": None, "comfyui_prompt_id": "weak", "source": "comfyui_sync"},
        {GenHistory.comfyui_prompt_id: "weak", GenHistory.source: "comfyui_sync"},
        only_when_job_null=True,
    )

    row = GenHistory.get(GenHistory.filename == "dup.png")
    assert row.comfyui_prompt_id == "rich"
    assert row.source == "composer"
