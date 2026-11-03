"""services.fragment_syntax 的单元测试 —— 提示词解析的唯一实现。"""

from app.services.fragment_syntax import (
    FRAGMENT_TYPES,
    classify,
    extract,
    is_structured,
    parse,
    render,
    replace_type,
    replace_types,
    split_marked,
    strip_headers,
    types_in,
    validate,
)

SAMPLE = """【人物面部】
silver hair, red eyes, delicate features

【姿态动作】
standing, hands in pockets

【场景环境】
neon-lit street at night"""


def test_parse_three_fragments():
    fragments = parse(SAMPLE)
    assert [f["type"] for f in fragments] == ["人物面部", "姿态动作", "场景环境"]
    assert fragments[0]["content"] == "silver hair, red eyes, delicate features"


def test_parse_empty_and_flat_text():
    assert parse("") == []
    assert parse(None) == []
    assert parse("just a flat prompt without headers") == []


def test_extract_specific_type():
    assert extract(SAMPLE, "姿态动作") == "standing, hands in pockets"
    assert extract(SAMPLE, "画风技术") == ""


def test_types_in_preserves_order():
    assert types_in(SAMPLE) == ["人物面部", "姿态动作", "场景环境"]


def test_strip_headers_keeps_only_content():
    stripped = strip_headers(SAMPLE)
    assert "【" not in stripped
    assert "silver hair" in stripped
    assert "neon-lit street" in stripped


def test_render_roundtrip():
    fragments = parse(SAMPLE)
    assert parse(render(fragments)) == fragments


def test_render_skips_incomplete_fragments():
    assert render([{"type": "人物面部", "content": ""}, {"type": "", "content": "x"}]) == ""


def test_classify_thresholds():
    assert classify("") is None
    assert classify("flat text") == "scattered"
    assert classify("【人物面部】\nx") == "single"
    assert classify(SAMPLE) == "single"
    four = "\n\n".join(f"【{t}】\ncontent" for t in FRAGMENT_TYPES[:4])
    assert classify(four) == "composite"


def test_is_structured():
    assert is_structured(SAMPLE) is True
    assert is_structured("flat") is False


def test_validate_reports_duplicate_and_unknown_type():
    problems = validate("【人物面部】\na\n【人物面部】\nb\n【不存在的类型】\nc")
    assert any("重复" in p for p in problems)
    assert any("标准 8 类" in p for p in problems)
    assert validate(SAMPLE) == []


# ---------------------------------------------------------------------------
# split_marked / replace_type —— 前端"智能分段"与"批量替换"依赖的语义
# ---------------------------------------------------------------------------


def test_split_marked_separates_marked_and_leftover():
    text = "【人物面部】\n黑色长发\n\n一个站在窗边的女孩"
    fragments, leftover = split_marked(text)
    assert fragments == [{"type": "人物面部", "content": "黑色长发"}]
    assert leftover == "一个站在窗边的女孩"


def test_split_marked_all_marked_leaves_no_leftover():
    fragments, leftover = split_marked("【人物面部】\n黑色长发\n\n【人物服饰】\n白色连衣裙")
    assert [f["type"] for f in fragments] == ["人物面部", "人物服饰"]
    assert leftover == ""


def test_split_marked_flat_text_is_all_leftover():
    fragments, leftover = split_marked("一整段没有分块的提示词")
    assert fragments == []
    assert leftover == "一整段没有分块的提示词"


def test_replace_type_keeps_other_blocks_verbatim():
    text = "【人物面部】黑色长发\n\n【人物身材】旧身材\n\n【场景环境】街道"
    replaced = replace_type(text, "人物身材", "统一身材")
    assert replaced == "【人物面部】黑色长发\n\n【人物身材】\n统一身材\n\n【场景环境】街道"
    assert "旧身材" not in replaced


def test_replace_type_returns_none_when_type_absent():
    assert replace_type("【人物面部】黑色长发", "人物身材", "新身材") is None
    assert replace_type("一整段没有分块的提示词", "人物身材", "新身材") is None
    assert replace_type("", "人物身材", "新身材") is None


# ---------------------------------------------------------------------------
# replace_types —— 「替换清单」一次改多个类型
# ---------------------------------------------------------------------------


def test_replace_types_applies_each_item_in_order():
    text = "【人物面部】黑色长发\n\n【人物身材】旧身材\n\n【场景环境】街道"
    replaced, outcomes = replace_types(text, [
        {"type": "人物面部", "content": "银发"},
        {"type": "人物身材", "content": "统一身材", "missing": "skip"},
    ])
    assert replaced == "【人物面部】\n银发\n\n【人物身材】\n统一身材\n\n【场景环境】街道"
    assert outcomes == [
        {"type": "人物面部", "old_content": "黑色长发", "action": "replaced"},
        {"type": "人物身材", "old_content": "旧身材", "action": "replaced"},
    ]


def test_replace_types_honours_missing_policy_per_item():
    replaced, outcomes = replace_types("【人物面部】黑色长发", [
        {"type": "人物服饰", "content": "统一服饰", "missing": "append"},
        {"type": "人物身材", "content": "纤细修长"},
    ])
    assert replaced == "【人物面部】黑色长发\n\n【人物服饰】\n统一服饰"
    assert [o["action"] for o in outcomes] == ["appended", "skipped"]


def test_replace_types_returns_none_when_nothing_applies():
    replaced, outcomes = replace_types("【人物面部】黑色长发", [
        {"type": "人物服饰", "content": "统一服饰"},
    ])
    assert replaced is None
    assert outcomes == [{"type": "人物服饰", "old_content": "", "action": "skipped"}]


def test_replace_types_ignores_empty_type_or_content():
    replaced, outcomes = replace_types("【人物面部】黑色长发", [
        {"type": "", "content": "x"},
        {"type": "人物服饰", "content": "  "},
    ])
    assert replaced is None
    assert outcomes == []
