"""AI 参考图库只读层契约：加载、检索、facet、NSFW、路径安全、深度图。

所有用例都指向临时构造的迷你参考库，不依赖本机真实素材；
另有一条「真实库规模」用例，只在存在上游目录时执行。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import settings
from app.services import reference_library as rl


def _write_json(path: Path, payload: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_bytes(path: Path, data: bytes = b"img") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


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
        "id": "P001_side",
        "体系": "日常",
        "姿势编号": "P001",
        "分类": "站姿",
        "姿势名称": "侧身站姿",
        "角度": "侧面",
        "缩略图": "thumbs/P001_side.jpg",
        "原图": "img/P001_side.png",
        "检索": "P001_side 日常 站姿 侧身站姿 侧面",
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
        "标签": ["针织"],
        "关键词": "knit",
        "缩略图": "thumbs/costume/SPR-0001.webp",
        "原图": "img/costume/SPR-0001.webp",
        "检索": "SPR-0001 春季穿搭 象牙白针织衫 针织 knit",
    },
    {
        "id": "UND-0001",
        "分类": "内衣・睡衣",
        "服装名称": "蕾丝睡裙",
        "标签": [],
        "关键词": "",
        "缩略图": "thumbs/costume/UND-0001.webp",
        "原图": "img/costume/UND-0001.webp",
        "检索": "UND-0001 内衣・睡衣 蕾丝睡裙",
    },
]

PORTRAIT_ITEMS = [
    {
        "id": "p1",
        "分区": "正脸参考",
        "发长": "短发",
        "发型名称": "标准基础款",
        "标题": "短发・标准款",
        "精选": True,
        "热门": True,
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

    _write_bytes(root / "thumbs" / "P001_front.jpg")
    _write_bytes(root / "img" / "P001_front.png")
    _write_bytes(root / "img" / "depth" / "P001_front.webp")
    # 仅正面有深度缩略图；P001_side 故意缺失，用于验证 DTO 回落 None
    _write_bytes(root / "thumbs" / "depth" / "P001_front.webp")
    _write_bytes(root / "thumbs" / "costume" / "SPR-0001.webp")
    _write_bytes(root / "img" / "costume" / "SPR-0001.webp")
    _write_bytes(root / "thumbs" / "portrait" / "p1.webp")
    _write_bytes(root / "img" / "portrait" / "p1.webp")

    monkeypatch.setattr(settings, "reference_root", root)
    monkeypatch.setattr(settings, "reference_allow_nsfw", False)
    monkeypatch.setattr(settings, "reference_page_size", 60)
    rl.clear_cache()
    yield root
    rl.clear_cache()


def test_default_reference_root_follows_library_root():
    assert settings.reference_root == settings.library_root / "ai-pose-gallery-zh"


def test_library_counts_and_availability(api, ref_root):
    resp = api.get("/api/reference/libraries")
    assert resp.status_code == 200
    stats = {row["library"]: row for row in resp.json()["libraries"]}
    assert set(stats) == {"pose", "costume", "portrait", "costume-anime"}
    assert stats["pose"]["total"] == 3
    assert stats["costume"]["total"] == 2
    assert stats["portrait"]["total"] == 1
    assert stats["costume-anime"]["total"] == 1
    assert stats["costume-anime"]["remote"] == 1
    assert stats["pose"]["local"] == 3
    assert stats["pose"]["available"] is True
    # 默认隐藏敏感分类：pose 可见 2 条、costume 可见 1 条
    assert stats["pose"]["visible"] == 2
    assert stats["costume"]["visible"] == 1


def test_search_matches_upstream_search_field(api, ref_root):
    pose = api.get("/api/reference/items", params={"library": "pose", "search": "P001"})
    assert pose.status_code == 200
    assert pose.json()["total"] == 2

    # 大小写不敏感
    lower = api.get("/api/reference/items", params={"library": "pose", "search": "p001"})
    assert lower.json()["total"] == 2

    costume = api.get("/api/reference/items", params={"library": "costume", "search": "针织"})
    assert costume.json()["total"] == 1
    assert costume.json()["items"][0]["id"] == "SPR-0001"


def test_facet_filter_and_facet_indexes(api, ref_root):
    stats = {row["library"]: row for row in api.get("/api/reference/libraries").json()["libraries"]}
    pose_groups = {row["value"]: row["count"] for row in stats["pose"]["groups"]}
    assert pose_groups == {"日常": 2}
    assert "全身单人・性感系" not in pose_groups

    costume_groups = {row["value"] for row in stats["costume"]["groups"]}
    assert costume_groups == {"春季穿搭"}

    portrait_facets = {row["value"] for row in stats["portrait"]["facets"]}
    assert portrait_facets == {"短发"}

    resp = api.get(
        "/api/reference/items",
        params={"library": "pose", "group": "日常", "facet": "站姿", "angle": "正面"},
    )
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["id"] == "P001_front"


def test_nsfw_filter_is_backend_gated(api, ref_root, monkeypatch):
    # 默认关闭：敏感条目不可见，nsfw=1 被忽略而不是 403
    default = api.get("/api/reference/items", params={"library": "pose", "nsfw": True})
    assert default.status_code == 200
    assert default.json()["total"] == 2
    assert all(not item["nsfw"] for item in default.json()["items"])

    hidden = api.get("/api/reference/items/pose/full_sexy_P002_front")
    assert hidden.status_code == 404

    # 开启总闸后 nsfw 参数才生效
    monkeypatch.setattr(settings, "reference_allow_nsfw", True)
    only_nsfw = api.get("/api/reference/items", params={"library": "pose", "nsfw": True})
    assert only_nsfw.json()["total"] == 1
    assert only_nsfw.json()["items"][0]["id"] == "full_sexy_P002_front"

    detail = api.get("/api/reference/items/pose/full_sexy_P002_front")
    assert detail.status_code == 200
    assert detail.json()["nsfw"] is True


def test_remote_items_use_upstream_urls_and_cannot_be_served(api, ref_root):
    resp = api.get("/api/reference/items", params={"library": "costume-anime"})
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["remote"] is True
    assert item["thumb_url"].startswith("https://example.invalid/")
    assert item["depth_url"] is None

    img = api.get("/api/reference/items/costume-anime/charadb-O001/image", params={"kind": "thumb"})
    assert img.status_code == 400


def test_image_endpoints_and_depth_derivation(api, ref_root):
    thumb = api.get("/api/reference/items/pose/P001_front/image", params={"kind": "thumb"})
    assert thumb.status_code == 200
    assert thumb.headers["content-type"].startswith("image/")

    image = api.get("/api/reference/items/pose/P001_front/image", params={"kind": "image"})
    assert image.status_code == 200

    # 深度图按 img/depth/{id}.webp 派生，存在即可读
    depth = api.get("/api/reference/items/pose/P001_front/image", params={"kind": "depth"})
    assert depth.status_code == 200

    # 同一个姿势的另一个角度没有深度文件 → 404，不退回 thumb
    missing_depth = api.get("/api/reference/items/pose/P001_side/image", params={"kind": "depth"})
    assert missing_depth.status_code == 404

    # costume 没有深度图
    wrong_library = api.get(
        "/api/reference/items/costume/SPR-0001/image", params={"kind": "depth"}
    )
    assert wrong_library.status_code == 404

    # 不支持的 kind
    bad_kind = api.get("/api/reference/items/pose/P001_front/image", params={"kind": "preview"})
    assert bad_kind.status_code == 404

    # 缺失的原图
    missing = api.get("/api/reference/items/pose/P001_side/image", params={"kind": "image"})
    assert missing.status_code == 404


def test_depth_thumb_url_and_endpoint(api, ref_root):
    front = api.get("/api/reference/items/pose/P001_front")
    assert front.status_code == 200
    assert front.json()["depth_thumb_url"].endswith("kind=depth_thumb")
    assert front.json()["depth_url"].endswith("kind=depth")

    side = api.get("/api/reference/items/pose/P001_side")
    assert side.status_code == 200
    assert side.json()["depth_thumb_url"] is None

    thumb = api.get("/api/reference/items/pose/P001_front/image", params={"kind": "depth_thumb"})
    assert thumb.status_code == 200
    # Windows 的 mimetypes 未必认识 .webp，media_type 兜底为 octet-stream，内容才是准绳
    assert thumb.content == b"img"

    # 非姿势库没有深度缩略图
    wrong_library = api.get(
        "/api/reference/items/costume/SPR-0001/image", params={"kind": "depth_thumb"}
    )
    assert wrong_library.status_code == 404

    # 缩略图文件缺失时不退回原深度图
    missing = api.get("/api/reference/items/pose/P001_side/image", params={"kind": "depth_thumb"})
    assert missing.status_code == 404


def test_libraries_expose_allow_nsfw(api, ref_root, monkeypatch):
    body = api.get("/api/reference/libraries").json()
    assert body["allow_nsfw"] is False
    assert all(row["allow_nsfw"] is False for row in body["libraries"])

    monkeypatch.setattr(settings, "reference_allow_nsfw", True)
    body = api.get("/api/reference/libraries").json()
    assert body["allow_nsfw"] is True
    assert all(row["allow_nsfw"] is True for row in body["libraries"])


def test_remote_item_without_urls_returns_none(api, tmp_path, monkeypatch):
    """外链库字段缺失时给 None：空串会让前端 `<img src="">` 去请求当前页面。"""
    root = tmp_path / "broken-gallery"
    _write_json(root / "data" / "costume-anime-zh.json", [{
        "id": "broken-1",
        "一级分类": "二次元",
        "分类": "制服",
        "服装名称": "缺图条目",
        "检索": "broken-1 缺图条目",
    }])
    for name in ("pose-zh.json", "costume-zh.json", "portrait-zh.json"):
        _write_json(root / "data" / name, [])
    monkeypatch.setattr(settings, "reference_root", root)
    rl.clear_cache()
    try:
        body = api.get("/api/reference/items/costume-anime/broken-1").json()
        assert body["remote"] is True
        assert body["thumb_url"] is None
        assert body["image_url"] is None
    finally:
        rl.clear_cache()


def test_remote_library_depth_is_404(api, ref_root):
    for kind in ("depth", "depth_thumb"):
        resp = api.get(
            "/api/reference/items/costume-anime/charadb-O001/image", params={"kind": kind}
        )
        assert resp.status_code == 404, kind


def test_system_status_exposes_reference_enabled(api, monkeypatch):
    """离线分支也要带开关：前端导航收起不依赖 ComfyUI 是否在线。"""
    from app.routers import system as system_router

    monkeypatch.setattr(settings, "reference_enabled", False)
    offline = api.get("/api/system/status").json()
    assert offline["comfyui"] == "offline"
    assert offline["reference_enabled"] is False

    monkeypatch.setattr(system_router, "is_online", lambda: True)
    monkeypatch.setattr(system_router, "fetch_queue", lambda: {})
    online = api.get("/api/system/status").json()
    assert online["comfyui"] == "online"
    assert online["reference_enabled"] is False


def test_path_traversal_is_rejected(api, ref_root):
    secret = ref_root.parent / "secret.png"
    secret.write_bytes(b"secret")

    payload = list(POSE_ITEMS) + [
        {
            "id": "evil",
            "体系": "日常",
            "姿势编号": "P999",
            "分类": "站姿",
            "姿势名称": "越界",
            "角度": "正面",
            "缩略图": "../secret.png",
            "原图": "C:/Windows/win.ini",
            "检索": "evil",
        }
    ]
    _write_json(ref_root / "data" / "pose-zh.json", payload)
    rl.clear_cache()

    traversal = api.get("/api/reference/items/pose/evil/image", params={"kind": "thumb"})
    assert traversal.status_code == 400

    absolute = api.get("/api/reference/items/pose/evil/image", params={"kind": "image"})
    assert absolute.status_code == 400


def test_pagination_shape(api, ref_root):
    resp = api.get("/api/reference/items", params={"library": "pose", "page": 2, "page_size": 1})
    body = resp.json()
    assert set(body) == {"items", "total", "page", "page_size"}
    assert body["total"] == 2
    assert body["page"] == 2
    assert body["page_size"] == 1
    assert len(body["items"]) == 1

    capped = api.get("/api/reference/items", params={"library": "pose", "page_size": 999})
    assert capped.json()["page_size"] == 200


def test_unknown_library_returns_404(api, ref_root):
    assert api.get("/api/reference/items", params={"library": "nope"}).status_code == 404
    assert api.get("/api/reference/items/nope/x").status_code == 404


def test_real_library_scale(monkeypatch):
    real_root = rl.reference_root()
    try:
        if not (real_root / "data" / "pose-zh.json").is_file():
            pytest.skip("本机没有上游参考库")
    except OSError:
        pytest.skip("上游参考库不可读")

    monkeypatch.setattr(settings, "reference_root", real_root)
    monkeypatch.setattr(settings, "reference_allow_nsfw", False)
    rl.clear_cache()
    stats = {row["library"]: row for row in rl.library_stats()}
    try:
        assert stats["pose"]["total"] == 1439
        assert stats["costume"]["total"] == 1407
        assert stats["portrait"]["total"] == 1499
        assert stats["costume-anime"]["total"] == 440
        assert stats["costume-anime"]["remote"] == 440

        depth_dir = real_root / "img" / "depth"
        depth_count = sum(1 for _ in depth_dir.glob("*.webp"))
        assert depth_count == 1439

        assert rl.query_items("costume", search="针织", page_size=1)["total"] > 0
        assert rl.query_items("portrait", search="波波头", page_size=1)["total"] > 0
    finally:
        rl.clear_cache()