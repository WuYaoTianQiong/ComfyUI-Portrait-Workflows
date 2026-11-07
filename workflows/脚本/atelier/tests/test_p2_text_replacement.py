"""P2 替代态：槽无图 + 文本成为主描述（方案 2026-11-06 §3 C3、§4.4、§5.1、§8 P2）。

覆盖 7 组行为：
1. 人像替代（C3-2）：`faceless` 不得在 `portrait_text` 非空时触发，不写「无脸展示」；
2. 服装替代（C3-1）：服装文本存在时不再自动切 bare，`body_mode='costume'`；
3. 姿势替代（C3-3 前置）：文本句替换「严格复现图N」，双人语义不再由文本触发；
4. 三槽全文本无图 → 400（文本不计入 `filled`）；
5. 图号只引用真实 `image_N`：文本槽不占图号，不出现不存在的图号；
6. 图片 + 文本仍是补充态（回归 P1「此外需体现」）；
7. bare + 服装文本 → 400。

夹具复用 `tests/test_reference_recipes.py`（参考库 JSON、最小 Qwen21 工作流、
`captured` 截获提交），避免两套数据漂移。
"""
from __future__ import annotations

from app.services.recipe_prompt import (
    SUPPLEMENT_JOINER,
    RecipeEntry,
    build_recipe_prompt,
)
from test_reference_recipes import (  # noqa: F401 —— 复用既有 pytest 夹具
    THREE_BODY,
    captured,
    recipe_env,
)

PORTRAIT = RecipeEntry(
    id="p1", name="短发・标准款", subtitle="标准基础款", facet="短发", angle="",
)
COSTUME = RecipeEntry(id="SPR-0001", name="象牙白针织衫")
POSE = RecipeEntry(id="P001_front", name="正面站姿", angle="正面")
PAIR = RecipeEntry(id="pair_001", name="双人并肩站姿", angle="正面")

FACE_TEXT = "冷白皮，鹅蛋脸，眼神柔和"
COSTUME_TEXT = "米色风衣，白色衬衫，细跟短靴"
POSE_TEXT = "重心落在右腿，右手扶腰，肩膀下沉"

PORTRAIT_REPLACEMENT = f"• 人物：一位 {FACE_TEXT}。"
COSTUME_REPLACEMENT = (
    f"• 服装：人物穿着 {COSTUME_TEXT}，颜色、款式、面料与配饰以文字描述为准。"
)
POSE_REPLACEMENT = (
    f"• 姿势：{POSE_TEXT}。保持重心、胯部朝向、肩线、手臂位置与膝盖弯曲的自然关系；"
    "不要军姿，不要 T-pose，不要双脚并拢。"
)


def _post(api, payload: dict):
    return api.post(
        "/api/reference/recipes", json={**payload, "dry_run": True},
    )


def _slot_sources(body: dict) -> list[str]:
    return [slot["source"] for slot in body["slots"]]


# ---------------------------------------------------------------------------
# 1. 人像替代（C3-2：不能误判无脸）
# ---------------------------------------------------------------------------


def test_portrait_text_replaces_missing_portrait_image(api, recipe_env, captured):
    """人像文本 + 服装图 + 姿势图：写文本人物句，不触发无脸展示。"""
    resp = _post(
        api,
        {
            "costume_id": "SPR-0001",
            "pose_id": "P001_front",
            "portrait_text": FACE_TEXT,
        },
    )
    body = resp.json()
    assert resp.status_code == 200, resp.text

    raw = body["prompt_raw"]
    assert PORTRAIT_REPLACEMENT in raw
    # 非 bare：只声明肤色与质感，不追加素体措辞
    assert "肤色与质感按风格要求呈现。" in raw
    assert "中性素体展示" not in raw
    # C3-2：人像文本就是「脸」，绝不能抹掉
    assert "无脸展示" not in raw
    assert "图2中的人物" not in raw
    assert "保持其脸型、五官" not in raw
    assert "人物穿搭展示图" not in raw
    # 人像槽在溯源里仍是空槽（文本不计入 filled）
    assert _slot_sources(body) == ["empty", "library", "library", "empty"]
    assert (body["body_mode"], body["body_mode_auto"]) == ("costume", False)
    assert len(captured) == 1


def test_faceless_still_triggers_when_portrait_is_absent_and_silent():
    """回归：既无 image1、又无文本时，无脸展示仍要生效。"""
    prompt = build_recipe_prompt(None, COSTUME, POSE, style="none")
    assert "无脸展示" in prompt
    assert "• 人物：" not in prompt


