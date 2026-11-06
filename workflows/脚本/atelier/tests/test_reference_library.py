"""AI 参考图库只读层契约：加载、检索、facet、NSFW、路径安全、深度图。

所有用例都指向临时构造的迷你参考库，不依赖本机真实素材；
另有一条「真实库规模」用例，只在存在上游目录时执行。
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.config import _resolve_reference_root, settings
from app.services import reference_library as rl
from app.services import reference_remote_cache


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
        "来源地址": "https://example.invalid/source/O001",
        "敏感": False,
        "检索": "charadb-O001 藏青水手服 制服与校园风",
    }
]


@pytest.fixture()
def remote_cache(tmp_path: Path, monkeypatch) -> Path:
    """隔离外链缓存目录与白名单；所有下载都由用例 mock，不访问真实外网。"""
    cache_dir = tmp_path / "remote-cache"
    monkeypatch.setattr(settings, "reference_cache_dir", cache_dir)
    monkeypatch.setattr(settings, "reference_remote_hosts", "example.invalid")
    monkeypatch.setattr(settings, "reference_remote_timeout_sec", 5.0)
    monkeypatch.setattr(settings, "reference_remote_max_concurrency", 4)
    monkeypatch.setattr(settings, "reference_remote_retry", 0)
    monkeypatch.setattr(settings, "reference_remote_max_bytes", 1024 * 1024)
    reference_remote_cache.reset_state()
    yield cache_dir
    reference_remote_cache.reset_state()


def _mock_http(monkeypatch, handler) -> list[str]:
    """把缓存服务的 httpx 客户端替换成 MockTransport，返回记录下来的请求 URL。"""
    calls: list[str] = []

    def counting_handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return handler(request)

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(counting_handler),
            follow_redirects=False,
        )

    monkeypatch.setattr(reference_remote_cache, "_make_client", factory)
    return calls


def _image_response(request: httpx.Request, content: bytes = b"remote-image") -> httpx.Response:
    return httpx.Response(
        200,
        content=content,
        headers={"content-type": "image/webp"},
        request=request,
    )


@pytest.fixture()
def ref_root(tmp_path: Path, monkeypatch, remote_cache: Path) -> Path:
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
    # 隔离本机真实安装的第二姿势来源，避免合并条数污染既有用例
    monkeypatch.setattr(settings, "pose_extra_dir", None)
    monkeypatch.setattr(settings, "reference_allow_nsfw", False)
    monkeypatch.setattr(settings, "reference_page_size", 60)
    rl.clear_cache()
    yield root
    rl.clear_cache()


@pytest.fixture()
def pose_extra_root(tmp_path: Path, monkeypatch) -> Path:
    """最小 pose-studio-lite 来源：std/sexy/upper/duo 四种 series 各 1 条。"""
    root = tmp_path / "pose-studio-lite"
    base = {
        "angle": "front",
        "angle_zh": "正面",
        "prompt_zh": "图1是人物照片，图2是姿势参考线稿。",
        "prompt_en": "Image 1 is the person; image 2 is the pose reference.",
    }
    items = [
        {
            **base,
            "id": "P001",
            "name": "正面站姿",
            "name_en": "Front stance",
            "file": "normal/P001_front.webp",
            "thumb": "thumbs/normal/P001_front.webp",
            "category": "normal",
            "group": "正常姿势",
            "facet": "站立",
            "series": "std",
            "series_label": "全身",
            "tags": ["全身", "站立"],
            "nsfw": False,
            "search": "P001 正面站姿 站立",
        },
        {
            **base,
            "id": "S001",
            "name": "成人坐姿",
            "name_en": "Adult seated",
            "file": "adult/S001_front.webp",
            "thumb": "thumbs/adult/S001_front.webp",
            "category": "adult",
            "group": "成人风格",
            "facet": "坐姿",
            "series": "sexy",
            "series_label": "风格姿势",
            "tags": ["风格姿势", "坐姿"],
            "nsfw": True,
            "search": "S001 成人坐姿 坐姿",
        },
        {
            **base,
            "id": "U001",
            "name": "上半身可爱",
            "name_en": "Upper cute",
            "file": "normal/U001_front.webp",
            "thumb": "thumbs/normal/U001_front.webp",
            "category": "normal",
            "group": "正常姿势",
            "facet": "可爱系",
            "series": "upper",
            "series_label": "半身",
            "tags": ["半身", "可爱系"],
            "nsfw": False,
            "search": "U001 上半身可爱 可爱系",
        },
        {
            **base,
            "id": "D001",
            "name": "双人背向坐",
            "name_en": "Duo seated back",
            "file": "adult/D001_front.webp",
            "thumb": "thumbs/adult/D001_front.webp",
            "category": "adult",
            "group": "成人风格",
            "facet": "背向坐",
            "series": "duo",
            "series_label": "双人",
            "tags": ["双人", "背向坐"],
            "nsfw": True,
            "search": "D001 双人背向坐 背向坐",
        },
    ]
    _write_json(root / "meta.json", {"count": len(items), "items": items})
    for rel in (
        "normal/P001_front.webp",
        "thumbs/normal/P001_front.webp",
        "normal/U001_front.webp",
        "thumbs/normal/U001_front.webp",
        "adult/S001_front.webp",
        "thumbs/adult/S001_front.webp",
        "adult/D001_front.webp",
        "thumbs/adult/D001_front.webp",
    ):
        _write_bytes(root / rel)

    monkeypatch.setattr(settings, "pose_extra_dir", root)
    rl.clear_cache()
    yield root
    rl.clear_cache()


def test_default_reference_root_prefers_comfyui_custom_nodes():
    """上游参考库固定在 `<comfyui_root>/custom_nodes/` 下；workflows 下不再需要 Junction。"""
    assert settings.reference_root == (
        settings.comfyui_root / "custom_nodes" / "ai-pose-gallery-zh"
    )
    assert settings.reference_dir == settings.reference_root


def test_resolve_reference_root_priority(tmp_path):
    """三级解析：显式 > custom_nodes 规范位置 > library_root 旧布局兼容回退。"""
    library_root = tmp_path / "library"
    comfyui_root = tmp_path / "comfyui"
    library_root.mkdir()
    comfyui_root.mkdir()
    canonical = comfyui_root / "custom_nodes" / "ai-pose-gallery-zh"
    legacy = library_root / "ai-pose-gallery-zh"

    # 都不存在：仍返回规范位置，让下游明确报错，而不是静默指向旧布局
    assert _resolve_reference_root(library_root, comfyui_root, None) == canonical

    # 只有旧布局：兼容回退
    legacy.mkdir()
    assert _resolve_reference_root(library_root, comfyui_root, None) == legacy

    # 规范位置存在：优先于旧布局
    canonical.mkdir(parents=True)
    assert _resolve_reference_root(library_root, comfyui_root, None) == canonical

    # 显式指定：最高优先，且不校验存在性
    explicit = tmp_path / "explicit-ref"
    assert _resolve_reference_root(library_root, comfyui_root, explicit) == explicit


def test_default_reference_cache_dir_is_under_app_root():
    """缓存默认位于 `<app_root>/.cache/reference-remote`，不得落在参考库/发布物内。"""
    cache_dir = Path(settings.reference_cache_dir)
    assert cache_dir.name == "reference-remote"
    assert cache_dir.parent.name == ".cache"
    assert cache_dir.parent.parent == settings.app_root
    assert not str(cache_dir).startswith(str(settings.reference_root))
    assert "dist" not in cache_dir.parts
    assert "data" not in cache_dir.parts


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


def test_pose_merges_extra_source(api, ref_root, pose_extra_root):
    """上游 3 条 + PSL 4 条（std/sexy/upper/duo）；安全模式隐藏 3 条敏感。"""
    stats = {row["library"]: row for row in api.get("/api/reference/libraries").json()["libraries"]}
    assert stats["pose"]["total"] == 7
    assert stats["pose"]["visible"] == 4
    assert stats["pose"]["available"] is True
    groups = {row["value"]: row["count"] for row in stats["pose"]["groups"]}
    assert groups["pose-studio-lite・正常姿势"] == 2
    assert "pose-studio-lite・成人风格" not in groups
    sources = {row["key"]: row for row in stats["pose"]["sources"]}
    assert sources["upstream"]["total"] == 3
    assert sources["pose-studio-lite"]["total"] == 4
    assert sources["pose-studio-lite"]["has_depth"] is False

    items = api.get(
        "/api/reference/items", params={"library": "pose", "search": "psl-P001"}
    ).json()
    assert items["total"] == 1
    item = items["items"][0]
    assert item["id"] == "psl-P001"
    assert item["group"] == "pose-studio-lite・正常姿势"
    assert item["number"] == "P001"
    assert item["source"] == "pose-studio-lite"
    assert item["composition"] == "full"
    assert item["pose_type"] == "站立"
    assert item["style"] == "标准"
    assert item["depth_url"] is None
    assert item["has_depth"] is False

    image = api.get("/api/reference/items/pose/psl-P001/image", params={"kind": "image"})
    assert image.status_code == 200
    thumb = api.get("/api/reference/items/pose/psl-P001/image", params={"kind": "thumb"})
    assert thumb.status_code == 200
    depth = api.get("/api/reference/items/pose/psl-P001/image", params={"kind": "depth"})
    assert depth.status_code == 404

    # PSL 图片必须落在自己的根目录，不能借用上游根
    path = rl.resolve_image("pose", "psl-P001", "image")
    assert str(path).startswith(str(pose_extra_root))
    # 上游深度图不受影响
    upstream_depth = api.get(
        "/api/reference/items/pose/P001_front/image", params={"kind": "depth"}
    )
    assert upstream_depth.status_code == 200


def test_pose_extra_nsfw_and_taxonomy(api, ref_root, pose_extra_root, monkeypatch):
    monkeypatch.setattr(settings, "reference_allow_nsfw", True)
    stats = {row["library"]: row for row in api.get("/api/reference/libraries").json()["libraries"]}
    assert stats["pose"]["total"] == 7
    assert stats["pose"]["visible"] == 7
    groups = {row["value"]: row["count"] for row in stats["pose"]["groups"]}
    assert groups["pose-studio-lite・正常姿势"] == 2
    assert groups["pose-studio-lite・成人风格"] == 2

    def get(item_id: str) -> dict:
        payload = api.get("/api/reference/items", params={"library": "pose", "search": item_id}).json()
        assert payload["total"] == 1
        return payload["items"][0]

    sexy = get("psl-S001")
    assert sexy["nsfw"] is True
    assert sexy["composition"] == "full"
    assert sexy["pose_type"] == "坐姿"
    assert sexy["style"] == "性感"

    upper = get("psl-U001")
    assert upper["composition"] == "upper"
    assert upper["pose_type"] == "上半身"
    assert upper["style"] == "可爱"

    duo = get("psl-D001")
    assert duo["composition"] == "pair"
    assert duo["pose_type"] == "背向坐位"
    assert duo["style"] == "性感"


def test_upstream_taxonomy_mapping():
    assert rl._upstream_composition("上半身单人") == "upper"
    assert rl._upstream_composition("双人缠绵") == "pair"
    assert rl._upstream_composition("全身单人・标准系") == "full"
    assert rl._upstream_pose_type_style("上半身单人", "可爱系", "upper") == ("上半身", "可爱")
    assert rl._upstream_pose_type_style(
        "全身单人・标准系", "坐姿", "full"
    ) == ("坐姿", "标准")
    assert rl._upstream_pose_type_style(
        "全身单人・性感系", "趴卧", "full"
    ) == ("躺卧", "性感")
    assert rl._upstream_pose_type_style(
        "双人缠绵", "骑乘位", "pair"
    ) == ("骑乘位", "性感")


def test_psl_taxonomy_mapping():
    sexy = {"series": "sexy", "category": "adult", "facet": "坐姿", "tags": ["风格姿势"], "nsfw": True}
    assert rl._psl_composition(sexy) == "full"
    assert rl._psl_pose_type_style(sexy, "full") == ("坐姿", "性感")

    upper = {"series": "upper", "category": "normal", "facet": "可爱系", "tags": ["半身"], "nsfw": False}
    assert rl._psl_composition(upper) == "upper"
    assert rl._psl_pose_type_style(upper, "upper") == ("上半身", "可爱")

    duo = {"series": "duo", "category": "adult", "facet": "背向坐", "tags": ["双人"], "nsfw": True}
    assert rl._psl_composition(duo) == "pair"
    assert rl._psl_pose_type_style(duo, "pair") == ("背向坐位", "性感")


def test_pose_extra_image_path_is_scoped(api, ref_root, pose_extra_root):
    """PSL 元数据里出现 ../ 时按越界 400 处理，不读上游/任意文件。"""
    meta = json.loads((pose_extra_root / "meta.json").read_text(encoding="utf-8"))
    meta["items"][0]["file"] = "../../evil.webp"
    (pose_extra_root / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    rl.clear_cache()
    with pytest.raises(rl.ReferenceImageError) as exc:
        rl.resolve_image("pose", "psl-P001", "image")
    assert exc.value.status_code == 400


def test_pose_extra_missing_keeps_upstream(api, ref_root, pose_extra_root):
    (pose_extra_root / "meta.json").unlink()
    rl.clear_cache()
    stats = {row["library"]: row for row in api.get("/api/reference/libraries").json()["libraries"]}
    assert stats["pose"]["total"] == 3
    assert stats["pose"]["available"] is True
    items = api.get(
        "/api/reference/items", params={"library": "pose", "search": "psl-P001"}
    ).json()
    assert items["total"] == 0


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


def test_remote_items_use_backend_endpoints(api, ref_root, monkeypatch):
    """`costume-anime` 对外只暴露后端图片端点，上游外链不再下发前端。"""
    resp = api.get("/api/reference/items", params={"library": "costume-anime"})
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["remote"] is True
    assert item["thumb_url"] == (
        "/api/reference/items/costume-anime/charadb-O001/image?kind=thumb"
    )
    assert item["image_url"] == (
        "/api/reference/items/costume-anime/charadb-O001/image?kind=image"
    )
    assert "example.invalid" not in item["thumb_url"]
    assert "pages.dev" not in item["thumb_url"]
    assert item["thumb_url"].startswith("/api/reference/items/costume-anime/")
    assert item["depth_url"] is None
    assert item["depth_thumb_url"] is None
    assert item["source_url"] == "https://example.invalid/source/O001"
    # 非 pose 库 number 恒为空；search_text 为上游「检索」原文
    assert item["number"] == ""
    assert item["search_text"] == "charadb-O001 藏青水手服 制服与校园风"

    _mock_http(monkeypatch, lambda request: _image_response(request, b"webp"))
    img = api.get(item["thumb_url"])
    assert img.status_code == 200
    assert img.content == b"webp"


def test_dto_number_and_search_text_per_library(api, ref_root):
    pose = api.get("/api/reference/items/pose/P001_front").json()
    assert pose["number"] == "P001"
    assert pose["subtitle"] == "P001 · 正面"
    assert pose["search_text"] == "P001_front 日常 站姿 正面站姿 正面 unknown 站立 标准"
    assert pose["source"] == "upstream"
    assert pose["composition"] == "unknown"
    assert pose["pose_type"] == "站立"
    assert pose["style"] == "标准"
    assert pose["source_url"] is None

    costume = api.get("/api/reference/items/costume/SPR-0001").json()
    assert costume["number"] == ""
    assert costume["source_url"] is None
    assert costume["search_text"] == "SPR-0001 春季穿搭 象牙白针织衫 针织 knit"

    portrait = api.get("/api/reference/items/portrait/p1").json()
    assert portrait["number"] == ""
    assert portrait["source_url"] is None


def test_remote_image_cache_hit_does_not_touch_network(api, ref_root, monkeypatch):
    """缓存命中直接返回本机文件，不允许发起任何 HTTP 请求。"""
    url = rl.resolve_remote_url("costume-anime", "charadb-O001", "thumb")
    assert url
    path = reference_remote_cache.cache_path(
        "costume-anime", "charadb-O001", "thumb", url
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"cached-image")

    calls = _mock_http(monkeypatch, lambda request: _image_response(request))
    resp = api.get(
        "/api/reference/items/costume-anime/charadb-O001/image", params={"kind": "thumb"}
    )
    assert resp.status_code == 200
    assert resp.content == b"cached-image"
    assert calls == []


def test_remote_image_miss_downloads_then_hits(api, ref_root, monkeypatch):
    calls = _mock_http(monkeypatch, lambda request: _image_response(request, b"downloaded"))

    first = api.get(
        "/api/reference/items/costume-anime/charadb-O001/image", params={"kind": "image"}
    )
    assert first.status_code == 200
    assert first.content == b"downloaded"
    assert len(calls) == 1

    url = rl.resolve_remote_url("costume-anime", "charadb-O001", "image")
    path = reference_remote_cache.cache_path(
        "costume-anime", "charadb-O001", "image", url
    )
    assert path.is_file()
    assert path.stat().st_size > 0

    second = api.get(
        "/api/reference/items/costume-anime/charadb-O001/image", params={"kind": "image"}
    )
    assert second.status_code == 200
    assert second.content == b"downloaded"
    assert len(calls) == 1, "第二次请求必须命中缓存，不得重新下载"


def test_remote_image_offline_cached_ok_uncached_502(api, ref_root, monkeypatch):
    _mock_http(monkeypatch, lambda request: _image_response(request, b"online"))
    warm = api.get(
        "/api/reference/items/costume-anime/charadb-O001/image", params={"kind": "thumb"}
    )
    assert warm.status_code == 200

    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    _mock_http(monkeypatch, offline)

    cached = api.get(
        "/api/reference/items/costume-anime/charadb-O001/image", params={"kind": "thumb"}
    )
    assert cached.status_code == 200
    assert cached.content == b"online"

    uncached = api.get(
        "/api/reference/items/costume-anime/charadb-O001/image", params={"kind": "image"}
    )
    assert uncached.status_code == 502
    assert "外链图片下载失败" in uncached.json()["detail"]


def test_remote_image_host_not_in_allowlist_400(api, ref_root, monkeypatch):
    evil = dict(ANIME_ITEMS[0])
    evil.update(
        {
            "id": "charadb-evil-host",
            "缩略图": "https://evil.invalid/thumb.webp",
            "原图": "https://evil.invalid/image.jpg",
        }
    )
    _write_json(ref_root / "data" / "costume-anime-zh.json", [evil])
    rl.clear_cache()

    resp = api.get(
        "/api/reference/items/costume-anime/charadb-evil-host/image", params={"kind": "image"}
    )
    assert resp.status_code == 400
    assert "不在允许的外链域名内" in resp.json()["detail"]


def test_cache_path_traversal_is_rejected(api, ref_root):
    with pytest.raises(reference_remote_cache.RemoteCacheError) as excinfo:
        reference_remote_cache.cache_path(
            "costume-anime", "../evil", "image", "https://example.invalid/a.jpg"
        )
    assert excinfo.value.status_code == 400

    traversal = dict(ANIME_ITEMS[0])
    traversal["id"] = "..\\..\\evil"
    _write_json(ref_root / "data" / "costume-anime-zh.json", [traversal])
    rl.clear_cache()

    resp = api.get(
        "/api/reference/items/costume-anime/..%5C..%5Cevil/image", params={"kind": "image"}
    )
    assert resp.status_code == 400
    assert "非法" in resp.json()["detail"]


def test_remote_image_non_image_content_type_502(api, ref_root, monkeypatch):
    def html(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"<html>not an image</html>",
            headers={"content-type": "text/html"},
            request=request,
        )

    _mock_http(monkeypatch, html)
    resp = api.get(
        "/api/reference/items/costume-anime/charadb-O001/image", params={"kind": "image"}
    )
    assert resp.status_code == 502
    assert "不是图片" in resp.json()["detail"]

    url = rl.resolve_remote_url("costume-anime", "charadb-O001", "image")
    path = reference_remote_cache.cache_path(
        "costume-anime", "charadb-O001", "image", url
    )
    assert not path.exists()
    assert not list(path.parent.glob(".image.*.tmp"))


def test_remote_image_empty_body_502(api, ref_root, monkeypatch):
    def empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"",
            headers={"content-type": "image/webp"},
            request=request,
        )

    _mock_http(monkeypatch, empty)
    resp = api.get(
        "/api/reference/items/costume-anime/charadb-O001/image", params={"kind": "image"}
    )
    assert resp.status_code == 502
    assert "空图片" in resp.json()["detail"]


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


def test_remote_item_without_urls_returns_none(api, tmp_path, monkeypatch, remote_cache):
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
        assert body["depth_url"] is None
        assert body["depth_thumb_url"] is None
        assert body["source_url"] is None

        # URL 缺失时后端端点返回 400，而不是把空串交给前端
        for kind in ("thumb", "image"):
            resp = api.get(
                "/api/reference/items/costume-anime/broken-1/image", params={"kind": kind}
            )
            assert resp.status_code == 400, kind
            assert "没有可用的图片地址" in resp.json()["detail"]
    finally:
        rl.clear_cache()


def test_remote_library_depth_is_404(api, ref_root):
    for kind in ("depth", "depth_thumb"):
        resp = api.get(
            "/api/reference/items/costume-anime/charadb-O001/image", params={"kind": kind}
        )
        assert resp.status_code == 404, kind


def test_remote_library_unknown_kind_is_404(api, ref_root):
    resp = api.get(
        "/api/reference/items/costume-anime/charadb-O001/image", params={"kind": "preview"}
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "不支持的图片类型"


def test_warm_many_reports_stats_and_reuses_cache(ref_root, monkeypatch):
    calls = _mock_http(monkeypatch, lambda request: _image_response(request, b"warm"))
    thumb_url = rl.resolve_remote_url("costume-anime", "charadb-O001", "thumb")
    image_url = rl.resolve_remote_url("costume-anime", "charadb-O001", "image")
    jobs = [
        ("costume-anime", "charadb-O001", "thumb", thumb_url),
        ("costume-anime", "charadb-O001", "image", image_url),
    ]

    first = asyncio.run(reference_remote_cache.warm_many(jobs, concurrency=2, retry=0))
    assert first.total == 2
    assert first.downloaded == 2
    assert first.cached == 0
    assert first.failed == 0
    assert first.failures == []
    assert len(calls) == 2

    second = asyncio.run(reference_remote_cache.warm_many(jobs, concurrency=2, retry=0))
    assert second.total == 2
    assert second.cached == 2
    assert second.downloaded == 0
    assert second.failed == 0
    assert len(calls) == 2, "已缓存条目重复预热不得重新下载"


def test_warm_many_continues_after_failure(ref_root, monkeypatch):
    _mock_http(monkeypatch, lambda request: _image_response(request, b"warm"))
    thumb_url = rl.resolve_remote_url("costume-anime", "charadb-O001", "thumb")
    jobs = [
        ("costume-anime", "charadb-O001", "thumb", thumb_url),
        ("costume-anime", "charadb-bad", "image", "https://evil.invalid/image.jpg"),
    ]

    stats = asyncio.run(reference_remote_cache.warm_many(jobs, concurrency=2, retry=0))
    assert stats.total == 2
    assert stats.downloaded == 1
    assert stats.failed == 1
    assert len(stats.failures) == 1
    assert stats.failures[0].item_id == "charadb-bad"
    assert "不在允许的外链域名内" in stats.failures[0].reason


def test_concurrent_ensure_cached_downloads_once(ref_root, monkeypatch):
    calls = _mock_http(monkeypatch, lambda request: _image_response(request, b"once"))
    url = rl.resolve_remote_url("costume-anime", "charadb-O001", "image")

    async def run() -> list[Path]:
        return await asyncio.gather(
            *[
                reference_remote_cache.ensure_cached(
                    "costume-anime", "charadb-O001", "image", url
                )
                for _ in range(6)
            ]
        )

    paths = asyncio.run(run())
    assert len(set(paths)) == 1
    assert len(calls) == 1, "同一缓存键的并发请求只允许下载一次"
    assert paths[0].read_bytes() == b"once"


def test_ensure_cached_sync_works_in_sync_and_async_context(ref_root, monkeypatch):
    """同步入口供 T6 的同步路由复用；在事件循环内调用时转独立线程执行。"""
    calls = _mock_http(monkeypatch, lambda request: _image_response(request, b"sync"))
    image_url = rl.resolve_remote_url("costume-anime", "charadb-O001", "image")
    path = reference_remote_cache.ensure_cached_sync(
        "costume-anime", "charadb-O001", "image", image_url
    )
    assert path.read_bytes() == b"sync"

    thumb_url = rl.resolve_remote_url("costume-anime", "charadb-O001", "thumb")

    async def run() -> Path:
        return reference_remote_cache.ensure_cached_sync(
            "costume-anime", "charadb-O001", "thumb", thumb_url
        )

    thumb_path = asyncio.run(run())
    assert thumb_path.read_bytes() == b"sync"
    assert len(calls) == 2


def test_cache_extension_inferred_from_content_type(ref_root, monkeypatch):
    """URL 无扩展名时由 Content-Type 映射扩展名；`is_cached` 必须能再次命中。"""
    url = "https://example.invalid/raw-image"

    def png(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"png-bytes",
            headers={"content-type": "image/png"},
            request=request,
        )

    _mock_http(monkeypatch, png)
    path = asyncio.run(
        reference_remote_cache.ensure_cached("costume-anime", "raw-1", "image", url)
    )
    assert path.name == "image.png"
    assert path.read_bytes() == b"png-bytes"
    assert reference_remote_cache.is_cached("costume-anime", "raw-1", "image", url)


def test_remote_image_too_large_502(api, ref_root, monkeypatch):
    monkeypatch.setattr(settings, "reference_remote_max_bytes", 8)
    _mock_http(monkeypatch, lambda request: _image_response(request, b"x" * 32))

    resp = api.get(
        "/api/reference/items/costume-anime/charadb-O001/image", params={"kind": "image"}
    )
    assert resp.status_code == 502
    assert "超出大小上限" in resp.json()["detail"]


def test_remote_image_redirect_is_failure_502(api, ref_root, monkeypatch):
    def redirect(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "https://example.invalid/elsewhere.jpg"},
            request=request,
        )

    _mock_http(monkeypatch, redirect)
    resp = api.get(
        "/api/reference/items/costume-anime/charadb-O001/image", params={"kind": "image"}
    )
    assert resp.status_code == 502
    assert "外链图片下载失败" in resp.json()["detail"]


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