"""编译器接入注入层：按工作流能力决定正向/负向实际写入什么。"""


def _qwen_workflow() -> dict:
    return {
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
    }


def _zit_workflow() -> dict:
    return {
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": ""}},
        "8": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": ""}},
        "9": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "model": ["5", 0], "positive": ["7", 0], "negative": ["8", 0],
                "latent_image": ["6", 0], "cfg": 3,
            },
        },
    }


def test_qwen_cfg_one_rewrites_positive_but_drops_negative():
    from app.services.workflow_parser import inject_prompt

    wf = _qwen_workflow()
    data = {
        "prompt": "她不要看镜头，穿白衬衫",
        "negative_prompt": "水印",
    }
    inject_prompt(wf, data)

    assert "视线自然垂落，看向画外" in wf["5"]["inputs"]["prompt"]
    assert "不要看镜头" not in wf["5"]["inputs"]["prompt"]
    # cfg=1：负向字段实际不参与采样，不提交任何负向内容
    assert wf["5"]["inputs"]["negative_prompt"] == ""
    compiled = data["compiled"]
    assert compiled["negative_effective"] is False
    assert compiled["negative"] == "水印"
    assert "看镜头" in compiled["extracted"]
    assert compiled["warnings"]


def test_zit_cfg_three_writes_both_compiled_positive_and_negative():
    from app.services.workflow_parser import inject_prompt

    wf = _zit_workflow()
    data = {
        "prompt": "她不要看镜头，穿白衬衫",
        "negative_prompt": "水印",
    }
    inject_prompt(wf, data)

    assert "视线自然垂落，看向画外" in wf["7"]["inputs"]["text"]
    assert "水印" in wf["8"]["inputs"]["text"]
    assert "看镜头" in wf["8"]["inputs"]["text"]
    compiled = data["compiled"]
    assert compiled["negative_effective"] is True
    assert compiled["positive"] == wf["7"]["inputs"]["text"]
    assert compiled["negative"] == wf["8"]["inputs"]["text"]


def test_no_text_node_skips_compilation():
    from app.services.workflow_parser import inject_prompt

    wf = {"1": {"class_type": "SeedVR2VideoUpscaler", "inputs": {}}}
    data = {"prompt": "不要看镜头", "negative_prompt": ""}
    inject_prompt(wf, data)
    assert "compiled" not in data
