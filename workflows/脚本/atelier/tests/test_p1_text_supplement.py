"""P1 补充态 / 修饰层 / 负向 / 安全模式契约（方案 2026-11-06 §4.2、§5.2-§5.4、§8 P1）。

P4（2026-11-06）补充门槛：路由层要求 image 模式 + 同槽文本必须显式开启
`*_supplement`；本文件的服务层渲染用例直接调 `build_recipe_prompt`，不受开关影响；
端点级用例同时覆盖「开关关闭 → 400」与「开关开启 → 补充」。

覆盖 7 组行为：
1. 三槽补充句：图片主句保留，文本只作「此外需体现」，不写「图N」；
2. 修饰层插在「补充要求」之前；无 suffix 时插在固定风格段之前；逐行去重；
3. 画风技术碎片抑制固定「风格」段（真人主体判定仍按 style）；
4. 拍摄视角碎片覆盖库条目 `pose.angle`，其余姿势文案保留；
5. 校验：槽无图 + 文本在 P2 起是**替代态**（§4.4，返回 200，见
   `test_p2_text_replacement.py`）；本文件保留 bare + 服装文本 400 与全无图 400；
6. dry-run 返回编译后正向与最终负向，与真实 inject_prompt 的 compile 逐字一致；
7. `/api/composer/fragments?safe_mode=1` 只看 tags/note，不误伤正文。

参考库夹具直接复用 `tests/test_reference_recipes.py`，避免两套参考库数据漂移。
"""
from __future__ import annotations

from app.services.prompt_compiler import compile_prompt
from app.services.recipe_prompt import (
    SUPPLEMENT_JOINER,
    RecipeEntry,
    build_recipe_prompt,
)
from app.services.workflow_parser import detect_workflow_caps, load_workflow
from test_reference_recipes import (  # noqa: F401 —— 复用既有 pytest 夹具
    THREE_BODY,
    _qwen21_workflow,
    _write_json,
    captured,
    recipe_env,
)

PORTRAIT = RecipeEntry(
    id="p1", name="短发・标准款", subtitle="标准基础款", facet="短发", angle="",
)
COSTUME = RecipeEntry(id="SPR-0001", name="象牙白针织衫")
POSE = RecipeEntry(id="P001_front", name="正面站姿", angle="正面")

FACE_TEXT = "冷白皮，鹅蛋脸，眼神柔和"
COSTUME_TEXT = "米色风衣，白色衬衫，细跟短靴"
POSE_TEXT = "重心落在右腿，右手扶腰，肩膀下沉"

MODIFIER = "• 拍摄视角：低角度仰拍\n• 场景环境：午后街角咖啡店\n• 光影色调：柔和侧逆光"


# ---------------------------------------------------------------------------
# 1. 补充态渲染
# ---------------------------------------------------------------------------


def test_hair_extra_uses_hair_specific_clause():
    """第 4 张在发型工作流里写「发型」主句，而不是通用附加元素。"""
    hair = RecipeEntry(id="", name="上传的发型参考")
    prompt = build_recipe_prompt(
        PORTRAIT,
        COSTUME,
        POSE,
        hair,
        extra_kind="hair",
        style="none",
        index_map={"portrait": 2, "costume": 3, "pose": 1, "extra": 4},
    )
    assert "• 发型：" in prompt
    assert "结合图2人物的发际线" in prompt
    assert "不要使用图4中人物的脸" in prompt
    assert "• 附加参考" not in prompt

    generic = build_recipe_prompt(
        PORTRAIT,
        COSTUME,
        POSE,
        RecipeEntry(id="x", name="配饰"),
        style="none",
        index_map={"portrait": 2, "costume": 3, "pose": 1, "extra": 4},
    )
    assert "• 附加参考" in generic


