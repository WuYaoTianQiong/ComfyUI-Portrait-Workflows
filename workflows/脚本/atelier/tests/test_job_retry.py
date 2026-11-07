"""失败/取消条目重试：提示词类与换脸类。"""
import json

from app.config import settings


def _workflow(with_loadimage: bool = False):
    wf = {"2": {"class_type": "SaveImage", "inputs": {"filename_prefix": "orig"}}}
    if with_loadimage:
        wf["1"] = {"class_type": "LoadImage", "inputs": {"image": "old.png"}}
    return json.dumps(wf)


def _make_job(**kw):
    from app.models import GenJob

    defaults = dict(
        job_type="single",
        status="error",
        title="旧任务",
        total=1,
        done_count=0,
        error_count=1,
        workflow_path="x.json",
        orientation="portrait",
        quality="4K",
    )
    defaults.update(kw)
    return GenJob.create(**defaults)


def test_retry_prompt_item_uses_saved_prompt_params(api, monkeypatch):
    from app.models import GenJob
    from app.services import generation, submission

    tasks, pushed = [], []
    monkeypatch.setattr(generation, "enqueue_submission", lambda task: tasks.append(task))
    fake_push = lambda wf: pushed.append(wf) or {"prompt_id": "pid-retry"}
    monkeypatch.setattr(generation, "push_prompt", fake_push)
    monkeypatch.setattr(submission, "push_prompt", fake_push)

    item = {
        "prompt_id": None,
        "seed": 7,
        "prompt_preview": "【人物面部】x",
        "status": "error",
        "error": "boom",
        "prompt_params": json.dumps({
            "source": "composer",
            "prompt": "【人物面部】x",
            "negative_prompt": "",
            "seed": 7,
        }, ensure_ascii=False),
    }
    old = _make_job(
        items=json.dumps([item], ensure_ascii=False),
        extra=json.dumps({
            "workflow_content": _workflow(),
            "output_subfolder": "retry-test",
        }),
    )

    resp = api.post(f"/api/jobs/{old.id}/retry")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["queued"] == 1
    assert body["async"] is True

    submission.submit_task(tasks[0])
    new = GenJob.get_by_id(body["job_id"])
    new_items = json.loads(new.items)
    assert new_items[0]["status"] == "submitted"
    assert new_items[0]["comfyui_prompt_id"] == "pid-retry"
    assert new_items[0]["prompt_params"] == item["prompt_params"]
    assert pushed[0]["2"]["inputs"]["filename_prefix"].startswith("retry-test/orig_atelier_")

    again = api.post(f"/api/jobs/{old.id}/retry")
    assert again.status_code == 200
    assert again.json()["job_id"] == body["job_id"]
    assert again.json()["idempotent"] is True


def test_retry_faceswap_reinjects_inputs(api, monkeypatch, tmp_path):
    from app.models import GenJob
    from app.services import generation, submission

    source = settings.input_dir / "retry_source.png"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"x")
    tasks, pushed = [], []
    monkeypatch.setattr(generation, "enqueue_submission", lambda task: tasks.append(task))
    fake_push = lambda wf: pushed.append(wf) or {"prompt_id": "pid-fs"}
    monkeypatch.setattr(generation, "push_prompt", fake_push)
    monkeypatch.setattr(submission, "push_prompt", fake_push)

    item = {
        "prompt_id": 0,
        "seed": 9,
        "prompt_preview": "目标 × 参考",
        "status": "error",
        "prompt_params": json.dumps({
            "source": "faceswap", "prompt": "编辑", "seed": 9,
        }, ensure_ascii=False),
        "inputs": [{
            "role": "target",
            "node": "1",
            "meta": {"source": "file", "path": str(source)},
        }],
    }
    old = _make_job(
        job_type="faceswap",
        items=json.dumps([item], ensure_ascii=False),
        extra=json.dumps({"workflow_content": _workflow(with_loadimage=True)}),
    )
    try:
        resp = api.post(f"/api/jobs/{old.id}/retry")
        assert resp.status_code == 200, resp.text
        assert resp.json()["queued"] == 1
        submission.submit_task(tasks[0])
        assert pushed[0]["1"]["inputs"]["image"].startswith("atelier_fs_")
        assert pushed[0]["2"]["inputs"]["filename_prefix"].startswith("retry")
    finally:
        source.unlink(missing_ok=True)


def test_retry_without_failed_items_returns_400(api):
    old = _make_job(
        status="done",
        done_count=1,
        error_count=0,
        items=json.dumps([{"status": "done", "prompt_id": 1}]),
    )
    resp = api.post(f"/api/jobs/{old.id}/retry")
    assert resp.status_code == 400
