"""出图配方契约（M2/M2.5）：空槽裁剪、真实图位编号、输入数校验、错误分支。

提交动作一律被 `monkeypatch` 掉的 `editor.faceswap_batch` 截获，不会真的向 ComfyUI
推任务；另有一条 `dry_run` 用例走真实实现，用来核对裁剪后的节点映射。

2026-11-05 契约变更：
- 三槽（人像/服装/姿势/附加）全部允许为空，空槽在提交前从工作流副本里裁掉；
- 提示词编号按工作流真实图位书写（Qwen21：1=姿势 / 2=人像 / 3=服装）；
- 工作流由 `workflow` 字段选择，空请求使用 Qwen21+VNCCS 默认工作流；
- 输入数按 N（工作流 LoadImage 数）与 M（实际提交张数）校验。
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.config import settings
from app.routers import editor as editor_router
from app.routers import reference_library as ref_router
from app.services import reference_library as rl
from app.services import reference_remote_cache

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
    }
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
    },
    {
        "id": "ACC-0001",
        "分类": "配饰",
        "服装名称": "棕色单肩包",
        "标签": ["包"],
        "关键词": "bag",
        "缩略图": "thumbs/costume/ACC-0001.png",
        "原图": "img/costume/ACC-0001.png",
        "检索": "ACC-0001 配饰 棕色单肩包 包 bag",
    },
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


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_bytes(path: Path, data: bytes = b"img") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _qwen21_workflow(*, with_extra: bool = False) -> dict:
    """与默认工作流一致的最小 Qwen21 结构：图位 1=姿势 / 2=人像 / 3=服装。"""
    workflow = {
        "1": {
            "class_type": "LoadImage",
            "inputs": {"image": "pose_ref.webp"},
            "_meta": {"title": "图3：姿势参考 (Pose) · 深度图"},
        },
        "2": {
            "class_type": "LoadImage",
            "inputs": {"image": "portrait_ref.webp"},
            "_meta": {"title": "图1：人像参考 (Portrait)"},
        },
        "3": {
            "class_type": "LoadImage",
            "inputs": {"image": "costume_ref.webp"},
            "_meta": {"title": "图2：服装参考 (Costume)"},
        },
        "8": {
            "class_type": "TextEncodeQwenImage21",
            "inputs": {
                "clip": ["5", 0],
                "prompt": "",
                "negative_prompt": "",
                "images.image_1": ["1", 0],
                "images.image_2": ["2", 0],
                "images.image_3": ["3", 0],
            },
        },
    }
    if with_extra:
        workflow["4"] = {
            "class_type": "LoadImage",
            "inputs": {"image": "extra_ref.png"},
            "_meta": {"title": "图4：附加参考 (Extra)"},
        }
        workflow["8"]["inputs"]["images.image_4"] = ["4", 0]
    return workflow


def _flux_workflow() -> dict:
    """Flux 系：参考图不进文本编码器，空槽无法裁掉（用于 400 分支）。"""
    return {
        "1": {
            "class_type": "LoadImage",
            "inputs": {"image": "portrait_ref.png"},
            "_meta": {"title": "图1：人像参考 (Portrait)"},
        },
        "2": {
            "class_type": "LoadImage",
            "inputs": {"image": "costume_ref.png"},
            "_meta": {"title": "图2：服装参考 (Costume)"},
        },
        "3": {
            "class_type": "LoadImage",
            "inputs": {"image": "pose_ref.png"},
            "_meta": {"title": "图3：姿势参考 (Pose)"},
        },
        "8": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["10", 0], "text": ""},
        },
    }


@pytest.fixture()
def recipe_env(tmp_path: Path, monkeypatch):
    ref_root = tmp_path / "ai-pose-gallery-zh"
    data = ref_root / "data"
    _write_json(data / "pose-zh.json", POSE_ITEMS)
    _write_json(data / "costume-zh.json", COSTUME_ITEMS)
    _write_json(data / "portrait-zh.json", PORTRAIT_ITEMS)
    _write_json(data / "costume-anime-zh.json", ANIME_ITEMS)
    for rel in (
        "img/P001_front.png",
        "thumbs/P001_front.png",
        "img/costume/SPR-0001.png",
        "thumbs/costume/SPR-0001.png",
        "img/costume/ACC-0001.png",
        "thumbs/costume/ACC-0001.png",
        "img/portrait/p1.png",
        "thumbs/portrait/p1.png",
    ):
        _write_bytes(ref_root / rel)

    library_root = tmp_path / "library"
    studio_dir = library_root / "图库专用工作流"
    default_workflow = studio_dir / ref_router.DEFAULT_STUDIO_WORKFLOW
    _write_json(default_workflow, _qwen21_workflow())
    _write_json(studio_dir / "图库专用_四槽_测试.api.json", _qwen21_workflow(with_extra=True))
    _write_json(studio_dir / "测试_Flux三图_不可裁.api.json", _flux_workflow())
    # 不在 studio_dirs() 里：显式选择它必须 400，不能静默回落
    outside_workflow = library_root / "别处" / "外部工作流.api.json"
    _write_json(outside_workflow, _qwen21_workflow())

    uploads = library_root / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    portrait_upload = uploads / "portrait.png"
    _write_bytes(portrait_upload, b"upload-portrait")

    monkeypatch.setattr(settings, "library_root", library_root)
    monkeypatch.setattr(settings, "reference_root", ref_root)
    monkeypatch.setattr(settings, "reference_allow_nsfw", False)
    rl.clear_cache()
    yield {
        "root": ref_root,
        "library_root": library_root,
        "uploads": uploads,
        "portrait_upload": portrait_upload,
        "default_workflow": default_workflow,
        "outside_workflow": outside_workflow,
    }
    rl.clear_cache()


@pytest.fixture()
def captured(monkeypatch):
    """截获提交载荷；返回值模拟 dry_run 的响应，绝不真提交任务。"""
    calls = []

    def fake_faceswap(req):
        calls.append(req)
        return {"success": True, "dry_run": req.dry_run, "total": 1}

    monkeypatch.setattr(editor_router, "faceswap_batch", fake_faceswap)
    return calls


@pytest.fixture()
def remote_cache_env(tmp_path: Path, monkeypatch):
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


def _seed_remote_image(item_id: str = "charadb-O001") -> Path:
    """预置 costume-anime 原图缓存，模拟预热脚本已跑过（不发网络请求）。"""
    url = rl.resolve_remote_url("costume-anime", item_id, "image")
    assert url, "测试数据必须提供外链原图 URL"
    path = reference_remote_cache.cache_path("costume-anime", item_id, "image", url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"cached-anime")
    return path


def _mock_http(monkeypatch, handler) -> list[str]:
    """替换缓存服务的 httpx 客户端，记录请求 URL；返回空列表即未访问网络。"""
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


THREE_BODY = {
    "portrait_id": "p1",
    "costume_id": "SPR-0001",
    "pose_id": "P001_front",
    "dry_run": True,
}


def _inputs(body: dict) -> list[tuple[str, str]]:
    return [(item["role"], item["id"]) for item in body["nodes"]["inputs"]]


def test_real_dry_run_reports_real_node_mapping(api, recipe_env):
    """走真实实现：默认 Qwen21 的图位是 1=姿势 / 2=人像 / 3=服装。"""
    resp = api.post("/api/reference/recipes", json=THREE_BODY)
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    assert body["input_count"] == 3

    assert _inputs(body) == [
        ("target", "2"),   # 人像
        ("ref1", "3"),     # 服装
        ("ref2", "1"),     # 姿势
    ]
    assert Path(body["workflow_path"]).name == ref_router.DEFAULT_STUDIO_WORKFLOW
    assert body["plan"][0]["roles"] == ["target", "ref1", "ref2"]
    # 编号必须按真实图位书写，而不是按出现顺序重排
    assert "图2中的人物" in body["prompt"]
    assert "图3中展示的整套服装" in body["prompt"]
    assert "图1中人体模型" in body["prompt"]


def test_empty_slot_trims_workflow_and_keeps_real_numbers(api, recipe_env, captured):
    """缺人像：工作流裁成 2 个 LoadImage，提示词仍是 图3 服装 / 图1 姿势。"""
    resp = api.post(
        "/api/reference/recipes",
        json={"costume_id": "SPR-0001", "pose_id": "P001_front", "dry_run": True},
    )
    assert resp.status_code == 200
    assert len(captured) == 1
    req = captured[0]

    trimmed = json.loads(req.workflow_content)
    loads = [node for node in trimmed.values() if node["class_type"] == "LoadImage"]
    assert len(loads) == 2
    encoder = trimmed["8"]["inputs"]
    assert "images.image_2" not in encoder, "人像槽对应的编码器键必须删除"
    assert encoder["images.image_1"] == ["1", 0]  # 姿势
    assert encoder["images.image_3"] == ["3", 0]  # 服装

    # 节点号保持原图位，不压缩重排
    assert (req.main_node, req.ref_node, req.ref2_node) == ("3", "1", None)
    assert [Path(p).name for p in req.main_paths + req.ref_paths] == [
        "SPR-0001.png",
        "P001_front.png",
    ]

    prompt = resp.json()["prompt"]
    assert "图3中展示的整套服装" in prompt
    assert "图1中人体模型" in prompt
    assert "图2" not in prompt, "人像槽为空，提示词里不能出现图2"


def test_empty_slot_dry_run_reports_trimmed_nodes(api, recipe_env):
    """真实 dry_run：裁剪后的节点映射必须是剩余的两个真实图位。"""
    resp = api.post(
        "/api/reference/recipes",
        json={"costume_id": "SPR-0001", "pose_id": "P001_front", "dry_run": True},
    )
    body = resp.json()
    assert resp.status_code == 200
    assert _inputs(body) == [("target", "3"), ("ref1", "1")]
    assert body["input_count"] == 3


def test_faceless_prompt_triggers_when_portrait_empty(api, recipe_env):
    """缺人像时 faceless 必须生效（空槽直接传 None，不再被上传占位包装）。"""
    resp = api.post(
        "/api/reference/recipes",
        json={"costume_id": "SPR-0001", "pose_id": "P001_front", "dry_run": True},
    )
    assert resp.status_code == 200
    assert "无脸展示" in resp.json()["prompt"]


def test_single_slot_is_allowed(api, recipe_env, captured):
    """只交一张也能跑：工作流裁到 1 个 LoadImage。"""
    resp = api.post(
        "/api/reference/recipes",
        json={"pose_id": "P001_front", "dry_run": True},
    )
    assert resp.status_code == 200
    req = captured[0]
    trimmed = json.loads(req.workflow_content)
    loads = [node for node in trimmed.values() if node["class_type"] == "LoadImage"]
    assert len(loads) == 1
    assert req.main_node == "1"
    assert req.main_paths and not req.ref_paths and not req.ref2_paths


def test_extra_on_three_input_workflow_is_400(api, recipe_env, captured):
    """三图工作流 + 第 4 张 = M(4) > N(3)，必须 400，不能静默丢掉。"""
    resp = api.post(
        "/api/reference/recipes",
        json={**THREE_BODY, "extra_library": "costume", "extra_id": "ACC-0001"},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "3 个输入" in detail and "4 张" in detail
    assert not captured


def test_four_input_workflow_accepts_extra(api, recipe_env, captured):
    """有 4 个输入的工作流可以带第 4 张，节点用真实图位 1/2/3/4。"""
    resp = api.post(
        "/api/reference/recipes",
        json={
            **THREE_BODY,
            "workflow": "图库专用_四槽_测试",
            "extra_library": "costume",
            "extra_id": "ACC-0001",
        },
    )
    assert resp.status_code == 200
    req = captured[0]
    # 四槽测试工作流沿用 Qwen21 图位：1=姿势 / 2=人像 / 3=服装 / 4=附加
    assert (req.main_node, req.ref_node, req.ref2_node, req.ref3_node) == (
        "2", "3", "1", "4",
    )
    assert Path(req.workflow_path).name == "图库专用_四槽_测试.api.json"
    assert Path(req.ref3_paths[0]).name == "ACC-0001.png"
    assert "图4" in resp.json()["prompt"]


def test_three_slot_payload_uses_real_nodes(api, recipe_env, captured):
    resp = api.post("/api/reference/recipes", json=THREE_BODY)
    assert resp.status_code == 200
    assert len(captured) == 1
    req = captured[0]
    assert req.dry_run is True
    assert (req.main_node, req.ref_node, req.ref2_node, req.ref3_node) == (
        "2", "3", "1", None,
    )
    assert Path(req.workflow_path).name == ref_router.DEFAULT_STUDIO_WORKFLOW
    assert req.ref3_paths == []
    assert [Path(p).name for p in (req.main_paths + req.ref_paths + req.ref2_paths)] == [
        "p1.png",
        "SPR-0001.png",
        "P001_front.png",
    ]


def test_one_slot_can_use_uploaded_path(api, recipe_env, captured):
    resp = api.post(
        "/api/reference/recipes",
        json={
            "portrait_path": str(recipe_env["portrait_upload"]),
            "costume_id": "SPR-0001",
            "pose_id": "P001_front",
            "dry_run": True,
        },
    )
    assert resp.status_code == 200
    req = captured[0]
    assert [Path(p).name for p in req.main_paths] == ["portrait.png"]
    assert Path(req.ref_paths[0]).name == "SPR-0001.png"
    assert Path(req.ref2_paths[0]).name == "P001_front.png"
    # 上传槽没有库条目，响应里的 references 用空串表示
    assert resp.json()["references"]["portrait"] == ""


def test_slots_unify_library_and_upload(api, recipe_env, captured):
    """slots 把库条目 / 上传图 / 空槽统一成同一形状（references 只带 id）。"""
    resp = api.post(
        "/api/reference/recipes",
        json={
            "portrait_path": str(recipe_env["portrait_upload"]),
            "costume_id": "SPR-0001",
            "pose_id": "P001_front",
            "dry_run": True,
        },
    )
    assert resp.status_code == 200
    slots = {slot["role"]: slot for slot in resp.json()["slots"]}
    assert set(slots) == {"portrait", "costume", "pose", "extra"}
    assert slots["extra"]["source"] == "empty"

    upload = slots["portrait"]
    assert upload["source"] == "upload"
    assert upload["id"] == "" and upload["library"] == ""
    assert Path(upload["path"]).name == "portrait.png"

    library = slots["costume"]
    assert library["source"] == "library"
    assert library["library"] == "costume" and library["id"] == "SPR-0001"
    assert Path(library["path"]).name == "SPR-0001.png"


def test_slots_include_optional_fourth(api, recipe_env, captured):
    resp = api.post(
        "/api/reference/recipes",
        json={
            **THREE_BODY,
            "workflow": "图库专用_四槽_测试",
            "extra_library": "costume",
            "extra_id": "ACC-0001",
        },
    )
    assert resp.status_code == 200
    roles = [slot["role"] for slot in resp.json()["slots"]]
    assert roles == ["portrait", "costume", "pose", "extra"]
    assert "ACC-0001" in resp.json()["references"]["extra"]


def test_non_studio_workflow_is_400(api, recipe_env, captured):
    """显式选择一个不在合成台范围的工作流必须 400，不静默回落默认值。"""
    resp = api.post(
        "/api/reference/recipes",
        json={**THREE_BODY, "workflow": str(recipe_env["outside_workflow"])},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "该工作流不属于合成台可用范围"
    assert not captured


def test_untrimmable_workflow_requires_all_inputs(api, recipe_env, captured):
    """Flux 系不能裁空槽：M=2 < N=3 时必须 400 并说明需要几张。"""
    resp = api.post(
        "/api/reference/recipes",
        json={
            "portrait_id": "p1",
            "costume_id": "SPR-0001",
            "workflow": "测试_Flux三图_不可裁",
        },
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "3 个输入" in detail and "2 个" in detail
    assert not captured


def test_id_takes_priority_over_path(api, recipe_env, captured):
    # 路径在 uploads 外，若被使用必然 400；这里应直接忽略路径走库条目
    outside = recipe_env["root"].parent / "outside.png"
    _write_bytes(outside)
    resp = api.post(
        "/api/reference/recipes",
        json={**THREE_BODY, "portrait_path": str(outside)},
    )
    assert resp.status_code == 200
    assert Path(captured[0].main_paths[0]).name == "p1.png"


def test_path_outside_uploads_is_400(api, recipe_env, captured):
    outside = recipe_env["root"].parent / "outside.png"
    _write_bytes(outside)
    body = api.post(
        "/api/reference/recipes",
        json={**THREE_BODY, "portrait_path": str(outside)},
    ).json()
    # 上面的 *_id 优先；单独用路径时才走校验
    resp = api.post(
        "/api/reference/recipes",
        json={
            "portrait_path": str(outside),
            "costume_id": "SPR-0001",
            "pose_id": "P001_front",
            "dry_run": True,
        },
    )
    assert body["references"]["portrait"] == "p1"
    assert resp.status_code == 400
    assert "上传目录" in resp.json()["detail"]
    assert captured and len(captured) == 1, "越界路径不应进入提交"


def test_upload_path_validation_errors(api, recipe_env, captured):
    # 目录穿越写法
    traversal = api.post(
        "/api/reference/recipes",
        json={
            "portrait_path": "../outside.png",
            "costume_id": "SPR-0001",
            "pose_id": "P001_front",
        },
    )
    assert traversal.status_code == 400

    # 扩展名不在白名单
    txt = recipe_env["uploads"] / "note.txt"
    txt.write_text("x", encoding="utf-8")
    bad_ext = api.post(
        "/api/reference/recipes",
        json={
            "portrait_path": str(txt),
            "costume_id": "SPR-0001",
            "pose_id": "P001_front",
        },
    )
    assert bad_ext.status_code == 400
    assert "图片类型" in bad_ext.json()["detail"]

    # 文件不存在
    missing = api.post(
        "/api/reference/recipes",
        json={
            "portrait_path": str(recipe_env["uploads"] / "nope.png"),
            "costume_id": "SPR-0001",
            "pose_id": "P001_front",
        },
    )
    assert missing.status_code == 400
    assert "不存在" in missing.json()["detail"]

    assert not captured


def test_remote_extra_item_cache_miss_is_502(api, recipe_env, remote_cache_env, captured, monkeypatch):
    """第 4 张外链条目缓存缺失且下载失败 → 502，错误文本带槽位名。"""

    def server_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, request=request)

    _mock_http(monkeypatch, server_error)
    resp = api.post(
        "/api/reference/recipes",
        json={
            **THREE_BODY,
            "workflow": "图库专用_四槽_测试",
            "extra_library": "costume-anime",
            "extra_id": "charadb-O001",
        },
    )
    assert resp.status_code == 502
    assert "第 4 张参考" in resp.json()["detail"]
    assert "下载失败" in resp.json()["detail"]
    assert not captured, "校验失败不应进入提交"


def test_cached_costume_anime_as_fourth(api, recipe_env, remote_cache_env, captured, monkeypatch):
    """缓存就绪的外链服装同样可作为第 4 张，节点仍是真实图位 4。"""
    _seed_remote_image()
    calls = _mock_http(monkeypatch, lambda request: httpx.Response(500, request=request))
    resp = api.post(
        "/api/reference/recipes",
        json={
            **THREE_BODY,
            "workflow": "图库专用_四槽_测试",
            "extra_library": "costume-anime",
            "extra_id": "charadb-O001",
        },
    )
    assert resp.status_code == 200
    req = captured[0]
    assert req.ref3_node == "4"
    assert Path(req.workflow_path).name == "图库专用_四槽_测试.api.json"
    assert calls == [], "缓存命中不应访问网络"


def test_costume_library_defaults_to_costume(api, recipe_env):
    """不传 `costume_library` 时按本地 costume 库解析（与现状一致）。"""
    resp = api.post("/api/reference/recipes", json=THREE_BODY)
    assert resp.status_code == 200
    slots = {slot["role"]: slot for slot in resp.json()["slots"]}
    assert slots["costume"]["library"] == "costume"
    assert Path(slots["costume"]["path"]).name == "SPR-0001.png"


def test_cached_costume_anime_dry_run_reports_real_node_mapping(api, recipe_env, remote_cache_env, monkeypatch):
    """缓存就绪的 costume-anime 可参与三图 dry_run，不再报“外链素材不能参与”。"""
    _seed_remote_image()
    calls = _mock_http(monkeypatch, lambda request: httpx.Response(500, request=request))
    resp = api.post(
        "/api/reference/recipes",
        json={**THREE_BODY, "costume_library": "costume-anime", "costume_id": "charadb-O001"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    assert _inputs(body) == [("target", "2"), ("ref1", "3"), ("ref2", "1")]
    assert Path(body["workflow_path"]).name == ref_router.DEFAULT_STUDIO_WORKFLOW
    assert body["references"]["costume"] == "charadb-O001"
    costume_slot = {slot["role"]: slot for slot in body["slots"]}["costume"]
    assert costume_slot["library"] == "costume-anime"
    assert calls == [], "缓存命中不应访问网络"


def test_unknown_costume_library_is_400(api, recipe_env):
    resp = api.post(
        "/api/reference/recipes",
        json={**THREE_BODY, "costume_library": "portrait"},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "服装" in detail
    assert "costume-anime" in detail


def test_costume_anime_cache_miss_download_failure_is_502(api, recipe_env, remote_cache_env, monkeypatch):
    """缓存缺失且下载失败 → 502，detail 明确指向服装槽位。"""

    def server_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, request=request)

    _mock_http(monkeypatch, server_error)
    resp = api.post(
        "/api/reference/recipes",
        json={**THREE_BODY, "costume_library": "costume-anime", "costume_id": "charadb-O001"},
    )
    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert "服装" in detail
    assert "下载失败" in detail


def test_costume_anime_without_remote_url_is_400(api, recipe_env):
    no_url = dict(ANIME_ITEMS[0])
    no_url.update({"id": "charadb-no-url", "缩略图": "", "原图": ""})
    _write_json(recipe_env["root"] / "data" / "costume-anime-zh.json", [no_url])
    rl.clear_cache()

    resp = api.post(
        "/api/reference/recipes",
        json={
            **THREE_BODY,
            "costume_library": "costume-anime",
            "costume_id": "charadb-no-url",
        },
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "服装" in detail
    assert "没有可用的图片地址" in detail


def test_invalid_requests_are_400(api, recipe_env, captured):
    """空提交 / 缺 extra 库标识 / 未知画风都必须 400。"""
    empty = api.post("/api/reference/recipes", json={"dry_run": True})
    assert empty.status_code == 400
    assert "请至少选择一个参考图" in empty.json()["detail"]

    no_extra_library = api.post(
        "/api/reference/recipes",
        json={**THREE_BODY, "extra_id": "ACC-0001"},
    )
    assert no_extra_library.status_code == 400
    assert "第 4 张缺少参考库标识" in no_extra_library.json()["detail"]

    unknown_style = api.post(
        "/api/reference/recipes",
        json={**THREE_BODY, "style": "anime"},
    )
    assert unknown_style.status_code == 400

    assert not captured


def test_empty_combos_is_400(api, recipe_env, monkeypatch):
    """素材组为空时 editor 必须拒绝，而不是静默入队 0 张。"""
    monkeypatch.setattr(editor_router, "_collect_sources", lambda *args, **kwargs: [])
    resp = api.post(
        "/api/editor/faceswap/batch",
        json={
            "main_paths": [str(recipe_env["portrait_upload"])],
            "workflow_path": str(recipe_env["default_workflow"]),
        },
    )
    assert resp.status_code == 400
    assert "全组合为空" in resp.json()["detail"]