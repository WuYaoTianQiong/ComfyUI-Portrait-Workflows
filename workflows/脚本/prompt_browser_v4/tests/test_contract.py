"""后端契约测试 —— 重构期的回归基线。

原则：锁"行为"不锁"实现"。每条用例对应一个用户可见的承诺（端点存在、键名、筛选语义、
软删除、入库去重）。重构时这些用例变红，就说明行为被破坏了。
"""

import json

import pytest


# ---------------------------------------------------------------------------
# 基础与提示词
# ---------------------------------------------------------------------------

def test_status_ok(api):
    r = api.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert "comfyui" in body


def test_status_reports_offline_when_comfyui_unreachable(api):
    """状态必须是真实探活：曾因 get_queue() 吞异常返回 {}，状态永远是 online，
    导致 ComfyUI 离线时仍允许提交任务（历史 109 个任务里 27 个因此失败）。"""
    body = api.get("/api/status").json()
    assert body["comfyui"] == "offline"


def test_prompts_list_envelope(api, seed_prompt):
    seed_prompt(name="A")
    seed_prompt(name="B")

    r = api.get("/api/prompts")
    assert r.status_code == 200
    body = r.json()
    assert {"prompts", "total", "page", "page_size"} <= set(body)
    assert body["total"] == 2
    assert len(body["prompts"]) == 2


def test_prompt_crud_roundtrip(api):
    r = api.post("/api/prompts", json={"name": "新条目", "prompt": "【人物面部】x"})
    assert r.status_code == 201
    pid = r.json()["id"]

    r = api.get(f"/api/prompts/{pid}")
    assert r.status_code == 200
    assert r.json()["name"] == "新条目"

    r = api.put(f"/api/prompts/{pid}", json={"name": "改过名"})
    assert r.status_code == 200
    assert api.get(f"/api/prompts/{pid}").json()["name"] == "改过名"

    assert api.delete(f"/api/prompts/{pid}").status_code == 200
    assert api.get(f"/api/prompts/{pid}").status_code == 404


def test_prompt_html_fragment(api, seed_prompt):
    seed_prompt(name="片段可见")
    r = api.get("/api/prompts/html?page=1&page_size=50&search=&sort=default")
    assert r.status_code == 200
    assert "promptListContainer" in r.text
    assert "片段可见" in r.text


