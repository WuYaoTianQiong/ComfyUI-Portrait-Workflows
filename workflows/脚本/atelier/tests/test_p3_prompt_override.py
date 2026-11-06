"""P3 手动改写：`prompt_override` + `skip_compile`（方案 2026-11-06 §14.2 / §14.3）。

覆盖 6 组行为：

1. `inject_prompt(skip_compile=True)`：正向原文一字不改（「不要军姿」仍在正向），
   负向只用用户填写的内容；负向通道不生效时负向为空；
2. `inject_prompt(skip_compile=False)`：既有 `compile_prompt` 行为回归
   （否定抽成负向、正向改肯定描述）；
3. API `dry_run` + `prompt_override`：返回原文、`manual_override=true`、负向正确；
   槽位文本字段不参与（不渲染、不校验）；
4. API 真实提交：提交载荷带 `skip_compile=true` 与 `prompt=override`，响应 prompt 为原文；
5. API 不带 `prompt_override`：P1/P2 自动模式行为与响应形状不变；
6. 三槽全无图 + `prompt_override`：仍是 400。

夹具复用 `tests/test_reference_recipes.py`（参考库 JSON、最小 Qwen21 工作流、
`captured` 截获提交），不重复造数据。
"""
from __future__ import annotations

import json

from app.services.workflow_parser import inject_prompt
from test_reference_recipes import (  # noqa: F401 —— 复用既有 pytest 夹具
    THREE_BODY,
    captured,
    recipe_env,
)

OVERRIDE = (
    "• 人物：一位冷白皮、鹅蛋脸的年轻女性，深棕及肩短发。\n"
    "• 服装：象牙白针织衫搭配黑色直筒裤。\n"
    "• 姿势：站在窗边，不要军姿。\n"
    "• 场景：室内卧室，柔和自然光。"
)
USER_NEGATIVE = "水印, 文字, 多人"


# ---------------------------------------------------------------------------
# 工作流构造：文本编码节点 + KSampler（判断负向是否真正参与采样）
# ---------------------------------------------------------------------------


def _two_encoder_workflow(*, cfg: float = 7.0) -> dict:
    """旧式双文本编码节点：正向写 10、负向写 11；cfg<=1 时负向不生效。"""
    return {
        "1": {
            "class_type": "LoadImage",
            "inputs": {"image": "ref.png"},
        },
        "7": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 896, "height": 1184, "batch_size": 1},
        },
        "10": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["5", 0], "text": "旧正向"},
        },
        "11": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["5", 0], "text": "旧负向"},
        },
        "12": {
            "class_type": "KSampler",
            "inputs": {
                "positive": ["10", 0],
                "negative": ["11", 0],
                "cfg": cfg,
                "model": ["6", 0],
                "latent_image": ["7", 0],
                "seed": 1,
                "steps": 20,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
            },
        },
    }


def _single_node_workflow() -> dict:
    """Qwen21 形态：正负字段在同一个文本编码节点上。"""
    return {
        "8": {
            "class_type": "TextEncodeQwenImage21",
            "inputs": {
                "clip": ["5", 0],
                "prompt": "旧正向",
                "negative_prompt": "旧负向",
            },
        },
        "9": {
            "class_type": "KSampler",
            "inputs": {
                "positive": ["8", 0],
                "negative": ["8", 0],
                "cfg": 7.0,
                "model": ["6", 0],
                "latent_image": ["7", 0],
                "seed": 1,
                "steps": 25,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
            },
        },
        "7": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 896, "height": 1184, "batch_size": 1},
        },
    }


def _p3_studio_workflow() -> dict:
    """默认 Qwen21 三槽工作流 + KSampler（负向真实生效，cfg=7）。"""
    return {
        "1": {
            "class_type": "LoadImage",
            "inputs": {"image": "pose_ref.webp"},
            "_meta": {"title": "图3：姿势参考 (Pose) · 深度图"},
        },
        "2": {
            "class_type": "LoadImage",
            "inputs": {"image": "portrait_ref.webp"},
            "_meta": {"title": "图1：人像参考 (Portrait)"},
        },
        "3": {
            "class_type": "LoadImage",
            "inputs": {"image": "costume_ref.webp"},
            "_meta": {"title": "图2：服装参考 (Costume)"},
        },
        "7": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 896, "height": 1184, "batch_size": 1},
        },
        "8": {
            "class_type": "TextEncodeQwenImage21",
            "inputs": {
                "clip": ["5", 0],
                "prompt": "",
                "negative_prompt": "",
                "images.image_1": ["1", 0],
                "images.image_2": ["2", 0],
                "images.image_3": ["3", 0],
            },
        },
        "9": {
            "class_type": "KSampler",
            "inputs": {
                "positive": ["8", 0],
                "negative": ["8", 0],
                "cfg": 7.0,
                "model": ["6", 0],
                "latent_image": ["7", 0],
                "seed": 1,
                "steps": 25,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
            },
        },
    }


