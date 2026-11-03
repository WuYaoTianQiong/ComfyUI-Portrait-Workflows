"""负向能力探测：结构上有输入框，不等于采样时真的生效。"""


def _caps(wf: dict) -> dict:
    from app.services.workflow_parser import detect_workflow_caps

    return detect_workflow_caps(wf)


def test_qwen_negative_field_is_inert_at_cfg_one():
    """Qwen 的 negative_prompt 字段存在，但 cfg=1 时数学上不参与采样。"""
    wf = {
        "5": {
            "class_type": "TextEncodeQwenImage21",
            "inputs": {"clip": ["2", 0], "vae": ["3", 0], "prompt": "正", "negative_prompt": "负"},
        },
        "7": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["4", 0], "positive": ["5", 0], "negative": ["5", 1],
                "latent_image": ["6", 0], "seed": 1, "steps": 32, "cfg": 1,
                "sampler_name": "euler", "scheduler": "simple", "denoise": 1,
            },
        },
    }
    caps = _caps(wf)
    assert caps["negative"] is True
    assert caps["negative_effective"] is False
    assert caps["negative_cfg"] == 1.0


def test_zit_negative_is_effective_on_first_pass():
    """ZIT 第一程 cfg=3 且负向接文本节点；第二程 cfg=1 不应把结论拉回 false。"""
    wf = {
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": "正"}},
        "8": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": "负"}},
        "9": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "model": ["5", 0], "positive": ["7", 0], "negative": ["8", 0],
                "latent_image": ["6", 0], "noise_seed": 1, "steps": 17, "cfg": 3,
            },
        },
        "11": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "model": ["5", 0], "positive": ["7", 0], "negative": ["8", 0],
                "latent_image": ["10", 0], "noise_seed": 2, "steps": 11, "cfg": 1,
            },
        },
    }
    caps = _caps(wf)
    assert caps["negative_effective"] is True
    assert caps["negative_cfg"] == 3.0


def test_zeroed_negative_is_not_effective_even_with_two_text_nodes():
    """Flux 有两个 CLIPTextEncode，但负向被 ConditioningZeroOut 清零。"""
    wf = {
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": "正"}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": "负"}},
        "6": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["5", 0]}},
        "11": {
            "class_type": "CFGGuider",
            "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["6", 0], "cfg": 1},
        },
    }
    caps = _caps(wf)
    assert caps["negative"] is True
    assert caps["negative_effective"] is False
    assert caps["negative_cfg"] is None


def test_single_text_node_with_zero_out_has_no_negative_channel():
    """Krea2/Porn 的单程线：只有一个文本节点，负向直接清零。"""
    wf = {
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": "正"}},
        "8": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["6", 0]}},
        "9": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "model": ["1", 0], "positive": ["6", 0], "negative": ["8", 0],
                "latent_image": ["5", 0], "noise_seed": 1, "steps": 8, "cfg": 1,
            },
        },
    }
    caps = _caps(wf)
    assert caps["negative"] is False
    assert caps["negative_effective"] is False
    assert caps["negative_cfg"] is None


def test_conditioning_passthrough_keeps_negative_effective():
    """负向经过 ConditioningCombine 等透传节点时仍能回溯到文本节点。"""
    wf = {
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": "正"}},
        "8": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": "负"}},
        "10": {
            "class_type": "ConditioningCombine",
            "inputs": {"conditioning_1": ["8", 0], "conditioning_2": ["9", 0]},
        },
        "9": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["7", 0]}},
        "11": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "model": ["1", 0], "positive": ["7", 0], "negative": ["10", 0],
                "latent_image": ["6", 0], "noise_seed": 1, "steps": 12, "cfg": 2.5,
            },
        },
    }
    caps = _caps(wf)
    assert caps["negative_effective"] is True
    assert caps["negative_cfg"] == 2.5
