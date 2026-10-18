"""后端契约测试 —— 重构期的回归基线。

原则：锁"行为"不锁"实现"。每条用例对应一个用户可见的承诺（端点存在、键名、筛选语义、
软删除、入库去重）。重构时这些用例变红，就说明行为被破坏了。
"""

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
    """ComfyUI 不可达时，任务快照必须返回 200 而不是 500。"""
    from models import GenJob

    job = GenJob.create(
        job_type="single", status="pending", title="离线", total=0,
        done_count=0, error_count=0, items="[]",
    )
    r = api.get(f"/api/jobs/{job.id}")
    assert r.status_code == 200
    assert r.json()["id"] == job.id
