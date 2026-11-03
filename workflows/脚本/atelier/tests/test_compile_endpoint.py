"""POST /api/prompts/compile：预览编译结果，不出图、不写库。"""

import json


def _qwen() -> str:
    return json.dumps({
        "5": {
            "class_type": "TextEncodeQwenImage21",
            "inputs": {"clip": ["2", 0], "prompt": "", "negative_prompt": ""},
        },
        "7": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["4", 0], "positive": ["5", 0], "negative": ["5", 1],
                "latent_image": ["6", 0], "cfg": 1,
            },
        },
    })


def _zit() -> str:
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


def test_compile_preview_reports_ineffective_qwen_negative(api):
    resp = api.post("/api/prompts/compile", json={
        "prompt": "她不要看镜头，穿白衬衫",
        "negative_prompt": "水印",
        "workflow_path": "custom://qwen",
        "workflow_content": _qwen(),
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["negative_effective"] is False
    assert body["negative"] == "水印"
    assert "看镜头" in body["extracted"]
    assert "视线自然垂落" in body["positive"]


def test_compile_preview_reports_effective_zit_negative(api):
    resp = api.post("/api/prompts/compile", json={
        "prompt": "她不要看镜头，穿白衬衫",
        "negative_prompt": "水印",
        "workflow_path": "custom://zit",
        "workflow_content": _zit(),
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["negative_effective"] is True
    assert body["negative_cfg"] == 3.0
    assert "水印" in body["negative"]
    assert "看镜头" in body["negative"]


def test_compile_preview_strips_fragment_headers(api):
    resp = api.post("/api/prompts/compile", json={
        "prompt": "【人物面部】\n她不要看镜头，穿白衬衫",
        "workflow_path": "custom://zit",
        "workflow_content": _zit(),
    })
    assert resp.status_code == 200
    assert "【人物面部】" not in resp.json()["positive"]


def test_compile_preview_requires_workflow(api):
    resp = api.post("/api/prompts/compile", json={"prompt": "x"})
    assert resp.status_code == 400
