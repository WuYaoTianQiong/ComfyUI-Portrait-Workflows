"""批量提交幂等：同一把键只创建一次任务。"""
import json


def _workflow():
    return json.dumps(
        {"1": {"class_type": "SaveImage", "inputs": {"filename_prefix": "orig"}}}
    )


def test_runs_batch_idempotency_key_returns_same_job(api, seed_prompt, monkeypatch):
    from app.models import GenJob
    from app.services import generation, submission

    pushed = []
    fake_push = lambda workflow: pushed.append(workflow) or {"prompt_id": "pid"}
    monkeypatch.setattr(generation, "push_prompt", fake_push)
    monkeypatch.setattr(submission, "push_prompt", fake_push)
    monkeypatch.setattr(generation, "enqueue_submission", submission.submit_task)
    prompt = seed_prompt()
    base = {
        "items": [{"prompt_id": prompt.id, "seed": 1}],
        "workflow_path": "x.json",
        "workflow_content": _workflow(),
        "idempotency_key": "batch-key-1",
    }

    first = api.post("/api/runs/batch", json=base)
    second = api.post("/api/runs/batch", json=base)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["job_id"] == second.json()["job_id"]
    assert second.json()["idempotent"] is True
    assert GenJob.select().count() == 1
    assert len(pushed) == 1

    other = api.post("/api/runs/batch", json={**base, "idempotency_key": "batch-key-2"})
    assert other.status_code == 200, other.text
    assert other.json()["job_id"] != first.json()["job_id"]
    assert GenJob.select().count() == 2


def test_header_key_wins_and_sync_text_run_is_idempotent(api, monkeypatch):
    from app.models import GenJob
    from app.services import generation, submission

    fake_push = lambda wf: {"prompt_id": "pid-text"}
    monkeypatch.setattr(generation, "push_prompt", fake_push)
    monkeypatch.setattr(submission, "push_prompt", fake_push)

    payload = {
        "prompt": "一个幂等测试",
        "workflow_path": "x.json",
        "workflow_content": _workflow(),
    }
    headers = {"X-Idempotency-Key": "text-key-1"}

    first = api.post("/api/runs/text", json=payload, headers=headers)
    second = api.post("/api/runs/text", json=payload, headers=headers)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["job_id"] == second.json()["job_id"]
    assert second.json()["idempotent"] is True
    assert GenJob.select().count() == 1


def test_composer_batch_idempotency_scope(api, monkeypatch):
    from app.models import GenJob
    from app.services import generation, submission

    pushed = []
    fake_push = lambda workflow: pushed.append(workflow) or {"prompt_id": "pid"}
    monkeypatch.setattr(generation, "push_prompt", fake_push)
    monkeypatch.setattr(submission, "push_prompt", fake_push)
    monkeypatch.setattr(generation, "enqueue_submission", submission.submit_task)
    body = {
        "count": 1,
        "composed_prompts": ["【人物面部】测试"],
        "workflow_path": "x.json",
        "workflow_content": _workflow(),
        "idempotency_key": "composer-key-1",
    }

    first = api.post("/api/composer/batch_random_run", json=body)
    second = api.post("/api/composer/batch_random_run", json=body)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["job_id"] == second.json()["job_id"]
    assert second.json()["idempotent"] is True
    assert GenJob.select().count() == 1
    assert len(pushed) == 1
