"""出图跑编辑框所见文本：/api/runs 的 prompt_override / negative_prompt_override。

不传 override 时行为逐字节不变（跑库里的文本）；传了则注入并归档实际文本，
提示词库原文一个字不动。设计见 文档/提示词_出图与试跑收敛_重设计_20261107.md。
"""
import json


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
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["4", 0]}},
    })


def _run(api, monkeypatch, payload):
    from app.services import generation

    pushed = []
    monkeypatch.setattr(
        generation, "push_prompt", lambda wf: pushed.append(wf) or {"prompt_id": "pid"},
    )
    body = api.post("/api/runs", json={
        "workflow_path": "x.json", "workflow_content": _workflow(), **payload,
    }).json()
    return body, pushed


def test_override_is_injected_and_archived_without_touching_prompt(api, seed_prompt, monkeypatch):
    from app.models import GenJob, Prompt

    p = seed_prompt(prompt="【人物面部】库原文", negative_prompt="库负向")
    body, pushed = _run(api, monkeypatch, {
        "id": p.id,
        "prompt_override": "外来草稿文本",
        "negative_prompt_override": "新负向",
    })

    item = json.loads(GenJob.get_by_id(body["job_id"]).items)[0]
    params = json.loads(item["prompt_params"])
    assert params["prompt"] == "外来草稿文本"
    assert params["negative_prompt"] == "新负向"
    assert item["prompt_preview"].startswith("外来草稿文本")
    assert "外来草稿文本" in pushed[0]["3"]["inputs"]["text"]

    saved = Prompt.get_by_id(p.id)
    assert saved.prompt == "【人物面部】库原文"
    assert saved.negative_prompt == "库负向"


def test_no_override_keeps_saved_text(api, seed_prompt, monkeypatch):
    from app.models import GenJob

    p = seed_prompt(prompt="【人物面部】库原文", negative_prompt="库负向")
    body, pushed = _run(api, monkeypatch, {"id": p.id})

    item = json.loads(GenJob.get_by_id(body["job_id"]).items)[0]
    params = json.loads(item["prompt_params"])
    assert params["prompt"] == "库原文"
    assert params["negative_prompt"] == "库负向"
    assert "库原文" in pushed[0]["3"]["inputs"]["text"]


def test_empty_override_is_respected_not_fallback(api, seed_prompt, monkeypatch):
    """显式清空编辑框 = 跑空文本，不能回退成库原文（None 才是未传）。"""
    from app.models import GenJob

    p = seed_prompt(prompt="【人物面部】库原文")
    body, _ = _run(api, monkeypatch, {"id": p.id, "prompt_override": ""})

    item = json.loads(GenJob.get_by_id(body["job_id"]).items)[0]
    assert json.loads(item["prompt_params"])["prompt"] == ""