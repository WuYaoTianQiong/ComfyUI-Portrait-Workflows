"""P2：同一个 job 的 item 可以各自带工作流/画质/比例。"""
import json


def _text_workflow(node_id: str, prefix: str) -> str:
    return json.dumps({
        node_id: {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["9", 0], "text": ""},
        },
        "2": {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix}},
    })


def test_batch_items_use_their_own_workflow(api, seed_prompt, monkeypatch):
    from app.models import GenJob
    from app.services import generation, submission

    tasks, pushed = [], []
    monkeypatch.setattr(generation, "enqueue_submission", lambda task: tasks.append(task))

    def fake_push(wf):
        pushed.append(wf)
        return {"prompt_id": f"pid-{len(pushed)}"}

    monkeypatch.setattr(submission, "push_prompt", fake_push)

    first = seed_prompt(prompt="【人物面部】甲")
    second = seed_prompt(prompt="【人物面部】乙")
    wf_a = _text_workflow("7", "a")
    wf_b = _text_workflow("8", "b")

    body = api.post("/api/runs/batch", json={
        "items": [
            {"prompt_id": first.id, "workflow_content": wf_a, "quality": "0.75x"},
            {"prompt_id": second.id, "workflow_content": wf_b, "quality": "2.0x"},
        ],
        "workflow_path": "x.json",
        "workflow_content": wf_a,
        "quality": "1.0x",
    }).json()

    assert body["queued"] == 2
    submission.submit_task(tasks[0])

    assert "甲" in pushed[0]["7"]["inputs"]["text"]
    assert "乙" in pushed[1]["8"]["inputs"]["text"]

    items = json.loads(GenJob.get_by_id(body["job_id"]).items)
    assert items[0]["quality"] == "0.75x"
    assert items[1]["quality"] == "2.0x"


def test_retry_prefers_item_workflow_and_quality():
    from app.services.job_retry import _build_prompt_workflow

    wf_a = _text_workflow("7", "a")
    wf_b = _text_workflow("8", "b")
    job = {
        "workflow_path": "job.json",
        "workflow_content": wf_a,
        "quality": "1.0x",
        "orientation": "portrait",
        "extra": json.dumps({"workflow_content": wf_a}),
    }
    item = {
        "workflow_path": "item.json",
        "workflow_content": wf_b,
        "quality": "2.0x",
        "orientation": "landscape",
        "prompt_params": json.dumps({"prompt": "【人物面部】重试"}),
    }

    api_wf = _build_prompt_workflow(job, item, 1, "")

    assert "8" in api_wf
    assert "7" not in api_wf
    assert "重试" in api_wf["8"]["inputs"]["text"]
