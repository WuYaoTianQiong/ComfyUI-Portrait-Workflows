"""AI 参考图库 · 单条转提示词（M4）契约。

覆盖：类型映射、正文格式、note/tags 来源标记、按正文精确去重、
NSFW 可见性、外链条目只转文字、未知库/空 id 的错误。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import settings
from app.models import Prompt
from app.services import reference_library as rl


def _write_json(path: Path, payload: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


POSE_ITEMS = [
    {
        "id": "P001_front",
        "体系": "日常",
        "姿势编号": "P001",
        "分类": "站姿",
        "姿势名称": "正面站姿",
        "角度": "正面",
        "缩略图": "thumbs/P001_front.jpg",
        "原图": "img/P001_front.png",
        "检索": "P001_front 日常 站姿 正面站姿 正面",
    },
    {
        "id": "full_sexy_P002_front",
        "体系": "全身单人・性感系",
        "姿势编号": "P002",
        "分类": "站姿",
        "姿势名称": "S形站姿",
        "角度": "正面",
        "缩略图": "thumbs/full_sexy_P002_front.jpg",
        "原图": "img/full_sexy_P002_front.png",
        "检索": "full_sexy_P002_front 全身单人・性感系 站姿 S形站姿 正面",
    },
]

COSTUME_ITEMS = [
    {
        "id": "SPR-0001",
        "分类": "春季穿搭",
        "服装名称": "象牙白针织衫",
        "标签": ["针织", "针织"],
        "关键词": "knit",
        "缩略图": "thumbs/costume/SPR-0001.webp",
        "原图": "img/costume/SPR-0001.webp",
        "检索": "SPR-0001 春季穿搭 象牙白针织衫 针织 knit",
    },
]

PORTRAIT_ITEMS = [
    {
        "id": "p1",
        "分区": "正脸参考",
        "发长": "短发",
        "发型名称": "标准基础款",
        "标题": "短发・标准款",
        "缩略图": "thumbs/portrait/p1.webp",
        "原图": "img/portrait/p1.webp",
        "检索": "p1 正脸参考 短发 标准基础款",
    }
]

ANIME_ITEMS = [
    {
        "id": "charadb-O001",
        "一级分类": "二次元",
        "分类": "制服与校园风",
        "服装名称": "藏青水手服",
        "日文名称": "セーラー服(紺)",
        "标签": ["水手服"],
        "关键词": "serafuku",
        "缩略图": "https://example.invalid/thumb/O001.webp",
        "原图": "https://example.invalid/img/O001.jpg",
        "敏感": False,
        "检索": "charadb-O001 藏青水手服 制服与校园风",
    }
]


@pytest.fixture()
def ref_root(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "ai-pose-gallery-zh"
    data = root / "data"
    _write_json(data / "pose-zh.json", POSE_ITEMS)
    _write_json(data / "costume-zh.json", COSTUME_ITEMS)
    _write_json(data / "portrait-zh.json", PORTRAIT_ITEMS)
    _write_json(data / "costume-anime-zh.json", ANIME_ITEMS)

    for rel in (
        "thumbs/P001_front.jpg",
        "img/P001_front.png",
        "thumbs/costume/SPR-0001.webp",
        "img/costume/SPR-0001.webp",
        "thumbs/portrait/p1.webp",
        "img/portrait/p1.webp",
    ):
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"img")

    monkeypatch.setattr(settings, "reference_root", root)
    monkeypatch.setattr(settings, "pose_extra_dir", None)
    monkeypatch.setattr(settings, "costume_character_dir", None)
    monkeypatch.setattr(settings, "reference_allow_nsfw", False)
    rl.clear_cache()
    yield root
    rl.clear_cache()


def _post(api, library: str, item_id: str):
    return api.post("/api/reference/fragments", json={"library": library, "item_id": item_id})


def test_pose_fragment_uses_standard_type_and_body(api, ref_root):
    resp = _post(api, "pose", "P001_front")
    assert resp.status_code == 200
    body = resp.json()
    assert body["dedup"] is False
    assert body["fragment_type"] == "姿态动作"
    assert body["prompt"] == "【姿态动作】\n正面站姿，正面"
    assert body["note"] == "ref:pose/P001_front"
    assert body["tags"] == "参考库,姿势库"

    row = Prompt.get_by_id(body["id"])
    assert row.prompt == body["prompt"]
    assert row.note == body["note"]
    assert row.tags == "参考库,姿势库"
    assert row.name == "正面站姿"


def test_costume_and_portrait_map_to_standard_types(api, ref_root):
    costume = _post(api, "costume", "SPR-0001").json()
    assert costume["fragment_type"] == "人物服饰"
    # 服装名称本身就是整套搭配描述，正文不再叠分类/标签
    assert costume["prompt"] == "【人物服饰】\n象牙白针织衫"
    assert costume["note"] == "ref:costume/SPR-0001"

    portrait = _post(api, "portrait", "p1").json()
    assert portrait["fragment_type"] == "人物面部"
    assert portrait["prompt"] == "【人物面部】\n短发・标准款"
    assert portrait["note"] == "ref:portrait/p1"


def test_duplicate_is_deduplicated_by_exact_body(api, ref_root):
    first = _post(api, "pose", "P001_front").json()
    second = _post(api, "pose", "P001_front").json()
    assert second["dedup"] is True
    assert second["id"] == first["id"]
    assert Prompt.select().count() == 1


def test_remote_anime_item_only_converts_text(api, ref_root):
    resp = _post(api, "costume-anime", "charadb-O001")
    assert resp.status_code == 200
    body = resp.json()
    assert body["fragment_type"] == "人物服饰"
    assert body["prompt"] == "【人物服饰】\n藏青水手服，セーラー服(紺)"
    # 只写文字，不落外链 URL
    assert "http" not in body["prompt"]
    assert body["tags"] == "参考库,外链服装"


def test_nsfw_item_is_hidden_when_gate_closed(api, ref_root):
    resp = _post(api, "pose", "full_sexy_P002_front")
    assert resp.status_code == 404
    assert Prompt.select().count() == 0


def test_unknown_library_and_empty_id(api, ref_root):
    assert _post(api, "nope", "x").status_code == 404
    assert _post(api, "pose", "").status_code == 400
    assert Prompt.select().count() == 0