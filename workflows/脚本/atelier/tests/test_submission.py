"""批量提交异步队列：立即返回、后台提交、取消与重启恢复。"""
import json


def _workflow():
    return json.dumps(
        {"1": {"class_type": "SaveImage", "inputs": {"filename_prefix": "orig"}}}
    )


def test_batch_endpoint_returns_immediately_then_submits(api, seed_prompt, monkeypatch):
    from app.models import GenJob
    from app.services import generation, submission

    tasks = []
    pushed = []
    monkeypatch.setattr(generation, "enqueue_submission", lambda task: tasks.append(task))
    fake_push = lambda wf: pushed.append(wf) or {"prompt_id": "pid-async"}
    monkeypatch.setattr(generation, "push_prompt", fake_push)
    monkeypatch.setattr(submission, "push_prompt", fake_push)

    p = seed_prompt()
    resp = api.post("/api/runs/batch", json={
        "items": [{"prompt_id": p.id, "seed": 1}],
        "workflow_path": "x.json",
        "workflow_content": _workflow(),
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["async"] is True
    assert body["queued"] == 1
    assert body["submitted"] == 0
    assert len(tasks) == 1

    items = json.loads(GenJob.get_by_id(body["job_id"]).items)
    assert items[0]["submit_state"] == "queued"
    assert not items[0].get("comfyui_prompt_id")

    submission.submit_task(tasks[0])
    items = json.loads(GenJob.get_by_id(body["job_id"]).items)
    assert len(pushed) == 1
    assert items[0]["submit_state"] == "submitted"
    assert items[0]["comfyui_prompt_id"] == "pid-async"


def test_cancelled_before_submit_is_not_pushed(api, seed_prompt, monkeypatch):
    from app.models import GenJob
    from app.services import generation, submission

    tasks = []
    pushed = []
    monkeypatch.setattr(generation, "enqueue_submission", lambda task: tasks.append(task))
    fake_push = lambda wf: pushed.append(wf) or {"prompt_id": "pid-late"}
    monkeypatch.setattr(generation, "push_prompt", fake_push)
    monkeypatch.setattr(submission, "push_prompt", fake_push)

    p = seed_prompt()
    body = api.post("/api/runs/batch", json={
        "items": [{"prompt_id": p.id, "seed": 1}],
        "workflow_path": "x.json",
        "workflow_content": _workflow(),
    }).json()

    assert api.post(f"/api/jobs/{body['job_id']}/cancel").status_code == 200
    submission.submit_task(tasks[0])

    assert pushed == []
    items = json.loads(GenJob.get_by_id(body["job_id"]).items)
    assert items[0]["status"] == "cancelled"


def test_recover_queued_submissions_marks_interrupted(api):
    from app.models import GenJob
    from app.services import job_state

    job = GenJob.create(
        job_type="batch", status="running", title="中断", total=1,
        items=json.dumps([{"status": "pending", "submit_state": "queued"}]),
    )
    assert job_state.recover_queued_submissions() == 1

    row = GenJob.get_by_id(job.id)
    items = json.loads(row.items)
    assert items[0]["status"] == "error"
    assert items[0]["submit_state"] == "failed"
    assert "重启" in items[0]["error"]
