"""services.composition 的单元测试 —— 提示词解析的唯一实现。"""

from services.composition import (
    FRAGMENT_TYPES,
    classify,
    extract,
    is_structured,
    parse,
    render,
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