def test_prompts_export_route(api, seed_prompt):
    seed_prompt(name="导出用")
    r = api.get("/api/prompts/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert "prompts" in r.text


# ---------------------------------------------------------------------------
# 历史画廊
# ---------------------------------------------------------------------------

def test_history_list_envelope(api, seed_history):
    seed_history(filename="a.png")
    seed_history(filename="b.png")

    r = api.get("/api/history?page=1&page_size=50")
    assert r.status_code == 200
    body = r.json()
    assert {"items", "total", "page", "page_size"} <= set(body)
    assert body["total"] == 2


def test_history_soft_delete_hides_item(api, seed_history):
    item = seed_history(filename="gone.png")
    r = api.delete(f"/api/history/{item.id}")
    assert r.status_code == 200

    body = api.get("/api/history?page=1&page_size=50").json()
    assert body["total"] == 0
    # 物理文件与行都保留，只置软删除标记
    from models import GenHistory

    assert GenHistory.get_by_id(item.id).is_deleted is True


def test_history_html_fragment(api, seed_history):
    seed_history(filename="h.png")
    r = api.get(
        "/api/history/html?page=1&page_size=50&sort=newest"
        "&favorite=&search=&category_id=&tag_ids=&source=&date=&model="
    )
    assert r.status_code == 200
    assert "gallery-grid" in r.text


def test_history_ids_route(api, seed_history):
    seed_history(filename="i1.png")
    seed_history(filename="i2.png")

    r = api.get("/api/history/ids")
    assert r.status_code == 200
    assert len(r.json()["ids"]) == 2


def test_history_ids_respects_category(api, seed_history, seed_taxonomy):
    from models import ImageCategory, ImageTag

    keep = seed_history(filename="keep.png")
    drop = seed_history(filename="drop.png")
    cat, tag = seed_taxonomy()
    ImageCategory.create(image=keep.id, category=cat.id)
    ImageTag.create(image=keep.id, tag=tag.id)

    body = api.get(f"/api/history/ids?category_id={cat.id}").json()
    assert body["ids"] == [keep.id]

    body = api.get(f"/api/history/ids?tag_ids={tag.id}").json()
    assert body["ids"] == [keep.id]


def test_history_add_category_endpoint(api, seed_history, seed_taxonomy):
    item = seed_history(filename="cat.png")
    cat, _ = seed_taxonomy()

    r = api.post(f"/api/history/{item.id}/categories/{cat.id}")
    assert r.status_code == 200
    assert r.json()["created"] is True


def test_history_add_tag_endpoint(api, seed_history, seed_taxonomy):
    item = seed_history(filename="tag.png")
    _, tag = seed_taxonomy()

    r = api.post(f"/api/history/{item.id}/tags/{tag.id}")
    assert r.status_code == 200
    assert r.json()["created"] is True


# ---------------------------------------------------------------------------
# 分类 / 标签 / 任务
# ---------------------------------------------------------------------------

def test_tags_popular_endpoint(api, seed_taxonomy):
    seed_taxonomy()
    r = api.get("/api/tags/popular")
    assert r.status_code == 200
    assert "tags" in r.json()


def test_categories_tree_envelope(api, seed_taxonomy):
    seed_taxonomy()
    r = api.get("/api/categories?tree=true")
    assert r.status_code == 200
    assert "categories" in r.json()


def test_job_detail_404(api):
    assert api.get("/api/jobs/999999").status_code == 404


def test_job_snapshot_survives_offline_comfyui(api):
    """ComfyUI 不可达时，任务详情必须返回 200 而不是 500。"""
    from models import GenJob

    job = GenJob.create(
        job_type="single", status="pending", title="离线", total=0,
        done_count=0, error_count=0, items="[]",
    )
    r = api.get(f"/api/jobs/{job.id}")
    assert r.status_code == 200
    assert r.json()["id"] == job.id


# ---------------------------------------------------------------------------
# B2：任务状态只读化 / 取消归属 / unknown 不落库
# ---------------------------------------------------------------------------

def test_job_get_is_read_only(api):
    """GET /api/jobs/{id} 不允许再写库（旧实现每次轮询都反推并落库）。"""
    from models import GenJob

    job = GenJob.create(
        job_type="single", status="pending", title="只读", total=1,
        items=json.dumps([{"prompt_id": 1, "status": "pending"}], ensure_ascii=False),
    )
    before = GenJob.get_by_id(job.id)

    r = api.get(f"/api/jobs/{job.id}")
    assert r.status_code == 200
    assert r.json()["items"][0]["status"] == "pending"

    after = GenJob.get_by_id(job.id)
    assert after.status == before.status == "pending"
    assert after.updated_at == before.updated_at, "GET 不应修改任务行"


def test_job_cancel_marks_stopped_and_items_cancelled(api):
    from models import GenJob

    items = [
        {"prompt_id": 1, "status": "done", "comfyui_prompt_id": "p1"},
        {"prompt_id": 2, "status": "running", "comfyui_prompt_id": "p2"},
    ]
    job = GenJob.create(
        job_type="batch", status="running", title="取消", total=2,
        done_count=1, items=json.dumps(items, ensure_ascii=False),
    )

    r = api.post(f"/api/jobs/{job.id}/cancel")
    assert r.status_code == 200

    row = GenJob.get_by_id(job.id)
    assert row.status == "stopped"
    saved = json.loads(row.items)
    assert saved[0]["status"] == "done"          # 已完成的不动
    assert saved[1]["status"] == "cancelled"     # 未完成的标取消


def test_refresh_never_persists_unknown(api):
    """pid 在队列和历史里都查不到时，保留原状态而不是写 unknown。
    unknown 一旦落库就再没有代码会重新选中它（旧库里因此卡了 56 个 item）。"""
    from models import GenJob
    from services import job_state

    job = GenJob.create(
        job_type="single", status="pending", title="待判定", total=1,
        items=json.dumps([{"prompt_id": 1, "status": "pending",
                           "comfyui_prompt_id": "not-in-comfyui"}], ensure_ascii=False),
    )

    snapshot = job_state.refresh_job(job.id)
    assert snapshot is not None
    assert snapshot["status"] in ("pending", "running")

    row = GenJob.get_by_id(job.id)
    assert row.status != "unknown"
    assert json.loads(row.items)[0]["status"] in ("pending", "running")


def test_refresh_keeps_no_pid_items_pending_during_submission(api):
    """提交窗口内（create_job 后、update_job_items 前）条目还没有 prompt_id，
    写者不能把它判成失败——批量 160 张的提交循环可能持续几分钟。"""
    from models import GenJob
    from services import job_state

    job = GenJob.create(
        job_type="batch", status="pending", title="提交中", total=1,
        items=json.dumps([{"prompt_id": 1}], ensure_ascii=False),
    )

    snapshot = job_state.refresh_job(job.id)
    assert snapshot is not None
    assert snapshot["status"] == "pending"
    assert snapshot["items"][0]["status"] == "pending"


def test_jobs_list_items_are_arrays(api):
    from models import GenJob

    GenJob.create(
        job_type="batch", status="running", title="列表", total=1,
        items=json.dumps([{"prompt_id": 1, "status": "pending"}], ensure_ascii=False),
    )
    body = api.get("/api/jobs").json()
    assert isinstance(body["jobs"][0]["items"], list)

    active = api.get("/api/jobs?active=1").json()
    assert len(active["jobs"]) == 1


# ---------------------------------------------------------------------------
# B3：captured_at（真实出图时间）与模板导入
# ---------------------------------------------------------------------------

def test_gallery_sorts_by_captured_at_not_import_time(api, seed_history):
    from datetime import datetime

    old_photo = seed_history(filename="old.png", captured_at=datetime(2020, 1, 1, 12, 0, 0))
    new_photo = seed_history(filename="new.png", captured_at=datetime(2024, 6, 1, 12, 0, 0))

    body = api.get("/api/history?page=1&page_size=50").json()
    assert [item["filename"] for item in body["items"]][:2] == ["new.png", "old.png"]
    assert body["items"][0]["captured_at"].startswith("2024-06-01")


def test_history_date_facet_uses_captured_at(api, seed_history):
    from datetime import datetime

    seed_history(filename="a.png", captured_at=datetime(2020, 1, 1))
    seed_history(filename="b.png", captured_at=datetime(2024, 6, 1))

    facets = api.get("/api/history/facets").json()
    assert facets["date"].get("2024-06") == 1
    assert facets["date"].get("2020-01") == 1

    filtered = api.get("/api/history?page=1&page_size=50&date=2024-06").json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["filename"] == "b.png"


def test_history_date_falls_back_to_created_at(api, seed_history):
    """老数据没有 captured_at 时，日期筛选仍要能命中（COALESCE 回退）。"""
    from datetime import datetime

    from models import GenHistory

    item = seed_history(filename="legacy.png")
    GenHistory.update(captured_at=None, created_at=datetime(2022, 3, 15, 8, 0, 0)) \
        .where(GenHistory.id == item.id).execute()

    filtered = api.get("/api/history?page=1&page_size=50&date=2022-03").json()
    assert filtered["total"] == 1


def test_template_batch_import_keeps_all_fragments(api, seed_prompt):
    """旧实现把 TemplateFragment.create 放在 for 循环外，导入的模板只剩 1 个碎片。"""
    p = seed_prompt(name="来源", prompt="【人物面部】face\n\n【场景环境】street")

    r = api.post("/api/templates/batch_import", json={
        "items": [{
            "name": "导入的模板",
            "fragments": [
                {"prompt_id": p.id, "fragment_type": "人物面部"},
                {"prompt_id": p.id, "fragment_type": "场景环境"},
            ],
        }]
    })
    assert r.status_code == 200
    assert r.json()["imported"] == 1

    templates = api.get("/api/templates").json()["templates"]
    assert len(templates) == 1
    tid = templates[0]["id"]
    detail = api.get(f"/api/templates/{tid}").json()["template"]
    assert detail["fragment_count"] == 2
    assert detail["fragments"][0]["content"] == "face"


# ---------------------------------------------------------------------------
# B4 前置：删除提示词不删图；画廊读取不再写库
# ---------------------------------------------------------------------------

def test_delete_prompt_keeps_history_but_detaches(api, seed_prompt):
    """删提示词只解除关联，不再删掉它的出图记录（文件还在磁盘，删了会反复重建）。"""
    from models import GenHistory

    p = seed_prompt(name="要删的")
    photo = GenHistory.create(
        filename="keep_me.png", subfolder="", img_type="output",
        prompt_id=p.id, source="local",
    )

    r = api.delete(f"/api/prompts/{p.id}")
    assert r.status_code == 200
    assert r.json()["gen_history_detached"] == 1

    assert api.get(f"/api/prompts/{p.id}").status_code == 404
    kept = GenHistory.get_or_none(GenHistory.id == photo.id)
    assert kept is not None, "出图记录不应被删除"
    assert kept.prompt_id is None, "应只解除与提示词的关联"


def test_gallery_read_does_not_backfill_into_db(api):
    """列表读取时从任务 items 取回缺失参数只用于展示，不得写库。"""
    from models import GenHistory, GenJob

    params = json.dumps({"prompt": "【人物面部】x", "seed": 7}, ensure_ascii=False)
    job = GenJob.create(
        job_type="single", status="done", title="历史", total=1,
        items=json.dumps([{
            "prompt_id": 0, "comfyui_prompt_id": "pid-1",
            "prompt_params": params, "status": "done",
        }], ensure_ascii=False),
    )
    photo = GenHistory.create(
        filename="noparams.png", subfolder="", img_type="output",
        job_id=job.id, comfyui_prompt_id="pid-1", prompt_params=None, source="local",
    )

    body = api.get("/api/history?page=1&page_size=50").json()
    item = next(i for i in body["items"] if i["id"] == photo.id)
    assert item["prompt_params"] and item["prompt_params"]["seed"] == 7

    row = GenHistory.get_by_id(photo.id)
    assert row.prompt_params is None, "读取接口不允许回写 prompt_params"
