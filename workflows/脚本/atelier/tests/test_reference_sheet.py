"""参考板导出契约（M5）：尺寸、标题条、外链/缺图拒绝、缓存命中。

所有用例都指向临时构造的迷你参考库与临时 uploads 目录，不读写本机真实素材；
`extra` 只接受 uploads 内文件，这条安全边界也在这里守住。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from app.config import settings
from app.services import reference_library as rl
from app.services import reference_sheet

POSE_ITEMS = [
    {
        "id": "P001_front",
        "体系": "日常",
        "姿势编号": "P001",
        "分类": "站姿",
        "姿势名称": "正面站姿",
        "角度": "正面",
        "缩略图": "thumbs/P001_front.png",
        "原图": "img/P001_front.png",
        "检索": "P001_front 日常 站姿 正面站姿 正面",
    },
    {
        "id": "P002_missing",
        "体系": "日常",
        "姿势编号": "P002",
        "分类": "站姿",
        "姿势名称": "缺原图站姿",
        "角度": "正面",
        "缩略图": "thumbs/P002_missing.png",
        "原图": "img/P002_missing.png",
        "检索": "P002_missing 日常 站姿 缺原图站姿 正面",
    },
]

COSTUME_ITEMS = [
    {
        "id": "SPR-0001",
        "分类": "春季穿搭",
        "服装名称": "象牙白针织衫",
        "标签": ["针织"],
        "关键词": "knit",
        "缩略图": "thumbs/costume/SPR-0001.png",
        "原图": "img/costume/SPR-0001.png",
        "检索": "SPR-0001 春季穿搭 象牙白针织衫 针织 knit",
    }
]

PORTRAIT_ITEMS = [
    {
        "id": "p1",
        "分区": "正脸参考",
        "发长": "短发",
        "发型名称": "标准基础款",
        "标题": "短发・标准款",
        "缩略图": "thumbs/portrait/p1.png",
        "原图": "img/portrait/p1.png",
        "检索": "p1 正脸参考 短发 标准基础款",
    }
]

ANIME_ITEMS = [
    {
        "id": "charadb-O001",
        "一级分类": "二次元",
        "分类": "制服与校园风",
        "服装名称": "藏青水手服",
        "标签": ["水手服"],
        "关键词": "serafuku",
        "缩略图": "https://example.invalid/thumb/O001.webp",
        "原图": "https://example.invalid/img/O001.jpg",
        "敏感": False,
        "检索": "charadb-O001 藏青水手服 制服与校园风",
    }
]


def _write_json(path: Path, payload: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_png(path: Path, color: tuple[int, int, int], size: tuple[int, int] = (320, 480)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="PNG")


@pytest.fixture()
def sheet_env(tmp_path: Path, monkeypatch):
    """临时参考库 + 临时 uploads：两者都在 pytest 的 tmp_path 下。"""
    ref_root = tmp_path / "ai-pose-gallery-zh"
    data = ref_root / "data"
    _write_json(data / "pose-zh.json", POSE_ITEMS)
    _write_json(data / "costume-zh.json", COSTUME_ITEMS)
    _write_json(data / "portrait-zh.json", PORTRAIT_ITEMS)
    _write_json(data / "costume-anime-zh.json", ANIME_ITEMS)

    _write_png(ref_root / "thumbs" / "P001_front.png", (180, 200, 220))
    _write_png(ref_root / "img" / "P001_front.png", (90, 140, 200))
    _write_png(ref_root / "thumbs" / "P002_missing.png", (200, 200, 200))
    # P002_missing 故意不写原图：验证缺图统一转 400
    _write_png(ref_root / "thumbs" / "costume" / "SPR-0001.png", (240, 210, 180))
    _write_png(ref_root / "img" / "costume" / "SPR-0001.png", (220, 190, 150))
    _write_png(ref_root / "thumbs" / "portrait" / "p1.png", (230, 200, 190))
    _write_png(ref_root / "img" / "portrait" / "p1.png", (210, 180, 170))

    library_root = tmp_path / "library"
    uploads = library_root / "uploads"
    extra = uploads / "uploaded.png"
    _write_png(extra, (40, 160, 120), size=(480, 320))

    monkeypatch.setattr(settings, "library_root", library_root)
    monkeypatch.setattr(settings, "reference_root", ref_root)
    monkeypatch.setattr(settings, "reference_allow_nsfw", False)
    rl.clear_cache()
    reference_sheet.clear_cache()
    yield {"root": ref_root, "uploads": uploads, "extra": extra}
    rl.clear_cache()
    reference_sheet.clear_cache()


def _sheet(api, **params):
    return api.get("/api/reference/sheet", params=params)


def _open_png(content: bytes) -> Image.Image:
    import io

    return Image.open(io.BytesIO(content)).convert("RGB")


def test_three_and_four_slots_are_fixed_1800x1200(api, sheet_env):
    three = _sheet(
        api,
        portrait="p1",
        costume="SPR-0001",
        pose="P001_front",
    )
    assert three.status_code == 200
    assert three.headers["content-type"] == "image/png"
    assert _open_png(three.content).size == (reference_sheet.SHEET_WIDTH, reference_sheet.SHEET_HEIGHT)

    four = _sheet(
        api,
        portrait="p1",
        costume="SPR-0001",
        pose="P001_front",
        extra=str(sheet_env["extra"]),
    )
    assert four.status_code == 200
    assert _open_png(four.content).size == (reference_sheet.SHEET_WIDTH, reference_sheet.SHEET_HEIGHT)
    assert four.content != three.content


def test_labels_zero_and_one_change_layout(api, sheet_env):
    params = {"portrait": "p1", "costume": "SPR-0001", "pose": "P001_front"}

    with_labels = _sheet(api, labels=1, **params)
    plain = _sheet(api, labels=0, **params)
    assert with_labels.status_code == plain.status_code == 200
    assert with_labels.content != plain.content

    # 左上角落在卡片背景：带标题条是深色卡片，纯图模式是浅色图区
    assert _open_png(with_labels.content).getpixel((reference_sheet.PADDING, reference_sheet.PADDING)) == reference_sheet.CARD_BG
    assert _open_png(plain.content).getpixel((reference_sheet.PADDING, reference_sheet.PADDING)) == reference_sheet.IMAGE_BG


def test_remote_item_is_rejected(api, sheet_env):
    # 外链服装只在 costume-anime 库里；参考板端点不暴露该库，直接验证服务层守卫
    with pytest.raises(reference_sheet.SheetError) as exc:
        reference_sheet._library_slot("服装", "costume-anime", "charadb-O001")
    assert exc.value.status_code == 400
    assert "外链" in exc.value.message

    # 不存在的条目同样是可读的 400，而不是 500
    with pytest.raises(reference_sheet.SheetError) as missing:
        reference_sheet._library_slot("姿势", "pose", "nope")
    assert missing.value.status_code == 400

    # 空选择不生成空画布
    assert _sheet(api).status_code == 400


def test_missing_library_image_is_400(api, sheet_env):
    resp = _sheet(api, pose="P002_missing")
    assert resp.status_code == 400
    assert "图片不可用" in resp.json()["detail"]


def test_extra_outside_uploads_is_rejected(api, sheet_env):
    outside = sheet_env["root"].parent / "outside.png"
    _write_png(outside, (10, 10, 10))

    absolute = _sheet(api, pose="P001_front", extra=str(outside))
    assert absolute.status_code == 400
    assert "上传目录" in absolute.json()["detail"]

    traversal = _sheet(api, pose="P001_front", extra="../outside.png")
    assert traversal.status_code == 400

    bad_type = sheet_env["uploads"] / "note.txt"
    bad_type.write_text("x", encoding="utf-8")
    assert _sheet(api, pose="P001_front", extra=str(bad_type)).status_code == 400

    missing = _sheet(api, pose="P001_front", extra=str(sheet_env["uploads"] / "nope.png"))
    assert missing.status_code == 400


def test_same_request_hits_cache_and_labels_do_not(api, sheet_env, monkeypatch):
    original = reference_sheet.render
    calls = {"n": 0}

    def counted(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(reference_sheet, "render", counted)
    params = {"portrait": "p1", "costume": "SPR-0001", "pose": "P001_front"}

    first = _sheet(api, **params)
    second = _sheet(api, **params)
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    assert calls["n"] == 1, "同参数的第二次请求应命中导出缓存"

    third = _sheet(api, labels=0, **params)
    assert third.status_code == 200
    assert calls["n"] == 2, "labels 不同属于不同版式，不能复用缓存"