def _use_negative_effective_workflow(recipe_env: dict) -> None:
    """把默认工作流换成带 KSampler 的版本，让 `negative_effective` 为真。"""
    path = recipe_env["default_workflow"]
    path.write_text(
        json.dumps(_p3_studio_workflow(), ensure_ascii=False), encoding="utf-8",
    )


def _post(api, payload: dict):
    return api.post("/api/reference/recipes", json=payload)


# ---------------------------------------------------------------------------
# 1. inject_prompt(skip_compile=True)
# ---------------------------------------------------------------------------


def test_skip_compile_keeps_positive_verbatim_and_writes_user_negative():
    """正向原文一字不改；负向按用户输入写入；compiled 保持 CompiledPrompt 同形。"""
    workflow = _two_encoder_workflow(cfg=7.0)
    prompt_data = {
        "prompt": "• 姿势：站在窗边，不要军姿。",
        "negative_prompt": USER_NEGATIVE,
        "skip_compile": True,
    }

    inject_prompt(workflow, prompt_data)

    assert workflow["10"]["inputs"]["text"] == "• 姿势：站在窗边，不要军姿。"
    assert workflow["11"]["inputs"]["text"] == USER_NEGATIVE
    assert "军姿" in workflow["10"]["inputs"]["text"], "手动模式不得把否定词从正向抽走"

    compiled = prompt_data["compiled"]
    assert set(compiled) == {
        "positive", "negative", "notes", "warnings", "extracted", "negative_effective",
    }
    assert compiled["positive"] == "• 姿势：站在窗边，不要军姿。"
    assert compiled["negative"] == USER_NEGATIVE
    assert compiled["negative_effective"] is True


def test_skip_compile_writes_empty_negative_when_channel_is_ineffective():
    """negative_effective=False：负向字段写空串，不假装负向生效。"""
    workflow = _two_encoder_workflow(cfg=1.0)
    prompt_data = {
        "prompt": "• 姿势：站在窗边，不要军姿。",
        "negative_prompt": USER_NEGATIVE,
        "skip_compile": True,
    }

    inject_prompt(workflow, prompt_data)

    assert workflow["10"]["inputs"]["text"] == "• 姿势：站在窗边，不要军姿。"
    assert workflow["11"]["inputs"]["text"] == ""
    assert prompt_data["compiled"]["negative_effective"] is False


def test_skip_compile_writes_single_node_negative_field():
    """单节点自带 negative_prompt 时，用户负向写回同一节点。"""
    workflow = _single_node_workflow()
    prompt_data = {
        "prompt": "• 人物：冷白皮、鹅蛋脸。",
        "negative_prompt": USER_NEGATIVE,
        "skip_compile": True,
    }

    inject_prompt(workflow, prompt_data)

    assert workflow["8"]["inputs"]["prompt"] == "• 人物：冷白皮、鹅蛋脸。"
    assert workflow["8"]["inputs"]["negative_prompt"] == USER_NEGATIVE


# ---------------------------------------------------------------------------
# 2. inject_prompt(skip_compile=False) 回归
# ---------------------------------------------------------------------------


def test_skip_compile_false_keeps_existing_compile_behavior():
    """保持既有行为：否定抽成负向，正向改肯定描述。"""
    workflow = _two_encoder_workflow(cfg=7.0)
    prompt_data = {
        "prompt": "正面站姿，不要文字水印。",
        "negative_prompt": "",
        "skip_compile": False,
    }

    inject_prompt(workflow, prompt_data)

    assert workflow["10"]["inputs"]["text"] == "正面站姿，画面干净，只有主体与场景。"
    assert workflow["11"]["inputs"]["text"] == "文字, 水印"
    assert prompt_data["compiled"]["extracted"] == ["文字", "水印"]


# ---------------------------------------------------------------------------
# 3. API dry_run + prompt_override
# ---------------------------------------------------------------------------