def test_supplement_clauses_are_appended_to_each_slot_master_sentence():
    prompt = build_recipe_prompt(
        PORTRAIT,
        COSTUME,
        POSE,
        style="none",
        portrait_text=FACE_TEXT,
        costume_text=COSTUME_TEXT,
        pose_text=POSE_TEXT,
    )

    # 三槽各自追加「；此外需体现：…。」，且图片主句未被覆盖
    for text in (FACE_TEXT, COSTUME_TEXT, POSE_TEXT):
        assert f"{SUPPLEMENT_JOINER}{text}。" in prompt
    assert "图1中的人物" in prompt
    assert "图2中展示的整套服装" in prompt
    assert "图3中人体模型" in prompt
    assert "保持其脸型、五官" in prompt

    # 补充分句不写「图N」：图号只对已填图片槽生效
    assert "此外需体现：图" not in prompt
    # 主句以句号结尾，追加时不能出现「。；」
    assert "。；" not in prompt


def test_no_text_means_no_supplement_clause():
    prompt = build_recipe_prompt(PORTRAIT, COSTUME, POSE, style="none")
    assert "此外需体现" not in prompt


# ---------------------------------------------------------------------------
# 2. 修饰层插入位置
# ---------------------------------------------------------------------------


def test_modifier_layer_sits_before_prompt_suffix():
    prompt = build_recipe_prompt(
        PORTRAIT,
        COSTUME,
        POSE,
        style="realistic",
        prompt_suffix="不要戴口罩",
        modifier_fragments=MODIFIER,
    )

    assert "• 场景环境：午后街角咖啡店" in prompt
    assert prompt.index("• 光影色调：柔和侧逆光") < prompt.index("• 补充要求：不要戴口罩")


def test_modifier_layer_sits_before_fixed_style_without_suffix():
    prompt = build_recipe_prompt(
        PORTRAIT, COSTUME, POSE, style="realistic", modifier_fragments=MODIFIER,
    )

    assert prompt.index("• 拍摄视角：低角度仰拍") < prompt.index("• 风格：")


def test_modifier_layer_dedupes_identical_lines():
    duplicated = "• 场景环境：街角\n• 场景环境：街角\n\n• 光影色调：柔光"
    prompt = build_recipe_prompt(
        PORTRAIT, COSTUME, POSE, style="none", modifier_fragments=duplicated,
    )

    assert prompt.count("• 场景环境：街角") == 1
    assert "• 光影色调：柔光" in prompt


# ---------------------------------------------------------------------------
# 3. 画风技术碎片与画风预设互斥
# ---------------------------------------------------------------------------


def test_art_style_fragment_suppresses_fixed_style_clause():
    prompt = build_recipe_prompt(
        PORTRAIT,
        COSTUME,
        POSE,
        style="realistic",
        modifier_fragments="• 画风技术：吉卜力动画风格，扁平上色",
    )

    assert "• 画风技术：吉卜力动画风格，扁平上色" in prompt
    assert "• 风格：" not in prompt
    # 画风碎片只替代「风格描述段」，不替代真人/非真人判定
    assert "真实人物照片" in prompt


def test_no_art_style_fragment_keeps_fixed_style_clause():
    prompt = build_recipe_prompt(PORTRAIT, COSTUME, POSE, style="realistic")
    assert "• 风格：" in prompt


# ---------------------------------------------------------------------------
# 4. 拍摄视角碎片覆盖库条目角度
# ---------------------------------------------------------------------------


def test_view_angle_fragment_overrides_pose_angle():
    prompt = build_recipe_prompt(
        PORTRAIT,
        COSTUME,
        POSE,
        style="none",
        modifier_fragments="• 拍摄视角：低角度仰拍",
    )

    assert "镜头角度：正面" not in prompt
    assert "低角度仰拍" in prompt
    # 其余姿势文案必须保留
    assert "不要军姿" in prompt
    assert "不要 T-pose" in prompt


def test_pose_angle_kept_without_view_angle_fragment():
    prompt = build_recipe_prompt(PORTRAIT, COSTUME, POSE, style="none")
    assert "镜头角度：正面" in prompt


# ---------------------------------------------------------------------------
# 5. 校验：替代态已开放（P2），保留仍必须 400 的两条
# ---------------------------------------------------------------------------


