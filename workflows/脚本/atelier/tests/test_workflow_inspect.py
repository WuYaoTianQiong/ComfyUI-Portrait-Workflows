"""caps / 尺寸预演：后端是唯一真源，预览必须等于实际注入。"""
import copy
import json

from app.services.workflow_parser import (
    apply_quality_tiers,
    build_size_preview,
    detect_workflow_params,
    inject_prompt,
)


def _workflow(extra: dict | None = None) -> dict:
    wf = {
        "1": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 768, "height": 1024, "batch_size": 1},
        },
        "2": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 0], "text": ""}},
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["5", 0], "positive": ["2", 0], "negative": ["2", 0],
                "latent_image": ["1", 0], "seed": 1, "steps": 20, "cfg": 1,
                "sampler_name": "euler", "scheduler": "normal", "denoise": 1,
            },
        },
        "4": {"class_type": "CLIPLoader", "inputs": {}},
        "5": {"class_type": "UNETLoader", "inputs": {}},
        "6": {"class_type": "SaveImage", "inputs": {"images": ["3", 0], "filename_prefix": "x"}},
    }
    if extra is not None:
        wf["extra"] = extra
    return wf


def test_size_preview_matches_actual_injection():
    wf = _workflow()
    params = apply_quality_tiers(
        detect_workflow_params(wf),
        {"extra": {"atelier": {"quality_tiers": ["4K", "6K"]}}},
    )
    preview = build_size_preview(wf, params)

    assert set(preview) == {"4K", "6K"}
    for tier, per_ratio in preview.items():
        assert per_ratio, f"{tier} 没有比例尺寸"
        for ratio, expected in per_ratio.items():
            injected = copy.deepcopy(wf)
            inject_prompt(injected, {
                "prompt": "", "seed": 1, "aspect_ratio": ratio,
                "quality": tier, "orientation": "portrait",
            })
            latent = injected["1"]["inputs"]
            assert (latent["width"], latent["height"]) == (
                expected["width"], expected["height"],
            ), f"{tier} {ratio} 预览与实际注入不一致"


def test_inspect_endpoint_returns_caps_and_preview(api):
    wf = _workflow({"atelier": {"quality_tiers": ["4K"], "default_quality": "4K"}})
    resp = api.post("/api/workflows/inspect", json={
        "workflow_path": "custom://preview",
        "workflow_content": json.dumps(wf, ensure_ascii=False),
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["caps"]["prompt"] is True
    assert body["params"]["quality_mode"] == "scale"
    assert body["params"]["quality_tiers"] == ["4K"]
    assert body["size_preview"]["4K"]


def test_inspect_requires_path_or_content(api):
    assert api.post("/api/workflows/inspect", json={}).status_code == 400