def test_dry_run_manual_override_returns_verbatim_prompt(api, recipe_env, captured):
    """dry_run 返回 override 原文、manual_override=true、用户负向（生效时）。"""
    _use_negative_effective_workflow(recipe_env)

    resp = _post(
        api,
        {
            **THREE_BODY,
            "prompt_override": OVERRIDE,
            "negative_prompt": USER_NEGATIVE,
            "dry_run": True,
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["prompt"] == OVERRIDE
    assert body["prompt_raw"] == OVERRIDE
    assert body["manual_override"] is True
    assert body["negative_effective"] is True
    assert body["negative_prompt"] == USER_NEGATIVE
    # 手动模式不再渲染碎片：自动生成的图片主句 / 图号一个都不应出现
    assert "图2中的人物" not in body["prompt"]
    assert len(captured) == 1
    assert captured[0].skip_compile is True
    assert captured[0].prompt == OVERRIDE


def test_manual_override_ignores_slot_text_fields(api, recipe_env, captured):
    """手动模式下槽位文本不参与：不渲染、bare + 服装文本也不再 400。"""
    resp = _post(
        api,
        {
            "portrait_id": "p1",
            "costume_id": "SPR-0001",
            "pose_id": "P001_front",
            "portrait_text": "小麦色肌肤，方圆脸",
            "costume_text": "藏青工装",
            "pose_text": "双手抱胸",
            "modifier_fragments": "• 拍摄视角：微仰拍\n• 场景环境：戈壁滩",
            "prompt_override": OVERRIDE,
            "dry_run": True,
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["prompt"] == OVERRIDE
    assert body["prompt_raw"] == OVERRIDE
    for text in ("小麦色肌肤", "方圆脸", "藏青工装", "双手抱胸", "微仰拍", "戈壁滩"):
        assert text not in body["prompt"], "文本字段在手动模式不得进入提示词"


def test_bare_mode_with_costume_text_is_allowed_in_manual_mode(api, recipe_env, captured):
    """bare + 服装文本：自动模式 400；手动模式文本不参与，正常通过。"""
    _use_negative_effective_workflow(recipe_env)
    payload = {
        "pose_id": "P001_front",
        "body_mode": "bare",
        "costume_text": "米色风衣",
        "prompt_override": OVERRIDE,
        "negative_prompt": USER_NEGATIVE,
        "dry_run": True,
    }

    resp = _post(api, payload)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["manual_override"] is True
    assert body["body_mode"] == "bare"
    assert body["prompt"] == OVERRIDE


# ---------------------------------------------------------------------------
# 4. API 真实提交
# ---------------------------------------------------------------------------


def test_real_submit_passes_skip_compile_and_override(api, recipe_env, captured):
    """真实提交：payload 带 skip_compile=true 与 prompt=override，响应 prompt 为原文。"""
    _use_negative_effective_workflow(recipe_env)

    resp = _post(
        api,
        {
            **THREE_BODY,
            "dry_run": False,
            "prompt_override": OVERRIDE,
            "negative_prompt": USER_NEGATIVE,
        },
    )

    assert resp.status_code == 200, resp.text
    assert len(captured) == 1
    req = captured[0]
    assert req.dry_run is False
    assert req.skip_compile is True
    assert req.prompt == OVERRIDE
    assert req.negative_prompt == USER_NEGATIVE

    body = resp.json()
    assert body["prompt"] == OVERRIDE
    assert body["manual_override"] is True


# ---------------------------------------------------------------------------
# 5. 无 prompt_override：P1/P2 自动模式回归
# ---------------------------------------------------------------------------


def test_auto_mode_without_override_is_unchanged(api, recipe_env, captured):
    """无 prompt_override：仍由碎片渲染提示词，响应不含 manual_override。"""
    resp = _post(api, THREE_BODY)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "manual_override" not in body
    assert "图2中的人物" in body["prompt"]
    assert "图3中展示的整套服装" in body["prompt"]
    assert captured[0].skip_compile is False
    assert captured[0].prompt == body["prompt_raw"]


# ---------------------------------------------------------------------------
# 6. 三槽全无图 + prompt_override
# ---------------------------------------------------------------------------


def test_manual_override_without_any_image_is_still_400(api, recipe_env, captured):
    """文本不参与计数：三槽全无图时仍必须 400。"""
    resp = _post(
        api,
        {
            "prompt_override": OVERRIDE,
            "negative_prompt": USER_NEGATIVE,
            "dry_run": True,
        },
    )

    assert resp.status_code == 400
    assert "请至少选择一个参考图" in resp.json()["detail"]
    assert not captured