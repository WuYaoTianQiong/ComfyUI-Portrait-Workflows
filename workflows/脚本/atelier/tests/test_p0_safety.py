"""P0 正确性回归：提交失败计数、sync 多条目、取消语义、push/cancel 竞态、seed。"""
import json

import pytest


def _workflow():
    return json.dumps({
        "1": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 1, "steps": 20, "cfg": 7,
                "sampler_name": "euler", "scheduler": "normal", "denoise": 1,
            },
        },
        "2": {"class_type": "SaveImage", "inputs": {"filename_prefix": "orig"}},
    })


def _latest_job():
    from app.models import GenJob

    return GenJob.select().order_by(GenJob.id.desc()).first()


# ---------------------------------------------------------------------------
# B1 sync 提交失败
# ---------------------------------------------------------------------------

def test_sync_push_failure_marks_items_error_and_counts(api, monkeypatch):
    from app.services import generation

    def boom(_wf):
        raise RuntimeError("ComfyUI 拒绝")

    monkeypatch.setattr(generation, "push_prompt", boom)

    resp = api.post("/api/runs/text", json={
        "prompt": "测试",
        "workflow_path": "x.json",
        "workflow_content": _workflow(),
    })

    assert resp.status_code == 500
    job = _latest_job()
    assert job is not None
    assert job.status == "error"
    assert job.error_count == 1
    items = json.loads(job.items)
    assert items[0]["status"] == "error"
    assert "ComfyUI 拒绝" in items[0]["error"]


# ---------------------------------------------------------------------------
# B2 sync 多条目
# ---------------------------------------------------------------------------

def test_sync_rejects_multiple_indexes():
    from app.services.generation import SubmitSpec, submit_spec
    from app.services.submission import SubmitContractError

    with pytest.raises(SubmitContractError):
        submit_spec(SubmitSpec(
            job_type="single",
            title="多条目",
            items=[{"status": "queued"}, {"status": "queued"}],
            workflow_path="x.json",
            prepare=lambda _index, _ctx: {},
            mode="sync",
            indexes=(0, 1),
        ))


def test_submit_spec_rejects_empty_items_and_unknown_mode():
    from app.services.generation import SubmitSpec, submit_spec
    from app.services.submission import SubmitContractError

    with pytest.raises(SubmitContractError):
        submit_spec(SubmitSpec(
            job_type="single", title="空", items=[], workflow_path="x.json",
            prepare=lambda _index, _ctx: {},
        ))

    with pytest.raises(ValueError):
        submit_spec(SubmitSpec(
            job_type="single", title="未知", items=[{"status": "queued"}],
            workflow_path="x.json", prepare=lambda _index, _ctx: {}, mode="later",
        ))


# ---------------------------------------------------------------------------
# B3 取消终态保护
# ---------------------------------------------------------------------------

def test_cancel_terminal_job_is_rejected_without_rewriting_history(api):
    from app.models import GenJob

    job = GenJob.create(
        job_type="single", status="done", title="已完成", total=2,
        done_count=1, error_count=1,
        items=json.dumps([
            {"status": "done"},
            {"status": "error", "error": "原始错误"},
        ]),
    )

    resp = api.post(f"/api/jobs/{job.id}/cancel")

    assert resp.status_code == 409
    row = GenJob.get_by_id(job.id)
    assert row.status == "done"
    items = json.loads(row.items)
    assert items[0]["status"] == "done"
    assert items[1]["status"] == "error"
    assert items[1]["error"] == "原始错误"


def test_cancel_only_rewrites_pending_and_running_items(api):
    from app.models import GenJob
    from app.services import job_state

    job = GenJob.create(
        job_type="batch", status="running", title="运行中", total=2,
        items=json.dumps([
            {"status": "error", "error": "原始错误"},
            {"status": "running"},
        ]),
    )

    assert job_state.cancel_job(job.id) is True

    row = GenJob.get_by_id(job.id)
    assert row.status == "stopped"
    assert row.error_count == 2
    items = json.loads(row.items)
    assert items[0]["status"] == "error"
    assert items[0]["error"] == "原始错误"
    assert items[1]["status"] == "cancelled"


# ---------------------------------------------------------------------------
# B4 取消与 push 并发
# ---------------------------------------------------------------------------

def test_cancel_during_push_aborts_the_accepted_prompt(monkeypatch):
    from app.models import GenJob
    from app.services import job_state, submission

    job = GenJob.create(
        job_type="batch", status="running", title="竞态", total=1,
        items=json.dumps([{"status": "running"}]),
    )

    aborted = []

    def push_then_cancel(_wf):
        # 模拟用户恰好在这个窗口点击取消：pid 还没落库
        job_state.cancel_job(job.id)
        return {"prompt_id": "pid-race"}

    monkeypatch.setattr(submission, "push_prompt", push_then_cancel)
    monkeypatch.setattr(submission, "_abort_prompt", lambda pid: aborted.append(pid))

    submission.submit_task(submission.SubmitTask(job.id, [0], lambda _index: {}))

    assert aborted == ["pid-race"]
    items = json.loads(GenJob.get_by_id(job.id).items)
    assert items[0]["status"] == "cancelled"
    assert not items[0].get("comfyui_prompt_id")


# ---------------------------------------------------------------------------
# B5 seed 与参数快照
# ---------------------------------------------------------------------------

def test_composer_seed_never_zero_and_sampler_params_are_saved(api, monkeypatch):
    from app.models import GenJob
    from app.routers import composer
    from app.services import generation

    tasks = []
    monkeypatch.setattr(generation, "enqueue_submission", lambda task: tasks.append(task))

    bounds = []

    def fake_randint(low, high):
        bounds.append((low, high))
        return 12345

    monkeypatch.setattr(composer.random, "randint", fake_randint)

    resp = api.post("/api/composer/batch_random_run", json={
        "count": 2,
        "composed_prompts": ["【人物面部】\n第一组", "【人物面部】\n第二组"],
        "workflow_path": "x.json",
        "workflow_content": _workflow(),
    })

    assert resp.status_code == 200, resp.text
    assert tasks, "应入队一个提交任务"

    job = GenJob.get_by_id(resp.json()["job_id"])
    items = json.loads(job.items)
    assert [item["seed"] for item in items] == [12345, 12345]
    assert all(low == 1 for low, _high in bounds), "seed 下限必须是 1，0 会被当成未指定"

    params = json.loads(items[0]["prompt_params"])
    assert params["steps"] == 20
    assert params["cfg_scale"] == 7
    assert params["sampler"] == "euler"
