"""后端契约测试 —— 重构期的回归基线。

原则：锁"行为"不锁"实现"。每条用例对应一个用户可见的承诺（端点存在、键名、筛选语义、
软删除、入库去重）。重构时这些用例变红，就说明行为被破坏了。
"""

import json

import pytest


# ---------------------------------------------------------------------------
# 基础与提示词
# ---------------------------------------------------------------------------

def test_workflow_params_describe_real_quality_semantics():
    """画质 / 方向档位必须能描述"实际怎么改"，而不是让前端摆一排固定 K 值。"""
    from app.services.workflow_parser import detect_workflow_params

    scale = detect_workflow_params({
        "1": {"class_type": "EmptyLatentImage", "inputs": {"width": 1128, "height": 2008}},
    })
    assert scale["quality_mode"] == "scale"
    assert (scale["base_width"], scale["base_height"]) == (1128, 2008)
    assert scale["orientation_mode"] == "swap"

    megapixels = detect_workflow_params({
        "2": {"class_type": "EmptyLatentImage",
              "inputs": {"width": ["9", 0], "height": ["9", 1]}},
        "9": {"class_type": "ResolutionSelector",
              "inputs": {"aspect_ratio": "9:16", "megapixels": 1}},
    })
    assert megapixels["quality_mode"] == "megapixels"
    assert megapixels["base_megapixels"] == 1
    assert megapixels["orientation_mode"] == "knob"

    seedvr = detect_workflow_params({
        "1": {"class_type": "SeedVR2VideoUpscaler", "inputs": {"resolution": 2560}},
    })
    assert seedvr["quality_mode"] == "seedvr"
    assert seedvr["orientation_mode"] == "none"

    video = detect_workflow_params({
        "1": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 1]}},
    })
    assert video["quality_mode"] == "none"


def test_prompts_full_returns_complete_text_under_filters(api, seed_prompt, seed_taxonomy):
    """批量替换要拿完整正文；列表接口只有 60 字预览，不能复用。"""
    from app.models import EntityTag

    long_text = "【人物身材】" + "很长的碎片内容" * 20
    hit = seed_prompt(name="命中", prompt=long_text)
    seed_prompt(name="别的", prompt="【人物面部】短")

    body = api.get("/api/prompts/full?search=人物身材").json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == hit.id
    assert body["items"][0]["prompt"] == long_text
    assert len(body["items"][0]["prompt"]) > 60

    _, tag = seed_taxonomy()
    EntityTag.create(entity_type="prompt", entity_id=hit.id, tag=tag.id)
    tagged = api.get(f"/api/prompts/full?tag_ids={tag.id}").json()
    assert [it["id"] for it in tagged["items"]] == [hit.id]

    # 按 ids 取：勾选项可能跨页/跨筛选，不能再被筛选条件过滤掉
    by_ids = api.get(f"/api/prompts/full?ids={hit.id}").json()
    assert by_ids["total"] == 1
    assert by_ids["items"][0]["prompt"] == long_text


def test_composer_fragments_can_filter_one_type(api, seed_prompt):
    """批量替换的候选来自"提示词里出现过的碎片"，不能只查碎片库。"""
    seed_prompt(prompt="【人物面部】脸\n\n【人物身材】旧身材")

    body = api.get("/api/composer/fragments?fragment_type=人物身材").json()
    assert set(body["grouped"]) == {"人物身材"}
    assert body["fragment_count"] >= 1
    assert all(it["type"] == "人物身材" for it in body["grouped"]["人物身材"])

    searched = api.get("/api/composer/fragments?fragment_type=人物身材&search=旧").json()
    assert len(searched["grouped"]["人物身材"]) == 1


