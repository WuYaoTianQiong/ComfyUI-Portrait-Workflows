"""seed 口径：0/None = 未指定；记录值必须等于实际注入值。"""
import json

from app.services.workflow_parser import resolve_seed


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


def test_resolve_seed_takes_first_positive_value():
    assert resolve_seed(123) == 123
    assert resolve_seed(None, 0, 7, 9) == 7
    assert resolve_seed(0, None) > 0


def test_run_text_records_effective_seed(api, monkeypatch):
    from app.models import GenJob
    from app.services import generation

    monkeypatch.setattr(generation, "push_prompt", lambda wf: {"prompt_id": "pid-text"})

    body = api.post("/api/runs/text", json={
        "prompt": "一个测试提示词",
        "workflow_path": "x.json",
        "workflow_content": _workflow(),
    }).json()

    assert body["seed"] > 0
    item = json.loads(GenJob.get_by_id(body["job_id"]).items)[0]
    assert item["seed"] == body["seed"]
    assert json.loads(item["prompt_params"])["seed"] == body["seed"]


def test_batch_uses_saved_prompt_seed_when_item_omits(api, seed_prompt, monkeypatch):
    from app.models import GenJob
    from app.services import generation, submission

    tasks, pushed = [], []
    monkeypatch.setattr(generation, "enqueue_submission", lambda task: tasks.append(task))
    fake_push = lambda wf: pushed.append(wf) or {"prompt_id": "pid-batch"}
    monkeypatch.setattr(generation, "push_prompt", fake_push)
    monkeypatch.setattr(submission, "push_prompt", fake_push)

    p = seed_prompt(seed=42)
    body = api.post("/api/runs/batch", json={
        "items": [{"prompt_id": p.id}],
        "workflow_path": "x.json",
        "workflow_content": _workflow(),
    }).json()

    item = json.loads(GenJob.get_by_id(body["job_id"]).items)[0]
    assert item["seed"] == 42

    submission.submit_task(tasks[0])
    assert pushed[0]["1"]["inputs"]["seed"] == 42


def test_batch_explicit_seed_wins_and_random_is_recorded(api, seed_prompt, monkeypatch):
    from app.models import GenJob
    from app.services import generation, submission

    tasks, pushed = [], []
    monkeypatch.setattr(generation, "enqueue_submission", lambda task: tasks.append(task))
    fake_push = lambda wf: pushed.append(wf) or {"prompt_id": "pid-batch"}
    monkeypatch.setattr(generation, "push_prompt", fake_push)
    monkeypatch.setattr(submission, "push_prompt", fake_push)

    p = seed_prompt(seed=0)  # 0 = 没保存种子
    body = api.post("/api/runs/batch", json={
        "items": [{"prompt_id": p.id}],
        "workflow_path": "x.json",
        "workflow_content": _workflow(),
    }).json()

    item = json.loads(GenJob.get_by_id(body["job_id"]).items)[0]
    assert item["seed"] > 0
    submission.submit_task(tasks[0])
    assert pushed[0]["1"]["inputs"]["seed"] == item["seed"]
