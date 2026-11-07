"""UI 的 bypass/mute 必须映射到 API 连线，而不是把节点原样提交。"""
import pytest

from app.config import settings
from app.services.workflow_parser import ensure_api_format, load_workflow


def _node(node_id, node_type, inputs, outputs, widgets=None, mode=0):
    return {
        "id": node_id,
        "type": node_type,
        "inputs": inputs,
        "outputs": outputs,
        "widgets_values": widgets or [],
        "mode": mode,
    }


def test_bypassed_latent_chain_is_removed_and_rewired():
    workflow = {
        "nodes": [
            _node(1, "KSamplerAdvanced", [], [{"name": "LATENT", "type": "LATENT", "links": [1]}]),
            _node(
                2, "LatentUpscaleBy",
                [{"name": "samples", "type": "LATENT", "link": 1}],
                [{"name": "LATENT", "type": "LATENT", "links": [2]}],
                ["bicubic", 1.5], mode=4,
            ),
            _node(
                3, "KSampler",
                [
                    {"name": "model", "type": "MODEL", "link": None},
                    {"name": "positive", "type": "CONDITIONING", "link": None},
                    {"name": "negative", "type": "CONDITIONING", "link": None},
                    {"name": "latent_image", "type": "LATENT", "link": 2},
                ],
                [{"name": "LATENT", "type": "LATENT", "links": [3]}],
                [1, "fixed", 4, 1, "euler", "simple", 0.39], mode=4,
            ),
            _node(
                4, "VAEDecode",
                [{"name": "samples", "type": "LATENT", "link": 3}],
                [{"name": "IMAGE", "type": "IMAGE", "links": []}],
            ),
        ],
        "links": [
            [1, 1, 0, 2, 0, "LATENT"],
            [2, 2, 0, 3, 0, "LATENT"],
            [3, 3, 0, 4, 0, "LATENT"],
        ],
    }

    api = ensure_api_format(workflow)
    assert "2" not in api
    assert "3" not in api
    assert api["4"]["inputs"]["samples"] == ["1", 0]


def test_muted_node_drops_its_links():
    workflow = {
        "nodes": [
            _node(1, "LatentUpscaleBy", [], [{"name": "LATENT", "type": "LATENT", "links": [1]}], mode=2),
            _node(
                2, "VAEDecode",
                [{"name": "samples", "type": "LATENT", "link": 1}],
                [{"name": "IMAGE", "type": "IMAGE", "links": []}],
            ),
        ],
        "links": [[1, 1, 0, 2, 0, "LATENT"]],
    }

    api = ensure_api_format(workflow)
    assert "1" not in api
    assert "samples" not in api["2"]["inputs"]


def test_missing_required_defaults_are_filled(monkeypatch):
    """UI 旧 JSON 缺新必填项时，按 object_info 默认值补齐（ResolutionPresetPicker.base_name）。"""
    from app.services import workflow_parser as wp

    monkeypatch.setattr(wp, "get_object_info", lambda: {
        "ResolutionPresetPicker": {
            "input": {
                "required": {
                    "preset": [
                        ["640x960 （2:3）", "720x1280 （9:16）"],
                        {"default": "640x960 （2:3）"},
                    ],
                    "base_name": ["STRING", {"default": "MoodyZIT"}],
                }
            }
        }
    })
    workflow = {
        "nodes": [
            {
                "id": 22,
                "type": "ResolutionPresetPicker",
                "mode": 0,
                "inputs": [
                    {
                        "name": "preset",
                        "type": "COMBO",
                        "widget": {"name": "preset"},
                        "link": None,
                    }
                ],
                "outputs": [
                    {"name": "width", "type": "INT", "links": []},
                    {"name": "height", "type": "INT", "links": []},
                    {"name": "filename_prefix", "type": "STRING", "links": []},
                ],
                "widgets_values": ["640x960 （2:3）"],
                "widgets_values_named": {"preset": "640x960 （2:3）"},
            }
        ],
        "links": [],
    }

    api = wp.ensure_api_format(workflow)
    assert api["22"]["inputs"]["preset"] == "640x960 （2:3）"
    assert api["22"]["inputs"]["base_name"] == "MoodyZIT"


@pytest.mark.parametrize(
    "filename, bypassed, vae_id, first_sampler",
    [
        (
            "MoodyKrea2_V8SE_文生图_单程8步_1128x2008_画质优先.json",
            ("10", "11"), "12", "9",
        ),
        (
            "PornMaster_Krea2V25_文生图_单程8步_1192x2112_fp8_画质优先.json",
            ("175", "176"), "30", "63",
        ),
    ],
)
def test_krea2_single_pass_workflows_do_not_submit_bypassed_second_pass(
    filename, bypassed, vae_id, first_sampler
):
    path = settings.library_root / filename
    assert path.is_file(), f"测试夹具缺失: {path}"
    api = load_workflow(str(path))
    for node_id in bypassed:
        assert node_id not in api
    assert api[vae_id]["inputs"]["samples"] == [first_sampler, 0]