def test_portrait_text_in_bare_mode_declares_neutral_display():
    """人像替代 + bare：追加中性素体展示，不用「肤色句」单独收尾。"""
    prompt = build_recipe_prompt(
        None, None, POSE, style="none", body_mode="bare", portrait_text=FACE_TEXT,
    )
    assert PORTRAIT_REPLACEMENT in prompt
    assert "中性素体展示，肤色与质感按风格要求呈现。" in prompt
    assert "无脸展示" not in prompt


# ---------------------------------------------------------------------------
# 2. 服装替代（C3-1：文本不能被当成空槽）
# ---------------------------------------------------------------------------


def test_costume_text_is_not_auto_downgraded_to_bare(api, recipe_env, captured):
    """服装文本 + 人像图 + 姿势图：保持 costume，文本即服装真源。"""
    resp = _post(
        api,
        {
            "portrait_id": "p1",
            "pose_id": "P001_front",
            "costume_text": COSTUME_TEXT,
        },
    )
    body = resp.json()
    assert resp.status_code == 200, resp.text

    # C3-1：服装文本算「有服装描述」，不能自动切素体
    assert (body["body_mode"], body["body_mode_auto"]) == ("costume", False)
    raw = body["prompt_raw"]
    assert COSTUME_REPLACEMENT in raw
    assert "素体展示" not in raw
    assert "不穿任何服装" not in raw
    assert "图3中展示的整套服装" not in raw
    assert _slot_sources(body) == ["library", "empty", "library", "empty"]


def test_text_costume_leaves_pose_wear_empty():
    """`costume_idx=0`：姿势段不能再写「穿着图0的服装」。"""
    prompt = build_recipe_prompt(
        PORTRAIT, None, POSE, style="realistic", costume_text=COSTUME_TEXT,
    )
    assert COSTUME_REPLACEMENT in prompt
    assert "穿着图" not in prompt
    assert "只是动作示意，最终画面中的人物是真人，皮肤真实自然。" in prompt


# ---------------------------------------------------------------------------
# 3. 姿势替代
# ---------------------------------------------------------------------------


def test_pose_text_replaces_missing_pose_image(api, recipe_env, captured):
    """姿势文本 + 人像图 + 服装图：不写「严格复现图N」，否定条款保留。"""
    resp = _post(
        api,
        {
            "portrait_id": "p1",
            "costume_id": "SPR-0001",
            "pose_text": POSE_TEXT,
        },
    )
    body = resp.json()
    assert resp.status_code == 200, resp.text

    raw = body["prompt_raw"]
    assert POSE_REPLACEMENT in raw
    assert "严格复现图" not in raw
    assert "只是动作示意" not in raw
    assert "不要军姿" in raw and "不要 T-pose" in raw
    assert _slot_sources(body) == ["library", "library", "empty", "empty"]


def test_pose_text_does_not_trigger_pair_wording():
    """`is_pair` 只由姿势图决定：姿势文本不可能带出双人条款。"""
    prompt = build_recipe_prompt(
        PORTRAIT, COSTUME, None, style="none", pose_text=POSE_TEXT,
    )
    assert POSE_REPLACEMENT in prompt
    assert "双人要求" not in prompt

    # 对照：保留 pair 姿势图时条款仍在（回归，说明没有把 is_pair 一并改坏）
    pair_prompt = build_recipe_prompt(PORTRAIT, COSTUME, PAIR, style="none")
    assert "双人要求" in pair_prompt


def test_pair_composition_triggers_wording_for_psl_ids():
    """pose-studio-lite 的 `psl-*` 双人姿势没有 pair 前缀，必须靠 composition 识别。"""
    psl_pair = RecipeEntry(
        id="psl-D026", name="双臂前伸扶腰", composition="pair",
    )
    prompt = build_recipe_prompt(PORTRAIT, COSTUME, psl_pair, style="none")
    assert "双人要求" in prompt
    assert "恰好两位成年女性" in prompt
    assert "禁止合并成一个人" in prompt


def test_person_b_text_adds_distinct_b_clause():
    """B 文字设定要单独成段，并明确 B 不复用 A 的脸。"""
    psl_pair = RecipeEntry(
        id="psl-D026", name="双臂前伸扶腰", composition="pair",
    )
    prompt = build_recipe_prompt(
        PORTRAIT,
        COSTUME,
        psl_pair,
        style="none",
        person_b_text="金色齐肩短发，酒红色西装外套，黑色阔腿长裤",
    )
    assert "• 人物B（文字设定）：金色齐肩短发，酒红色西装外套，黑色阔腿长裤。" in prompt
    assert "不要复用人物A的脸" in prompt
    assert "同色系素色简化款" not in prompt


def test_person_b_text_ignored_for_single_pose():
    prompt = build_recipe_prompt(
        PORTRAIT,
        COSTUME,
        POSE,
        style="none",
        person_b_text="金色齐肩短发",
    )
    assert "人物B" not in prompt


