"""Prompt IR 影子解析：结构化往返、负向提取、行内标题告警。"""
from app.services.prompt_ir import parse_prompt, render_prompt, shadow_report


def test_canonical_text_roundtrips_without_issues():
    text = "【人物面部】\n黑色长发\n\n【人物服饰】\n白色衬衫"
    doc = parse_prompt(text)

    assert doc.fragment_types == ["人物面部", "人物服饰"]
    assert render_prompt(doc) == text
    assert shadow_report(text)["issues"] == []


def test_negative_section_is_extracted_and_kept_for_render():
    text = "【人物面部】\n黑色长发\n\n【避免】\n错字、乱码"
    doc = parse_prompt(text)

    assert doc.negative_terms == ["错字", "乱码"]
    assert [segment.kind for segment in doc.segments] == ["fragment", "negative"]
    assert render_prompt(doc) == text


def test_inline_separator_is_classified_as_safe_whitespace():
    """库里的 `【类型】正文` 行内写法只差一个分隔符，不算结构丢失。"""
    report = shadow_report("【人物面部】黑色长发")

    assert report["whitespace_only"] is True
    assert any("可安全归一" in issue for issue in report["issues"])


def test_prose_before_first_header_is_reported():
    text = "自由描述\n\n【人物面部】\n黑色长发"
    report = shadow_report(text)

    assert report["issues"]
    assert "未标记正文" in report["issues"][0]
    doc = parse_prompt(text)
    assert doc.prose == "自由描述"
    assert render_prompt(doc) == text


def test_inline_header_inside_content_is_reported():
    text = "【人物面部】黑色长发【人物服饰】白衬衫"
    report = shadow_report(text)

    assert any("行内" in issue for issue in report["issues"])


def test_empty_text_is_empty_doc():
    doc = parse_prompt("")
    assert doc.segments == []
    assert doc.negative_terms == []
    assert render_prompt(doc) == ""