def test_batch_generate_uses_prompt_override(api, seed_prompt, monkeypatch):
    """批量替换只覆盖本次注入的正文，提示词库里的原文不动。"""
    from app.routers import comfyui as comfy_router
    from app.services import submission

    p = seed_prompt(name="原提示词", prompt="【人物身材】旧\n\n【场景环境】街道")

    captured = {}
    monkeypatch.setattr(comfy_router, "load_workflow", lambda *a, **k: {})
    monkeypatch.setattr(comfy_router, "inject_prompt", lambda wf, data: captured.update(data))
    monkeypatch.setattr(submission, "push_prompt", lambda wf: {"prompt_id": "pid-1"})
    # 测试里同步执行后台任务，避免线程时序
    monkeypatch.setattr(comfy_router, "enqueue_submission", submission.submit_task)

    r = api.post("/api/runs/batch", json={
        "items": [{
            "prompt_id": p.id,
            "seed": p.seed or 0,
            "prompt_override": "【人物身材】新\n\n【场景环境】街道",
        }],
        "workflow_path": "F:/wf.json",
    })
    assert r.status_code == 200
    assert r.json()["async"] is True
    assert "新" in captured["prompt"]
    assert "旧" not in captured["prompt"]
    assert "街道" in captured["prompt"]
    # 原文未被写回
    assert api.get(f"/api/prompts/{p.id}").json()["prompt"].startswith("【人物身材】旧")


def test_workflows_api_exposes_params(api):
    """/api/workflows 必须带上 params，否则前端只能退回固定的 2K..12K 死档位。"""
    rows = api.get("/api/workflows").json()["workflows"]
    assert rows, "工作流列表不应为空"
    params = rows[0]["params"]
    assert {"quality_mode", "orientation_mode"} <= set(params)
    # 本机根目录里的常用文生图工作流基准是 megapixels（2.16 / 2.4 MP），必须探测出来
    usable = [r for r in rows if r["params"]["quality_mode"] != "none"]
    assert usable, "至少应有一个可调画质的工作流"
    mp_rows = [r for r in usable if r["params"]["quality_mode"] == "megapixels"]
    assert mp_rows and mp_rows[0]["params"]["base_megapixels"] > 0


def test_status_ok(api):
    r = api.get("/api/system/status")
    assert r.status_code == 200
    body = r.json()
    assert "comfyui" in body


def test_status_reports_offline_when_comfyui_unreachable(api):
    """状态必须是真实探活：曾因 get_queue() 吞异常返回 {}，状态永远是 online，
    导致 ComfyUI 离线时仍允许提交任务（历史 109 个任务里 27 个因此失败）。"""
    body = api.get("/api/system/status").json()
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


def test_prompt_html_endpoint_removed(api, seed_prompt):
    """HTMX 分支已删除（B4）：旧的 HTML 片段端点不应再返回页面。
    路径会落到 /prompts/{prompt_id} 上，所以是 422 而不是 404。"""
    seed_prompt(name="片段可见")
    assert api.get("/api/prompts/html?page=1&page_size=50").status_code in (404, 422)


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

    r = api.get("/api/images?page=1&page_size=50")
    assert r.status_code == 200
    body = r.json()
    assert {"items", "total", "page", "page_size"} <= set(body)
    assert body["total"] == 2


def test_history_soft_delete_hides_item(api, seed_history):
    item = seed_history(filename="gone.png")
    r = api.delete(f"/api/images/{item.id}")
    assert r.status_code == 200

    body = api.get("/api/images?page=1&page_size=50").json()
    assert body["total"] == 0
    # 物理文件与行都保留，只置软删除标记
    from app.models import Image

    assert Image.get_by_id(item.id).is_deleted is True


def test_history_html_endpoint_removed(api, seed_history):
    seed_history(filename="h.png")
    # 路径可能落到 DELETE /images/{item_id} 上（405），只要不是 200 片段即可
    assert api.get("/api/images/html?page=1&page_size=50&sort=newest").status_code in (404, 405, 422)


def test_history_ids_route(api, seed_history):
    seed_history(filename="i1.png")
    seed_history(filename="i2.png")

    r = api.get("/api/images/ids")
    assert r.status_code == 200
    assert len(r.json()["ids"]) == 2


def test_history_ids_respects_category(api, seed_history, seed_taxonomy):
    from app.models import EntityTag, ImageCategory

    keep = seed_history(filename="keep.png")
    drop = seed_history(filename="drop.png")
    cat, tag = seed_taxonomy()
    ImageCategory.create(image=keep.id, category=cat.id)
    EntityTag.create(entity_type="image", entity_id=keep.id, tag=tag.id)

    body = api.get(f"/api/images/ids?category_id={cat.id}").json()
    assert body["ids"] == [keep.id]

    body = api.get(f"/api/images/ids?tag_ids={tag.id}").json()
    assert body["ids"] == [keep.id]


