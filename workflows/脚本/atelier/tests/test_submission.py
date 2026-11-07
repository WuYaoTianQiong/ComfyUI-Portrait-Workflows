"""批量提交异步队列：立即返回、后台提交、取消与重启恢复。"""
import json


def _workflow():
    return json.dumps(
        {"1": {"class_type": "SaveImage", "inputs": {"filename_prefix": "orig"}}}
    )


def _text_workflow():
    """两个文本编码节点 + cfg=3：负向通道有效。"""
    return json.dumps({
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": ""}},
        "8": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": ""}},
        "9": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "model": ["5", 0], "positive": ["7", 0], "negative": ["8", 0],
                "latent_image": ["6", 0], "cfg": 3,
            },
        },
    })


def test_batch_submission_moves_avoid_section_to_negative(api, seed_prompt, monkeypatch):
    """【避免】不能被提前剥标题吞掉，必须进入负向节点。"""
    from app.services import generation, submission

    tasks = []
    pushed = []
    monkeypatch.setattr(generation, "enqueue_submission", lambda task: tasks.append(task))
    fake_push = lambda wf: pushed.append(wf) or {"prompt_id": "pid-avoid"}
    monkeypatch.setattr(generation, "push_prompt", fake_push)
    monkeypatch.setattr(submission, "push_prompt", fake_push)

    p = seed_prompt(prompt="【人物面部】\n她穿白衬衫\n\n【避免】\n错字、乱码")
    body = api.post("/api/runs/batch", json={
        "items": [{"prompt_id": p.id, "seed": 1}],
        "workflow_path": "x.json",
        "workflow_content": _text_workflow(),
    }).json()
    assert body["queued"] == 1

    submission.submit_task(tasks[0])

    wf = pushed[0]
    positive = wf["7"]["inputs"]["text"]
    negative = wf["8"]["inputs"]["text"]
    assert "【人物面部】" not in positive
    assert "错字" not in positive
    assert "错字" in negative


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
    assert items[0]["status"] == "queued"
    assert not items[0].get("comfyui_prompt_id")

    submission.submit_task(tasks[0])
    items = json.loads(GenJob.get_by_id(body["job_id"]).items)
    assert len(pushed) == 1
    assert items[0]["status"] == "submitted"
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
        items=json.dumps([{"status": "queued"}]),
    )
    assert job_state.recover_queued_submissions() == 1

    row = GenJob.get_by_id(job.id)
    items = json.loads(row.items)
    assert items[0]["status"] == "error"
    assert "submit_state" not in items[0]
    assert "重启" in items[0]["error"]