def test_text_without_slot_image_becomes_replacement_state(api, recipe_env, captured):
    """P2（§4.4）：槽无图 + 文本 = 替代态，返回 200 并渲染 §5.1 的文本主句。"""
    cases = [
        # 服装槽无图，但给了服装文本
        (
            {"portrait_id": "p1", "costume_text": COSTUME_TEXT},
            f"• 服装：人物穿着 {COSTUME_TEXT}",
        ),
        # 姿势槽无图，但给了姿势文本
        (
            {"portrait_id": "p1", "pose_text": POSE_TEXT},
            f"• 姿势：{POSE_TEXT}。",
        ),
        # 人像槽无图，但给了人像文本
        (
            {"costume_id": "SPR-0001", "pose_id": "P001_front", "portrait_text": FACE_TEXT},
            f"• 人物：一位 {FACE_TEXT}。",
        ),
    ]
    for payload, expected in cases:
        resp = api.post(
            "/api/reference/recipes", json={**payload, "dry_run": True},
        )
        assert resp.status_code == 200, f"{payload} 应 200，实际 {resp.status_code}：{resp.text}"
        assert expected in resp.json()["prompt_raw"], f"{payload} 缺少替代句：{expected}"

    # 三条都真的走了提交链路（dry_run），没有被旧校验拦下
    assert len(captured) == len(cases)