def test_history_missing_filter(api, seed_history):
    """「仅失效」按 missing_since 派生列筛选；文件缺失只是标记，记录本身仍保留。"""
    from datetime import datetime

    from app.models import Image

    gone = seed_history(filename="gone.png")
    kept = seed_history(filename="kept.png")
    Image.update(missing_since=datetime.now()).where(Image.id == gone.id).execute()

    body = api.get("/api/images?missing=1").json()
    assert [it["id"] for it in body["items"]] == [gone.id]
    assert body["items"][0]["missing"] is True

    # 不筛选时两条都在 —— 缺失绝不等于删除
    body = api.get("/api/images").json()
    assert body["total"] == 2
    assert api.get("/api/images/ids?missing=1").json()["ids"] == [gone.id]
    kept_row = Image.get_by_id(kept.id)
    assert bool(kept_row.is_deleted) is False


def test_scan_missing_marks_and_heals(api, seed_history):
    """巡检只维护派生列：第一次标记缺失，文件出现后再次巡检应清除标记。"""
    from app.models import Image
    from app.services.integrity import scan_missing

    item = seed_history(filename="probe.png")

    scan_missing()
    assert Image.get_by_id(item.id).missing_since is not None

    # 把文件补到隔离的 output 目录，再巡检一次应自愈
    from app.config import settings

    (settings.comfyui_root / "output" / "probe.png").write_bytes(b"not-a-real-png")
    try:
        result = scan_missing()
        assert result["cleared"] >= 1
        assert Image.get_by_id(item.id).missing_since is None
    finally:
        (settings.comfyui_root / "output" / "probe.png").unlink(missing_ok=True)


def test_disk_scan_job_index_invalidates_after_new_job(api, seed_prompt):
    """新增任务后，磁盘兜底扫描要能重新匹配到来源提示词。

    旧实现用布尔标记缓存 job 索引，建一次就永不过期 → 服务启动之后新出的图
    全部匹配不到 prompt_id。
    """
    from app.config import settings
    from app.models import Image, GenJob
    from app.routers import images

    prompt = seed_prompt(name="索引提示词")
    target = settings.comfyui_root / "output" / "poll_me.png"
    target.write_bytes(b"x")
    try:
        images._job_index_version = None
        images._sync_disk_orphans()
        row = Image.get_or_none(Image.filename == "poll_me.png")
        assert row is not None and row.prompt_id is None

        # 模拟"任务后建、同名文件重新出现"：清掉记录后建一个已完成任务
        Image.delete().where(Image.filename == "poll_me.png").execute()
        GenJob.create(
            job_type="single", status="done", title="已完成的活", total=1,
            done_count=1,
            items=json.dumps(
                [{"prompt_id": prompt.id, "images": [{"filename": "poll_me.png"}]}],
                ensure_ascii=False,
            ),
        )

        images._sync_disk_orphans()
        row = Image.get_or_none(Image.filename == "poll_me.png")
        assert row is not None
        assert row.prompt_id == prompt.id, "job 索引没有随新任务失效，新图匹配不到提示词"
    finally:
        target.unlink(missing_ok=True)


def test_history_filters_consistent_between_endpoints(api, seed_history, seed_taxonomy):
    """列表、全选、分面共用同一套筛选：相同参数下返回的集合必须一致。

    这三处曾经各写一遍过滤逻辑，已经出现过"列表筛了、全选却选到范围外"，
    紧接着的批量删除就是真删。
    """
    from app.models import EntityTag, ImageCategory

    hit = seed_history(filename="aaa.png", is_favorite=True)
    seed_history(filename="bbb.png", is_favorite=False)
    cat, tag = seed_taxonomy()
    ImageCategory.create(image=hit.id, category=cat.id)
    EntityTag.create(entity_type="image", entity_id=hit.id, tag=tag.id)

    for qs in ("favorite=1", f"category_id={cat.id}", f"tag_ids={tag.id}", "search=aaa"):
        listed = {
            it["id"]
            for it in api.get(f"/api/images?{qs}&page_size=100").json()["items"]
        }
        ids = set(api.get(f"/api/images/ids?{qs}").json()["ids"])
        assert listed == ids, f"筛选条件 {qs} 下列表与全选结果不一致：{listed} vs {ids}"