def test_person_b_fragment_fields_join_b_clause_in_fixed_order():
    """v1.5：B 的面部/身材、服饰、自由补充按固定顺序并入同一个 B 条款。"""
    psl_pair = RecipeEntry(
        id="psl-D026", name="双臂前伸扶腰", composition="pair",
    )
    prompt = build_recipe_prompt(
        PORTRAIT,
        COSTUME,
        psl_pair,
        style="none",
        person_b_portrait_text="冷白皮，鹅蛋脸，深棕高马尾",
        person_b_costume_text="浅蓝衬衫，米色长裙",
        person_b_text="棕色乐福鞋，年龄与人物A相近",
    )
    assert (
        "• 人物B（文字设定）：冷白皮，鹅蛋脸，深棕高马尾；"
        "浅蓝衬衫，米色长裙；棕色乐福鞋，年龄与人物A相近。"
    ) in prompt
    assert "不要复用人物A的脸" in prompt


def test_person_b_fragment_fields_ignored_for_single_pose():
    """单人姿势下 B 碎片同样完全忽略，避免把 B 描述混进单人画面。"""
    prompt = build_recipe_prompt(
        PORTRAIT,
        COSTUME,
        POSE,
        style="none",
        person_b_portrait_text="冷白皮，鹅蛋脸",
        person_b_costume_text="浅蓝衬衫，米色长裙",
    )
    assert "人物B" not in prompt


B_IMAGE = RecipeEntry(id="f000fa12e8d", name="人物B参考")


def test_person_b_image_uses_image_for_face_and_keeps_only_costume_text():
    """v2-A：第 4 槽 = 人物B身份图时，B 的脸/发型以图为准，文字只保留服装/年龄。"""
    psl_pair = RecipeEntry(
        id="psl-D026", name="双臂前伸扶腰", composition="pair",
    )
    prompt = build_recipe_prompt(
        PORTRAIT,
        COSTUME,
        psl_pair,
        extra=B_IMAGE,
        extra_kind="person_b",
        style="none",
        person_b_portrait_text="冷白皮，鹅蛋脸，深棕高马尾",
        person_b_costume_text="浅蓝衬衫，米色长裙",
        person_b_text="棕色乐福鞋",
    )
    # 双人主句按图4取脸与发型；B 面容文字被图像取代
    assert "人物B按图4的脸型、发型与下方文字设定" in prompt
    assert "• 人物B（服装/年龄文字设定）：浅蓝衬衫，米色长裙；棕色乐福鞋。" in prompt
    assert "冷白皮，鹅蛋脸，深棕高马尾" not in prompt
    # A 的条款逐字不变
    assert (
        "人物A：脸型、五官、发型严格沿用图1中的人物，"
        "穿图2中展示的整套服装与配饰"
    ) in prompt
    # 图像参考条款只服务 B，并明确禁止回流到 A
    assert "• 人物B（图像参考）：图4是人物B的脸型与发型参考" in prompt
    assert "图4的脸与发型绝对不要用于人物A" in prompt


def test_person_b_image_ignored_for_single_pose():
    """单人姿势下第 4 槽仍按普通附加参考，不写任何 B 条款。"""
    prompt = build_recipe_prompt(
        PORTRAIT,
        COSTUME,
        POSE,
        extra=B_IMAGE,
        extra_kind="person_b",
        style="none",
        person_b_text="金色齐肩短发",
    )
    assert "人物B（图像参考）" not in prompt
    assert "人物B（服装/年龄文字设定）" not in prompt
    assert "人物B" not in prompt


def test_only_changing_b_keeps_a_prompt_identical():
    """隔离回归：只改 B 碎片时，A 的提示词（含双人要求前半段）必须逐字不变。"""
    psl_pair = RecipeEntry(
        id="psl-D026", name="双臂前伸扶腰", composition="pair",
    )
    base = dict(portrait=PORTRAIT, costume=COSTUME, pose=psl_pair, style="none")
    first = build_recipe_prompt(
        **base,
        person_b_portrait_text="冷白皮，鹅蛋脸",
        person_b_costume_text="浅蓝衬衫，米色长裙",
    )
    second = build_recipe_prompt(
        **base,
        person_b_portrait_text="小麦色皮肤，圆脸，金色短发",
        person_b_costume_text="酒红西装，黑色阔腿裤",
    )
    # B 条款之前的所有内容（人物A条款 + 双人要求）完全一致
    assert first.split("• 人物B（文字设定）")[0] == second.split("• 人物B（文字设定）")[0]
    assert "冷白皮，鹅蛋脸；浅蓝衬衫，米色长裙" in first
    assert "小麦色皮肤，圆脸，金色短发；酒红西装，黑色阔腿裤" in second


