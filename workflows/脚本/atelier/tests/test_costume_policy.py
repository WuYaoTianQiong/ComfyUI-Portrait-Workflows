"""随机配方服装完整性 lint 的单元测试（P4 safety）。"""
from __future__ import annotations

import pytest

from app.services.costume_policy import (
    costume_covers_lower,
    costume_coverage_warning,
    has_explicit_content,
)


@pytest.mark.parametrize(
    "text",
    [
        "正装衬衫，搭配蓝色牛仔裤",
        "白色T恤，下面是一条黑色短裤",
        "浅蓝色连衣裙",
        "红色传统汉服",
        "白色浴衣风格和服长袍",
        "婚纱风格的深V蕾丝设计款",
        "雾蓝色针织上衣，冷白色高腰短裙",
    ],
)
def test_costume_with_lower_coverage(text):
    assert costume_covers_lower(text) is True
    assert costume_coverage_warning(text) == ""


@pytest.mark.parametrize(
    "text",
    [
        "",
        "正装衬衫",
        "oversized 白色T恤",
        "白色棉质吊带背心",
        "无可见的下装",
        "白色浴巾低缠在胸前",
        "白色浴袍，腰带松松系着",
        "全身赤裸，只戴着头上的黑色发带",
        "适合场景的服装",
        "下身只穿一条极简内裤",
        "只穿内裤",
    ],
)
def test_costume_without_lower_coverage(text):
    assert costume_covers_lower(text) is False
    if text:
        assert "服装描述不完整" in costume_coverage_warning(text)
    else:
        assert costume_coverage_warning(text) == ""


@pytest.mark.parametrize(
    "text",
    ["全身赤裸，只戴发带", "胸部裸露", "下体裸露", "情趣内衣", "裸体写真"],
)
def test_has_explicit_content_true(text):
    assert has_explicit_content(text) is True


@pytest.mark.parametrize(
    "text",
    ["裸色口红，自然肤色", "白色衬衫搭配牛仔裤", "唇色是裸粉色", ""],
)
def test_has_explicit_content_false(text):
    assert has_explicit_content(text) is False