def _deleted_count():
    from app.models import Image

    return Image.select().where(Image.is_deleted == True).count()


def test_cleanup_missing_dry_run_does_not_write(api, seed_history):
    """清理失效默认只预览：返回将清理多少条 + 样本，绝不写库。"""
    seed_history(filename="gone1.png")
    seed_history(filename="gone2.png")

    body = api.post("/api/images/cleanup_missing").json()
    assert body["dry_run"] is True
    assert body["total"] == 2
    assert body["will_clean"] == 2
    assert [s["filename"] for s in body["samples"]] == ["gone1.png", "gone2.png"]
    assert _deleted_count() == 0


def test_cleanup_missing_requires_confirm(api, seed_history):
    """dry_run=false 但没带 confirm=true 时不得执行。"""
    seed_history(filename="gone.png")

    body = api.post("/api/images/cleanup_missing?dry_run=false").json()
    assert body["success"] is False
    assert "confirm" in body["message"]
    assert _deleted_count() == 0


def test_cleanup_missing_guard_blocks_mass_delete(api, seed_history):
    """缺失占比过半时要熔断：路径解析出错时一键清空整库是历史事故的根源。"""
    for i in range(25):
        seed_history(filename=f"gone_{i}.png")

    assert api.post("/api/images/cleanup_missing").json()["guarded"] is True

    body = api.post("/api/images/cleanup_missing?dry_run=false&confirm=true").json()
    assert body["success"] is False
    assert body["guarded"] is True
    assert _deleted_count() == 0


def test_cleanup_missing_scoped_by_category(api, seed_history, seed_taxonomy):
    """只清理当前筛选范围内的记录，范围外的一条都不能动。"""
    from app.models import Image, ImageCategory

    inside = seed_history(filename="in_cat.png")
    outside = seed_history(filename="out_cat.png")
    cat, _ = seed_taxonomy()
    ImageCategory.create(image=inside.id, category=cat.id)

    body = api.post(
        f"/api/images/cleanup_missing?dry_run=false&confirm=true&category_id={cat.id}"
    ).json()
    assert body["success"] is True
    assert body["cleaned"] == 1
    assert bool(Image.get_by_id(inside.id).is_deleted) is True
    assert bool(Image.get_by_id(outside.id).is_deleted) is False


def test_history_add_category_endpoint(api, seed_history, seed_taxonomy):
    item = seed_history(filename="cat.png")
    cat, _ = seed_taxonomy()

    r = api.post(f"/api/images/{item.id}/categories/{cat.id}")
    assert r.status_code == 200
    assert r.json()["created"] is True


def test_history_add_tag_endpoint(api, seed_history, seed_taxonomy):
    item = seed_history(filename="tag.png")
    _, tag = seed_taxonomy()

    r = api.post(f"/api/images/{item.id}/tags/{tag.id}")
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
    from app.models import GenJob

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
    from app.models import GenJob

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
    from app.models import GenJob

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
    from app.models import GenJob
    from app.services import job_state

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
    from app.models import GenJob
    from app.services import job_state

    job = GenJob.create(
        job_type="batch", status="pending", title="提交中", total=1,
        items=json.dumps([{"prompt_id": 1}], ensure_ascii=False),
    )

    snapshot = job_state.refresh_job(job.id)
    assert snapshot is not None
    assert snapshot["status"] == "pending"
    assert snapshot["items"][0]["status"] == "pending"


