"""`/api/composer/*` 出图入口的行为契约。

锁的是一条容易再次退化的规则：组合器里的 `【类型】` 标题只用于人看，
真正注入 CLIP 的正文必须和其它出图入口（`/api/comfyui/*`）一样剥掉标题。
"""

COMBINED = "【人物面部】\n黑色长发\n\n【人物身材】\n纤细高挑"


def _patch_pipeline(monkeypatch):
    """替掉真实工作流加载与提交，只回放注入后的提示词。"""
    from app.routers import composer as composer_router
    from app.services import generation, submission

    sent: list[str] = []

    def fake_load(path, content=None):
        # 只含一个文本编码节点的最小工作流：inject_prompt 会往它的 text 写正面提示词
        return {"1": {"class_type": "CLIPTextEncode", "inputs": {"clip": [2, 0], "text": ""}}}

    def fake_push(workflow):
        sent.append(workflow["1"]["inputs"]["text"])
        return {"prompt_id": f"pid-{len(sent)}"}

    monkeypatch.setattr(composer_router, "load_workflow", fake_load)
    monkeypatch.setattr(generation, "push_prompt", fake_push)
    monkeypatch.setattr(submission, "push_prompt", fake_push)
    # 测试里同步执行后台任务，避免线程时序
    monkeypatch.setattr(generation, "enqueue_submission", submission.submit_task)
    return sent


def _assert_no_headers(text: str):
    assert "【" not in text and "】" not in text, f"标题被注入了模型: {text!r}"
    assert "黑色长发" in text and "纤细高挑" in text, f"正文丢失: {text!r}"


def test_composer_run_strips_type_headers(api, monkeypatch):
    sent = _patch_pipeline(monkeypatch)

    resp = api.post(
        "/api/composer/run",
        json={"prompt": COMBINED, "workflow_path": "fake.json"},
    )

    assert resp.status_code == 200, resp.text
    assert len(sent) == 1
    _assert_no_headers(sent[0])


def test_batch_random_run_strips_type_headers(api, monkeypatch):
    sent = _patch_pipeline(monkeypatch)

    resp = api.post(
        "/api/composer/batch_random_run",
        json={
            "count": 2,
            "composed_prompts": [COMBINED, COMBINED],
            "workflow_path": "fake.json",
        },
    )

    assert resp.status_code == 200, resp.text
    assert len(sent) == 2
    for text in sent:
        _assert_no_headers(text)
