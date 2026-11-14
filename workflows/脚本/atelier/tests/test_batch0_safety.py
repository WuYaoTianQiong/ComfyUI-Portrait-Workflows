"""批次 0：删除确认、导入标签同步、跨页排序等写路径契约。"""
import json
from datetime import datetime

from app.config import settings


def test_clear_history_requires_confirm(api, seed_history):
    from app.models import Image

    seed_history(filename="a.png")
    seed_history(filename="b.png")

    blocked = api.delete("/api/images")
    assert blocked.status_code == 200
    assert blocked.json()["success"] is False
    assert blocked.json()["total"] == 2
    assert Image.select().where(Image.is_deleted == False).count() == 2

    done = api.delete("/api/images", params={"confirm": "true"})
    assert done.status_code == 200
    assert done.json()["success"] is True
    assert Image.select().where(Image.is_deleted == False).count() == 0


def test_import_prompts_syncs_tags(api):
    from app.models import EntityTag, Prompt, Tag

    resp = api.post(
        "/api/prompts/import",
        json={
            "prompts": [
                {"name": "导入带标签", "prompt": "【人物面部】内容", "tags": "红色,蓝色"}
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["imported"] == 1

    prompt = Prompt.get(Prompt.name == "导入带标签")
    links = EntityTag.select().where(
        (EntityTag.entity_type == "prompt") & (EntityTag.entity_id == prompt.id)
    )
    assert links.count() == 2

    tag = Tag.get(Tag.name == "红色")
    listed = api.get("/api/prompts", params={"tag_ids": str(tag.id)})
    assert listed.status_code == 200
    assert prompt.id in {row["id"] for row in listed.json()["prompts"]}


def _seed_sized_images(seed_history, count=5):
    """造 5 张真实文件 + prompt_params 宽高，用于跨页排序断言。"""
    output = settings.output_dir
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    files = []
    for i in range(count):
        name = f"batch0_sort_{i}.png"
        path = output / name
        path.write_bytes(b"x" * (i + 1) * 10)
        files.append(path)
        rows.append(
            seed_history(
                filename=name,
                prompt_params=json.dumps({"width": (i + 1) * 100, "height": 100}),
                captured_at=datetime(2026, 1, 1 + i, 12, 0, 0),
            )
        )
    return rows, files


def test_size_sort_is_global_across_pages(api, seed_history):
    rows, files = _seed_sized_images(seed_history)
    try:
        first = api.get("/api/images", params={"page": 1, "page_size": 2, "sort": "size_desc"}).json()
        second = api.get("/api/images", params={"page": 2, "page_size": 2, "sort": "size_desc"}).json()
        third = api.get("/api/images", params={"page": 3, "page_size": 2, "sort": "size_desc"}).json()
        ids = [it["id"] for it in first["items"] + second["items"] + third["items"]]
        assert ids == [row.id for row in reversed(rows)]
    finally:
        for path in files:
            path.unlink(missing_ok=True)


def test_resolution_and_oldest_sort_are_global_across_pages(api, seed_history):
    rows, files = _seed_sized_images(seed_history)
    try:
        by_res = api.get("/api/images", params={"page": 1, "page_size": 3, "sort": "res_desc"}).json()
        assert [it["id"] for it in by_res["items"]] == [row.id for row in reversed(rows)][:3]

        oldest = api.get("/api/images", params={"page": 1, "page_size": 2, "sort": "oldest"}).json()
        assert [it["id"] for it in oldest["items"]] == [rows[0].id, rows[1].id]
    finally:
        for path in files:
            path.unlink(missing_ok=True)


def test_refresh_active_jobs_fetches_comfyui_snapshot_once(api, monkeypatch):
    from app.services import job_state

    for pid in ("pid-1", "pid-2"):
        job_state.create_job(
            "batch", "并发任务",
            [{"prompt_id": 0, "comfyui_prompt_id": pid, "status": "running"}],
            "", "portrait", "4K",
        )

    calls = {"queue": 0, "history": 0, "progress": 0}

    def fake_queue():
        calls["queue"] += 1
        return {"queue_running": [[0, "pid-1"], [1, "pid-2"]], "queue_pending": []}

    def fake_history(max_items=100):
        calls["history"] += 1
        return {"pid-1": {"outputs": {}}, "pid-2": {"outputs": {}}}

    def fake_progress():
        calls["progress"] += 1
        return {"progress": 1, "max": 2, "current_node": "3"}

    monkeypatch.setattr(job_state, "get_queue", fake_queue)
    monkeypatch.setattr(job_state, "get_history", fake_history)
    monkeypatch.setattr(job_state, "get_progress", fake_progress)

    assert job_state.refresh_active_jobs() == 2
    assert calls == {"queue": 1, "history": 1, "progress": 1}


def test_refresh_active_jobs_does_not_call_comfyui_when_idle(api, monkeypatch):
    from app.services import job_state

    def boom(*args, **kwargs):
        raise AssertionError("无活跃任务时不应外呼 ComfyUI")

    monkeypatch.setattr(job_state, "get_queue", boom)
    monkeypatch.setattr(job_state, "get_history", boom)
    monkeypatch.setattr(job_state, "get_progress", boom)

    assert job_state.refresh_active_jobs() == 0


def test_refresh_active_jobs_round_robins_oldest(api, monkeypatch):
    """超过 limit 的活跃任务必须轮转：先推进最久没刷新的，而不是永远只刷最新 20 个。"""
    from app.services import job_state

    ids = [
        job_state.create_job(
            "single", f"任务{i}",
            [{"prompt_id": 0, "status": "queued"}],
            "", "portrait", "4K",
        )
        for i in range(25)
    ]

    seen: list[int] = []
    monkeypatch.setattr(job_state, "fetch_comfy_snapshot", lambda: None)
    monkeypatch.setattr(job_state, "refresh_job", lambda job_id, snapshot=None: seen.append(job_id))

    assert job_state.refresh_active_jobs() == 20
    assert seen == ids[:20]
    assert ids[-1] not in seen


def test_batch_replace_detaches_from_source_prompt(api, seed_prompt, monkeypatch):
    """替换碎片出的图应挂到临时提示词，而不是原提示词名下。"""
    from app.config import settings
    from app.models import GenJob, Image, Prompt
    from app.routers import comfyui as comfy_router
    from app.routers.comfyui import BatchItem, BatchRequest
    from app.services.job_state import _insert_history_for_item

    source = seed_prompt(name="原提示词", prompt="【人物面部】old")

    workflow = {"1": {"class_type": "SaveImage", "inputs": {"filename_prefix": "orig"}}}
    result = comfy_router.batch_generate(
        BatchRequest(
            items=[BatchItem(prompt_id=source.id, seed=7, prompt_override="【人物面部】new")],
            workflow_path="x.json",
            workflow_content=json.dumps(workflow),
            output_subfolder="",
        )
    )
    assert result["success"] is True
    job = GenJob.get_by_id(result["job_id"])
    item = json.loads(job.items)[0]
    assert item["prompt_id"] is None
    assert item["source_prompt_id"] == source.id
    pp = json.loads(item["prompt_params"])
    assert pp["source"] == "batch_replace"
    assert pp["prompt"] == "【人物面部】new"
    assert pp["injected_prompt"] == "new"
    assert pp["source_prompt_id"] == source.id
    assert Prompt.get_or_none(Prompt.id == source.id) is not None

    image_path = settings.output_dir / "replaced_result.png"
    image_path.write_bytes(b"x")
    try:
        _insert_history_for_item(
            job.id, None, "pid-replace",
            [{"filename": image_path.name, "subfolder": "", "type": "output"}],
            "替换结果", item["prompt_params"],
        )
        row = Image.get_or_none(Image.filename == image_path.name)
        assert row is not None
        assert row.prompt_id is None
        assert json.loads(row.prompt_params)["source"] == "batch_replace"
    finally:
        image_path.unlink(missing_ok=True)