def test_refresh_keeps_pids_written_during_slow_compute(api, monkeypatch):
    """写者在锁外算完再回写时，不能抹掉提交阶段刚写回的 comfyui_prompt_id。

    真实故障：批量换脸提交 50 组耗时数分钟，写者用陈旧 items 整体覆盖，
    所有 pid 丢失 → 宽限期后被判「提交失败」，而图其实已经生成（job 110）。
    """
    from app.models import GenJob
    from app.services import job_state

    job = GenJob.create(
        job_type="faceswap", status="pending", title="批量换脸 1×2", total=2,
        items=json.dumps([{"prompt_id": 0, "status": "pending"},
                          {"prompt_id": 0, "status": "pending"}], ensure_ascii=False),
    )
    stale = json.loads(GenJob.get_by_id(job.id).items)

    def fake_compute(job_dict):
        # 模拟 _compute 期间请求线程写回 pid
        fresh = [dict(it, comfyui_prompt_id=f"pid-{i}") for i, it in enumerate(stale)]
        job_state.update_job_items(job.id, fresh, status="running")
        return (dict(job_dict, items=[dict(it) for it in stale], status="pending",
                     done_count=0, error_count=0), [])

    monkeypatch.setattr(job_state, "_compute", fake_compute)

    snapshot = job_state.refresh_job(job.id)
    assert [it["comfyui_prompt_id"] for it in snapshot["items"]] == ["pid-0", "pid-1"]
    assert snapshot["status"] == "running"          # 不能被更早算出的 pending 覆盖
    saved = json.loads(GenJob.get_by_id(job.id).items)
    assert [it["comfyui_prompt_id"] for it in saved] == ["pid-0", "pid-1"]


def test_jobs_list_items_are_arrays(api):
    from app.models import GenJob

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

    body = api.get("/api/images?page=1&page_size=50").json()
    assert [item["filename"] for item in body["items"]][:2] == ["new.png", "old.png"]
    assert body["items"][0]["captured_at"].startswith("2024-06-01")


def test_history_date_facet_uses_captured_at(api, seed_history):
    from datetime import datetime

    seed_history(filename="a.png", captured_at=datetime(2020, 1, 1))
    seed_history(filename="b.png", captured_at=datetime(2024, 6, 1))

    facets = api.get("/api/images/facets").json()
    assert facets["date"].get("2024-06") == 1
    assert facets["date"].get("2020-01") == 1

    filtered = api.get("/api/images?page=1&page_size=50&date=2024-06").json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["filename"] == "b.png"


def test_history_date_falls_back_to_created_at(api, seed_history):
    """老数据没有 captured_at 时，日期筛选仍要能命中（COALESCE 回退）。"""
    from datetime import datetime

    from app.models import Image

    item = seed_history(filename="legacy.png")
    Image.update(captured_at=None, created_at=datetime(2022, 3, 15, 8, 0, 0)) \
        .where(Image.id == item.id).execute()

    filtered = api.get("/api/images?page=1&page_size=50&date=2022-03").json()
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
    from app.models import Image

    p = seed_prompt(name="要删的")
    photo = Image.create(
        filename="keep_me.png", subfolder="", img_type="output",
        prompt_id=p.id, source="local",
    )

    r = api.delete(f"/api/prompts/{p.id}")
    assert r.status_code == 200
    assert r.json()["gen_history_detached"] == 1

    assert api.get(f"/api/prompts/{p.id}").status_code == 404
    kept = Image.get_or_none(Image.id == photo.id)
    assert kept is not None, "出图记录不应被删除"
    assert kept.prompt_id is None, "应只解除与提示词的关联"


def test_gallery_read_does_not_backfill_into_db(api):
    """列表读取时从任务 items 取回缺失参数只用于展示，不得写库。"""
    from app.models import Image, GenJob

    params = json.dumps({"prompt": "【人物面部】x", "seed": 7}, ensure_ascii=False)
    job = GenJob.create(
        job_type="single", status="done", title="历史", total=1,
        items=json.dumps([{
            "prompt_id": 0, "comfyui_prompt_id": "pid-1",
            "prompt_params": params, "status": "done",
        }], ensure_ascii=False),
    )
    photo = Image.create(
        filename="noparams.png", subfolder="", img_type="output",
        job_id=job.id, comfyui_prompt_id="pid-1", prompt_params=None, source="local",
    )

    body = api.get("/api/images?page=1&page_size=50").json()
    item = next(i for i in body["items"] if i["id"] == photo.id)
    assert item["prompt_params"] and item["prompt_params"]["seed"] == 7

    row = Image.get_by_id(photo.id)
    assert row.prompt_params is None, "读取接口不允许回写 prompt_params"