def test_bare_mode_rejects_costume_text(api, recipe_env, captured):
    """素体模式不穿衣服：服装文本同样自相矛盾，必须 400。"""
    resp = api.post(
        "/api/reference/recipes",
        json={
            "portrait_id": "p1",
            "body_mode": "bare",
            "costume_text": COSTUME_TEXT,
            "dry_run": True,
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "素体模式不能同时选择服装文本"
    assert not captured


def test_zero_images_with_text_is_still_400(api, recipe_env, captured):
    """全无图仍走现有 total==0 文案，不被文本校验抢走错误原因。"""
    resp = api.post(
        "/api/reference/recipes",
        json={"portrait_text": FACE_TEXT, "dry_run": True},
    )
    assert resp.status_code == 400
    assert "请至少选择一个参考图" in resp.json()["detail"]
    assert not captured


def test_image_and_text_require_supplement_flag(api, recipe_env, captured):
    """P4：图片槽 + 同槽文本默认不再静默补充，必须显式开启对应开关。"""
    cases = [
        ({"portrait_id": "p1", "portrait_text": FACE_TEXT}, "portrait_supplement"),
        ({"costume_id": "SPR-0001", "costume_text": COSTUME_TEXT}, "costume_supplement"),
        ({"pose_id": "P001_front", "pose_text": POSE_TEXT}, "pose_supplement"),
    ]
    for payload, field in cases:
        resp = api.post(
            "/api/reference/recipes", json={**payload, "dry_run": True},
        )
        assert resp.status_code == 400, f"{payload} 应 400，实际 {resp.status_code}：{resp.text}"
        assert field in resp.json()["detail"]
    assert not captured


def test_text_mode_ignores_supplement_flag(api, recipe_env, captured):
    """槽无图时文本是替代；此时 supplement 开关不改变语义，也不报告为生效补充。"""
    resp = api.post(
        "/api/reference/recipes",
        json={
            "portrait_id": "p1",
            "costume_text": COSTUME_TEXT,
            "costume_supplement": True,
            "dry_run": True,
        },
    )
    body = resp.json()
    assert resp.status_code == 200, resp.text
    assert f"• 服装：人物穿着 {COSTUME_TEXT}" in body["prompt_raw"]
    assert SUPPLEMENT_JOINER not in body["prompt_raw"]
    assert body["supplements"] == {"portrait": False, "costume": False, "pose": False}


def test_supplement_state_does_not_change_slots(api, recipe_env):
    """三槽有图 + 三槽文本：filled / 裁剪不变，补充分句进入原始提示词。"""
    resp = api.post(
        "/api/reference/recipes",
        json={
            "portrait_id": "p1",
            "costume_id": "SPR-0001",
            "pose_id": "P001_front",
            "portrait_text": FACE_TEXT,
            "costume_text": COSTUME_TEXT,
            "pose_text": POSE_TEXT,
            "portrait_supplement": True,
            "costume_supplement": True,
            "pose_supplement": True,
            "negative_prompt": "低质量",
            "dry_run": True,
        },
    )
    body = resp.json()
    assert resp.status_code == 200, resp.text
    assert body["input_count"] == 3
    assert body["supplements"] == {"portrait": True, "costume": True, "pose": True}
    assert [slot["source"] for slot in body["slots"]] == [
        "library", "library", "library", "empty",
    ]
    for text in (FACE_TEXT, COSTUME_TEXT, POSE_TEXT):
        assert f"{SUPPLEMENT_JOINER}{text}。" in body["prompt_raw"]
    # dry-run 返回编译后正向 + 最终负向；默认工作流没有采样器 → 负向不生效
    assert body["prompt"] != body["prompt_raw"]
    assert body["negative_effective"] is False
    assert body["negative_prompt"] == ""


# ---------------------------------------------------------------------------
# 6. dry-run 与真实提交同一份编译结果
# ---------------------------------------------------------------------------


def _negative_effective_workflow() -> dict:
    """默认 Qwen21 补一个 cfg=2.5 的 KSampler：负向来自 node8 → 负向真正生效。"""
    workflow = _qwen21_workflow()
    workflow["9"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": ["7", 0],
            "positive": ["8", 0],
            "negative": ["8", 1],
            "latent_image": ["8", 2],
            "cfg": 2.5,
            "seed": 1,
        },
    }
    return workflow


def test_dry_run_returns_compiled_prompt_matching_real_injection(api, recipe_env):
    studio = recipe_env["library_root"] / "图库专用工作流"
    workflow_name = "P1负向生效.api.json"
    _write_json(studio / workflow_name, _negative_effective_workflow())

    user_negative = "低质量, 水印"
    resp = api.post(
        "/api/reference/recipes",
        json={
            **THREE_BODY,
            "workflow": workflow_name,
            "negative_prompt": user_negative,
        },
    )
    body = resp.json()
    assert resp.status_code == 200, resp.text
    assert body["dry_run"] is True
    assert body["negative_effective"] is True

    # 正向已编译：文字/水印类否定被抽走并改写
    assert "画面中没有任何文字、标志或水印。" not in body["prompt"]
    assert "画面干净" in body["prompt"]
    # 最终负向 = 后端自动抽取 + 用户填写
    assert "低质量" in body["negative_prompt"]
    assert "水印" in body["negative_prompt"]

    # 与真实 inject_prompt 同源：按同一工作流能力再编译一遍，逐字对照
    api_wf = load_workflow(str(studio / workflow_name))
    effective = bool(detect_workflow_caps(api_wf).get("negative_effective"))
    compiled = compile_prompt(
        body["prompt_raw"], user_negative, negative_effective=effective,
    )
    assert body["prompt"] == compiled.positive
    assert body["negative_prompt"] == compiled.negative


# ---------------------------------------------------------------------------
# 7. 碎片池安全模式（启发式，只看 tags / note）
# ---------------------------------------------------------------------------


def _fragment_contents(payload: dict, fragment_type: str) -> set[str]:
    return {item["content"] for item in payload["grouped"].get(fragment_type, [])}


def test_fragments_safe_mode_filters_tags_and_note_only(api, seed_prompt):
    seed_prompt(name="常态面部", prompt="【人物面部】\n黑色长发")
    seed_prompt(name="标签敏感", prompt="【人物面部】\n红色短裙", tags="NSFW,私房")
    seed_prompt(name="备注敏感", prompt="【场景环境】\n浴室镜前", note="含裸露画面")
    # 正文出现敏感词但 tags/note 干净：安全模式不能误伤正文
    seed_prompt(name="正文含敏感词", prompt="【人物面部】\n裸体写真感")

    full = api.get(
        "/api/composer/fragments", params={"fragment_type": "人物面部"},
    ).json()
    safe = api.get(
        "/api/composer/fragments",
        params={"fragment_type": "人物面部", "safe_mode": "1"},
    ).json()

    assert {"黑色长发", "红色短裙", "裸体写真感"} <= _fragment_contents(full, "人物面部")
    assert _fragment_contents(safe, "人物面部") == {"黑色长发", "裸体写真感"}

    # note 命中同样整条隐藏
    safe_scene = api.get(
        "/api/composer/fragments",
        params={"fragment_type": "场景环境", "safe_mode": "1"},
    ).json()
    assert _fragment_contents(safe_scene, "场景环境") == set()