# ---------------------------------------------------------------------------
# 4. 三槽全文本无图 → 400（C1：至少留 1 张图）
# ---------------------------------------------------------------------------


def test_three_text_slots_without_any_image_is_400(api, recipe_env, captured):
    """文本不计入 filled：三槽全文本等价 0 图，仍走 total==0 文案。"""
    resp = _post(
        api,
        {
            "portrait_text": FACE_TEXT,
            "costume_text": COSTUME_TEXT,
            "pose_text": POSE_TEXT,
        },
    )
    assert resp.status_code == 400
    assert "请至少选择一个参考图" in resp.json()["detail"]
    assert not captured


def test_all_text_prompt_has_no_figure_number():
    """纯文本提示词：三槽都是文本句，不写任何「图N」（路由器会先 400，这里锁渲染）。"""
    prompt = build_recipe_prompt(
        None,
        None,
        None,
        style="none",
        portrait_text=FACE_TEXT,
        costume_text=COSTUME_TEXT,
        pose_text=POSE_TEXT,
    )
    for number in ("图1", "图2", "图3"):
        assert number not in prompt, f"文本槽不应写图号：{number}"
    assert PORTRAIT_REPLACEMENT in prompt
    assert COSTUME_REPLACEMENT in prompt
    assert POSE_REPLACEMENT in prompt
    # 顺序固定 人像 → 服装 → 姿势
    assert prompt.index(PORTRAIT_REPLACEMENT) < prompt.index(COSTUME_REPLACEMENT)
    assert prompt.index(COSTUME_REPLACEMENT) < prompt.index(POSE_REPLACEMENT)


def test_replacement_text_normalizes_period_semicolon():
    """多碎片拼接留下的「。；」在渲染层归一为「；」，避免提示词脏标点。"""
    prompt = build_recipe_prompt(
        None,
        None,
        POSE,
        style="none",
        portrait_text="圆脸。；身形纤细。",
    )
    assert "。；" not in prompt
    assert "圆脸；身形纤细" in prompt


# ---------------------------------------------------------------------------
# 5. 图号：只引用真实 image_N
# ---------------------------------------------------------------------------


def test_only_real_portrait_figure_number_is_referenced(api, recipe_env, captured):
    """人像图 + 服装文本 + 姿势文本：只写真实图号 image_2，不出现图1/图3。"""
    resp = _post(
        api,
        {
            "portrait_id": "p1",
            "costume_text": COSTUME_TEXT,
            "pose_text": POSE_TEXT,
        },
    )
    body = resp.json()
    assert resp.status_code == 200, resp.text

    raw = body["prompt_raw"]
    assert "图2中的人物" in raw
    assert "根据提供的 1 张参考图" in raw
    for missing in ("图1", "图3"):
        assert missing not in raw, f"提示词引用了不存在的图号：{missing}"
    assert body["input_count"] == 3
    assert len(captured) == 1


# ---------------------------------------------------------------------------
# 6. 图片 + 文本：仍是补充态（P1 回归）
# ---------------------------------------------------------------------------


def test_image_with_text_still_uses_supplement_clause(api, recipe_env, captured):
    """三槽有图 + 三槽文本：主句保留，仍是「；此外需体现」，不走替代分支。"""
    resp = _post(
        api,
        {
            **THREE_BODY,
            "portrait_text": FACE_TEXT,
            "costume_text": COSTUME_TEXT,
            "pose_text": POSE_TEXT,
            "portrait_supplement": True,
            "costume_supplement": True,
            "pose_supplement": True,
        },
    )
    body = resp.json()
    assert resp.status_code == 200, resp.text

    raw = body["prompt_raw"]
    for text in (FACE_TEXT, COSTUME_TEXT, POSE_TEXT):
        assert f"{SUPPLEMENT_JOINER}{text}。" in raw
    assert "图2中的人物" in raw
    assert "图3中展示的整套服装" in raw
    assert "严格复现图1" in raw
    # 替代句不能与补充句同时出现
    assert PORTRAIT_REPLACEMENT not in raw
    assert COSTUME_REPLACEMENT not in raw
    assert POSE_REPLACEMENT not in raw


# ---------------------------------------------------------------------------
# 7. bare + 服装文本 → 400
# ---------------------------------------------------------------------------


def test_bare_mode_with_costume_text_is_400(api, recipe_env, captured):
    resp = _post(
        api,
        {
            "portrait_id": "p1",
            "body_mode": "bare",
            "costume_text": COSTUME_TEXT,
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "素体模式不能同时选择服装文本"
    assert not captured