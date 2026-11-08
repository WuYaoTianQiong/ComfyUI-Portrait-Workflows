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
from app.services.prompt_compiler import compile_prompt

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
    five_workflow = studio_dir / "图库专用_Qwen21+VNCCS_五图_可选人物B_25步_双人.api.json"
    five = _qwen21_workflow(with_extra=True)
    five["4"]["_meta"]["title"] = "图4：人物B参考 (PersonB)"
    five["13"] = {
        "class_type": "LoadImage",
        "inputs": {"image": "person_b_costume_ref.webp"},
        "_meta": {"title": "图5：人物B服装参考 (PersonB Costume)"},
    }
    five["8"]["inputs"]["images.image_5"] = ["13", 0]
    _write_json(five_workflow, five)
    _write_json(studio_dir / "测试_Flux三图_不可裁.api.json", _flux_workflow())
    # 不在 studio_dirs() 里：显式选择它必须 400，不能静默回落
    outside_workflow = library_root / "别处" / "外部工作流.api.json"
    _write_json(outside_workflow, _qwen21_workflow())

    # 运行数据根跟随 fixture 注入临时目录（生产默认 app_root/data）
    data_dir = tmp_path / "data"
    monkeypatch.setattr(settings, "data_dir", data_dir)
    uploads = settings.data_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    portrait_upload = uploads / "portrait.png"
    _write_bytes(portrait_upload, b"upload-portrait")

    monkeypatch.setattr(settings, "library_root", library_root)
    monkeypatch.setattr(settings, "reference_root", ref_root)
    monkeypatch.setattr(settings, "pose_extra_dir", None)
    monkeypatch.setattr(settings, "costume_character_dir", None)
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
    # 图号表（C-REF-FIGURE@1）：前端把「图N」标到槽位卡；含空槽
    assert body["figure_numbers"] == {"pose": 1, "portrait": 2, "costume": 3}
    assert body["figure_numbers_effective"] == {"pose": 1, "portrait": 2, "costume": 3}


def test_figure_numbers_keep_empty_slots_and_effective_shrinks(api, recipe_env):
    """空槽保留图号（用户能看出「图3 空着」），effective 只含真实用到的图号。"""
    resp = api.post(
        "/api/reference/recipes",
        json={"costume_id": "SPR-0001", "pose_id": "P001_front", "dry_run": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["figure_numbers"] == {"pose": 1, "portrait": 2, "costume": 3}
    assert body["figure_numbers_effective"] == {"pose": 1, "costume": 3}
    assert "图2" not in body["prompt"]


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


def test_extra_text_appends_to_extra_clause(api, recipe_env, captured):
    """第 4 槽有图时，文字作为「此外需体现」追加，不替换图片主句。"""
    resp = api.post(
        "/api/reference/recipes",
        json={
            **THREE_BODY,
            "workflow": "图库专用_四槽_测试",
            "extra_library": "costume",
            "extra_id": "ACC-0001",
            "extra_text": "金属扣与链条",
        },
    )
    assert resp.status_code == 200
    prompt = resp.json()["prompt"]
    assert "• 附加参考" in prompt
    assert "此外需体现：金属扣与链条。" in prompt
    # 预览与真实提交共用同一份生成结果（同一构建函数，不是两套文本）
    assert "此外需体现：金属扣与链条。" in captured[0].prompt


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
    assert set(slots) == {"portrait", "costume", "pose", "extra", "extra_costume"}
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
    assert roles == ["portrait", "costume", "pose", "extra", "extra_costume"]
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

def test_size_params_are_passed_to_editor(api, recipe_env, captured):
    """recipe 端点必须把三个尺寸参数原样透传，不能被 Pydantic 静默吞掉。"""
    resp = api.post(
        "/api/reference/recipes",
        json={
            **THREE_BODY,
            "quality": "1.5x",
            "aspect_ratio": "16:9",
            "orientation": "landscape",
        },
    )
    assert resp.status_code == 200
    req = captured[0]
    assert (req.quality, req.aspect_ratio, req.orientation) == (
        "1.5x", "16:9", "landscape",
    )


def test_qwen21_ignores_size_params_when_caps_unsupported(api, recipe_env, monkeypatch):
    """Qwen21 的 caps 是 quality/orientation=false：误传也必须回默认（二次防护）。"""
    from app.services import generation

    monkeypatch.setattr(generation, "enqueue_submission", lambda task: None)
    resp = api.post(
        "/api/reference/recipes",
        json={
            **THREE_BODY,
            "dry_run": False,
            "quality": "1.5x",
            "aspect_ratio": "16:9",
            "orientation": "landscape",
        },
    )
    assert resp.status_code == 200
    job = api.get(f"/api/jobs/{resp.json()['job_id']}").json()
    assert job["quality"] == "1.0x"      # 1.5x 被忽略，回旧默认 4K→1.0x
    assert job["orientation"] == "portrait"

# ---------------------------------------------------------------------------
# 提示词修正 + 素体模式（C-REF-BODY-MODE@1）
# ---------------------------------------------------------------------------

PAIR_ITEM = {
    "id": "pair-P900",
    "体系": "双人",
    "姿势编号": "P900",
    "分类": "双人站姿",
    "姿势名称": "双人并肩",
    "角度": "正面",
    "缩略图": "thumbs/P900.png",
    "原图": "img/P900.png",
    "检索": "pair-P900 双人 并肩",
}

PAIR_PSL_ITEM = {
    "id": "psl-D026",
    "体系": "双人",
    "姿势编号": "D026",
    "分类": "双人站姿",
    "姿势名称": "双臂前伸扶腰",
    "角度": "正面",
    "缩略图": "thumbs/psl-D026.png",
    "原图": "img/psl-D026.png",
    "检索": "psl-D026 双人 双臂前伸扶腰",
}


def _seed_pair_pose(recipe_env) -> None:
    """补上游 `pair*` 与 pose-studio-lite `psl-*` 两种双人姿势。"""
    _write_json(
        recipe_env["root"] / "data" / "pose-zh.json",
        POSE_ITEMS + [PAIR_ITEM, PAIR_PSL_ITEM],
    )
    for name in ("P900", "psl-D026"):
        _write_bytes(recipe_env["root"] / f"img/{name}.png")
        _write_bytes(recipe_env["root"] / f"thumbs/{name}.png")
    rl.clear_cache()


def test_person_b_text_reaches_prompt_for_composition_pair(api, recipe_env):
    """psl-* 双人姿势靠 composition 识别；B 文字设定进入自动提示词。"""
    _seed_pair_pose(recipe_env)
    resp = api.post(
        "/api/reference/recipes",
        json={
            "portrait_id": "p1",
            "costume_id": "SPR-0001",
            "pose_id": "psl-D026",
            "person_b_text": "金色齐肩短发，酒红色西装外套，黑色阔腿长裤",
            "dry_run": True,
        },
    )
    assert resp.status_code == 200
    prompt = resp.json()["prompt"]
    assert "双人要求" in prompt
    assert "• 人物B（文字设定）：金色齐肩短发，酒红色西装外套，黑色阔腿长裤。" in prompt
    assert "不要复用人物A的脸" in prompt


def test_pair_prompt_requires_complete_limbs(api, recipe_env):
    """V2-C：双人条款要求四肢完整，并把缺手缺脚类词交给负向。"""
    _seed_pair_pose(recipe_env)
    resp = api.post(
        "/api/reference/recipes",
        json={
            "portrait_id": "p1",
            "costume_id": "SPR-0001",
            "pose_id": "psl-D026",
            "dry_run": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    prompt = body["prompt"]
    assert "两人的手、手指、手臂、腿、脚必须完整自然出现" in prompt
    assert "服装未覆盖的部位必须是自然皮肤" in prompt
    assert "人体结构完整，四肢与手脚自然呈现" in prompt
    # 2026-11-08：双人姿势线稿重叠会多画人或手脚，正向补数量锚点、负向补「多」类词。
    assert "每人只有两条腿、两只脚、两只手" in prompt
    assert "重叠交叉轮廓是前后遮挡关系，不属于多余肢体" in prompt
    assert "画面中始终只有两位人物" in prompt
    # 测试夹具工作流没有接负向，这里直接验证「原文 + 编译器」这条链路会产出多人类负向。
    compiled = compile_prompt(body["prompt_raw"], "", negative_effective=True)
    for term in ("第三个人", "多余的腿", "多余的脚", "多余的手", "重复人体"):
        assert term in compiled.negative
    # 原文保留否定句，由编译器抽成负向；编译后正向不再出现「禁止漂浮衣架式人体」。
    assert "禁止漂浮衣架式人体" in body["prompt_raw"]
    assert "禁止漂浮衣架式人体" not in prompt
    assert "不得出现性器官、胸部、臀部裸露" in prompt
    assert "服装之外正常可见的手臂、小腿、手、脚属于正常皮肤" in prompt


FIVE_IMAGE_WORKFLOW = "图库专用_Qwen21+VNCCS_五图_可选人物B_25步_双人.api.json"


FIVE_IMAGE_BODY = {
    "portrait_id": "p1",
    "costume_id": "SPR-0001",
    "pose_id": "psl-D026",
    "extra_library": "portrait",
    "extra_id": "p1",
    "extra_costume_library": "costume",
    "extra_costume_id": "ACC-0001",
    "workflow": FIVE_IMAGE_WORKFLOW,
    "dry_run": True,
}


def test_five_image_workflow_exposes_extra_costume_slot(api, recipe_env):
    """V2-C：五图工作流必须下发 5 个业务角色，且第 5 槽识别为 extra_costume。"""
    resp = api.get("/api/workflows?scope=studio")
    assert resp.status_code == 200
    item = next(
        (row for row in resp.json()["workflows"] if row["name"] == FIVE_IMAGE_WORKFLOW),
        None,
    )
    assert item is not None
    assert item["slots"] == ["pose", "portrait", "costume", "extra", "extra_costume"]
    assert item["extra_kind"] == "person_b"
    assert item["input_count"] == 5


def test_five_image_prompt_uses_b_costume_image(api, recipe_env):
    """V2-C：B 服装按图5；B 服装文字被图像接管；图5 不回流到 A。"""
    _seed_pair_pose(recipe_env)
    resp = api.post(
        "/api/reference/recipes",
        json={
            **FIVE_IMAGE_BODY,
            "person_b_costume_text": "浅蓝衬衫兜底文字",
            "person_b_text": "与人物A年龄相近",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    prompt = body["prompt"]
    assert "请根据提供的 5 张参考图" in prompt
    assert "• 人物B：按图4的脸型、发型与图5的服装。" in prompt
    assert "• 人物B（图像参考）：图4是人物B的脸型与发型参考" in prompt
    assert "• 人物B（服装图像参考）：图5是人物B的整套服装、配饰与鞋参考" in prompt
    assert "图5的服装绝对不要用于人物A" in prompt
    # 图像接管后，B 服装文字与 B 面部文字都不再重复下发，只留自由文字（年龄）
    assert "浅蓝衬衫兜底文字" not in prompt
    assert "• 人物B（年龄/自由文字设定）：与人物A年龄相近。" in prompt
    # A 三槽条款保持原样
    assert "• 人物：图2中的人物" in prompt
    assert "• 服装：让人物穿上图3中展示的整套服装和配饰" in prompt
    slots = {item["role"]: item for item in body["slots"]}
    assert slots["extra_costume"]["id"] == "ACC-0001"
    assert slots["extra_costume"]["library"] == "costume"


def test_five_image_single_pose_writes_no_b_clause(api, recipe_env):
    """V2-C：单人姿势下第 4/5 槽仍作为输入，但不得写任何人物B条款。"""
    resp = api.post(
        "/api/reference/recipes",
        json={
            **FIVE_IMAGE_BODY,
            "pose_id": "P001_front",
        },
    )
    assert resp.status_code == 200
    prompt = resp.json()["prompt"]
    assert "请根据提供的 5 张参考图" in prompt
    assert "人物B" not in prompt
    assert "图5是人物B" not in prompt


def test_person_b_fragment_fields_reach_pair_prompt(api, recipe_env):
    """v1.5：B 的面部/身材、服饰字段与自由文本一起进入 B 条款；A 槽位文本不受影响。"""
    _seed_pair_pose(recipe_env)
    resp = api.post(
        "/api/reference/recipes",
        json={
            "portrait_id": "p1",
            "costume_id": "SPR-0001",
            "pose_id": "psl-D026",
            "portrait_text": "人物A：冷白皮",
            "portrait_supplement": True,
            "person_b_portrait_text": "冷白皮，鹅蛋脸，深棕高马尾",
            "person_b_costume_text": "浅蓝衬衫，米色长裙",
            "person_b_text": "棕色乐福鞋",
            "dry_run": True,
        },
    )
    assert resp.status_code == 200
    prompt = resp.json()["prompt"]
    # A 的补充文本仍在 A 条款里
    assert "此外需体现：人物A：冷白皮" in prompt
    # B 三部分按固定顺序合成同一段 B 条款
    assert "• 人物B（文字设定）：冷白皮，鹅蛋脸，深棕高马尾；浅蓝衬衫，米色长裙；棕色乐福鞋。" in prompt


def test_person_b_pose_and_modifier_reach_pair_prompt(api, recipe_env):
    """P1：B 姿势只走文字、B 修饰层独立成条款；A 的槽位文本不被 B 污染。"""
    _seed_pair_pose(recipe_env)
    resp = api.post(
        "/api/reference/recipes",
        json={
            "portrait_id": "p1",
            "costume_id": "SPR-0001",
            "pose_id": "psl-D026",
            "portrait_text": "人物A：冷白皮",
            "portrait_supplement": True,
            "person_b_pose_text": "侧身坐姿，双腿交叠",
            "person_b_modifier_fragments": "• 拍摄视角：低角度仰拍\n• 场景环境：黄昏天台",
            "dry_run": True,
        },
    )
    assert resp.status_code == 200
    prompt = resp.json()["prompt"]
    assert "此外需体现：人物A：冷白皮" in prompt
    assert "• 人物B（姿态文字）：侧身坐姿，双腿交叠。" in prompt
    assert "• 人物B（附加修饰）：拍摄视角：低角度仰拍；场景环境：黄昏天台。" in prompt
    # B 条款不得混进 A 的姿势/修饰段
    assert "• 姿势：严格复现图1中两个人形的身体姿态与镜头角度。" in prompt
    assert "低角度仰拍" not in prompt.split("• 人物B（附加修饰）")[0]


def test_person_b_pose_and_modifier_ignored_in_single_pose(api, recipe_env):
    """P1：单人姿势下 B 姿势/修饰字段不得生成任何人物B条款。"""
    resp = api.post(
        "/api/reference/recipes",
        json={
            "portrait_id": "p1",
            "costume_id": "SPR-0001",
            "pose_id": "P001_front",
            "person_b_pose_text": "侧身坐姿，双腿交叠",
            "person_b_modifier_fragments": "• 场景环境：黄昏天台",
            "dry_run": True,
        },
    )
    assert resp.status_code == 200
    prompt = resp.json()["prompt"]
    assert "人物B" not in prompt
    assert "侧身坐姿" not in prompt
    assert "黄昏天台" not in prompt


def test_person_b_style_fragment_suppresses_fixed_style(api, recipe_env):
    """P1：B 的画风碎片是整图属性，双人姿势下与固定风格段互斥。"""
    _seed_pair_pose(recipe_env)
    resp = api.post(
        "/api/reference/recipes",
        json={
            "portrait_id": "p1",
            "costume_id": "SPR-0001",
            "pose_id": "psl-D026",
            "person_b_modifier_fragments": "• 画风技术：赛博朋克霓虹质感",
            "dry_run": True,
        },
    )
    assert resp.status_code == 200
    prompt = resp.json()["prompt"]
    assert "• 人物B（附加修饰）：画风技术：赛博朋克霓虹质感。" in prompt
    # 固定写实风格段被抑制；主体判定仍按 style
    assert "写实商业摄影级质感" not in prompt
    assert "• 人物：图2中的人物" in prompt


def test_no_costume_prompt_drops_original_outfit_hint(api, recipe_env):
    """未选服装时不能写「保留图1人物原有可见服装」——否则模型会补全/捏造衣服。"""
    resp = api.post(
        "/api/reference/recipes",
        json={"portrait_id": "p1", "pose_id": "P001_front", "dry_run": True},
    )
    assert resp.status_code == 200
    prompt = resp.json()["prompt"]
    assert "保留图1人物原有可见服装" not in prompt
    assert "服装：让人物穿上" not in prompt
    # Qwen21 的真实图位是人像=图2；人像段本身必须保留
    assert "• 人物：图2中的人物" in prompt


def test_no_costume_pair_prompt_drops_forced_outfit(api, recipe_env):
    """双人姿势未选服装：自动按素体展示，不写「两人各自都有完整服装」。"""
    _seed_pair_pose(recipe_env)
    resp = api.post(
        "/api/reference/recipes",
        json={"portrait_id": "p1", "pose_id": PAIR_ITEM["id"], "dry_run": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    prompt = body["prompt"]
    assert "两人各自都有完整服装" not in prompt
    # 2026-11-06：缺服装自动切素体展示（不声明时 Qwen 系会自由发挥出裸体）
    assert body["body_mode"] == "bare"
    assert body["body_mode_auto"] is True
    assert "两位成年女性的素体展示" in prompt
    assert "两人都完整入镜" in prompt


def test_body_mode_validation_errors(api, recipe_env, captured):
    """C-REF-BODY-MODE@1：非法 body_mode 与「bare + 服装」都必须 400。"""
    bad_mode = api.post(
        "/api/reference/recipes",
        json={"pose_id": "P001_front", "body_mode": "nude", "dry_run": True},
    )
    assert bad_mode.status_code == 400
    detail = bad_mode.json()["detail"]
    assert "不支持的素体模式" in detail
    assert "costume" in detail and "bare" in detail

    with_costume_id = api.post(
        "/api/reference/recipes",
        json={
            "portrait_id": "p1",
            "pose_id": "P001_front",
            "costume_id": "SPR-0001",
            "body_mode": "bare",
            "dry_run": True,
        },
    )
    assert with_costume_id.status_code == 400
    assert with_costume_id.json()["detail"] == "素体模式不能同时选择服装"

    # 上传图路径同样算「选了服装」：校验必须发生在解析文件之前（文件不存在也先报冲突）
    with_costume_path = api.post(
        "/api/reference/recipes",
        json={
            "pose_id": "P001_front",
            "costume_path": str(recipe_env["uploads"] / "costume.png"),
            "body_mode": "bare",
            "dry_run": True,
        },
    )
    assert with_costume_path.status_code == 400
    assert with_costume_path.json()["detail"] == "素体模式不能同时选择服装"

    assert not captured, "校验失败不应进入提交"


def test_bare_mode_prompt_is_neutral_body_display(api, recipe_env):
    """bare 模式：只写中性素体展示，不写服装段，也不出现裸露/性感等词。"""
    resp = api.post(
        "/api/reference/recipes",
        json={
            "portrait_id": "p1",
            "pose_id": "P001_front",
            "body_mode": "bare",
            "dry_run": True,
        },
    )
    assert resp.status_code == 200
    prompt = resp.json()["prompt"]
    assert "素体展示" in prompt
    assert "不穿任何服装与配饰" in prompt
    assert "服装：让人物穿上" not in prompt
    assert "保留图1人物原有可见服装" not in prompt
    for word in ("裸露", "性感", "裸体"):
        assert word not in prompt, f"素体提示词不应出现「{word}」"


def test_bare_pair_prompt_uses_neutral_two_person_wording(api, recipe_env):
    """双人 + bare：写两位成年女性的素体展示，不再声明「各自都有完整服装」。"""
    _seed_pair_pose(recipe_env)
    resp = api.post(
        "/api/reference/recipes",
        json={"pose_id": PAIR_ITEM["id"], "body_mode": "bare", "dry_run": True},
    )
    assert resp.status_code == 200
    prompt = resp.json()["prompt"]
    assert "两位成年女性的素体展示" in prompt
    assert "两人各自都有完整服装" not in prompt
    assert "不允许裸露" not in prompt


# ---------------------------------------------------------------------------
# 提示词 A/B 拆条 + 成人向（2026-11-08）
# ---------------------------------------------------------------------------


def test_pair_prompt_splits_person_a_and_person_b_clauses(api, recipe_env):
    """V1：双人 + B 内容时，A/B 各自独立成条，「双人要求」只留人数与构图约束。"""
    _seed_pair_pose(recipe_env)
    resp = api.post(
        "/api/reference/recipes",
        json={
            "portrait_id": "p1",
            "costume_id": "SPR-0001",
            "pose_id": "psl-D026",
            "person_b_text": "金色齐肩短发，酒红色西装外套",
            "dry_run": True,
        },
    )
    assert resp.status_code == 200
    prompt = resp.json()["prompt"]
    assert "• 人物A：脸型、五官、发型严格沿用图2中的人物" in prompt
    assert "• 人物B：按下方文字设定。" in prompt
    # 拆条后混排句必须整体消失（同一行里不再出现「人物A：…；人物B…」）
    assert "人物A：脸型、五官、发型严格沿用图2中的人物；人物B" not in prompt
    assert "人物A只出现一次，人物B只出现一次" in prompt


def test_bare_pair_person_b_text_is_rendered(api, recipe_env):
    """V3：bare + 双人 + B 文字时，B 条款不再被整体丢弃。"""
    _seed_pair_pose(recipe_env)
    resp = api.post(
        "/api/reference/recipes",
        json={
            "portrait_id": "p1",
            "pose_id": "psl-D026",
            "body_mode": "bare",
            "person_b_portrait_text": "金发碧眼，丰满身材",
            "person_b_text": "体型高挑",
            "dry_run": True,
        },
    )
    assert resp.status_code == 200
    prompt = resp.json()["prompt"]
    assert "• 人物B（文字设定）：金发碧眼，丰满身材；体型高挑。" in prompt
    assert "• 人物A：脸型、五官、发型严格沿用图2中的人物。" in prompt
    # 素体专属措辞仍在，且没有服装段
    assert "不得出现性器官、胸部、臀部裸露" not in prompt
    assert "服装：让人物穿上" not in prompt


def test_adult_bare_removes_neutral_clauses(api, recipe_env, monkeypatch):
    """V4：18+ 解锁 + bare → 不再出现非性化/性暗示抑制句。"""
    monkeypatch.setattr(settings, "reference_allow_nsfw", True)
    resp = api.post(
        "/api/reference/recipes",
        json={
            "portrait_id": "p1",
            "pose_id": "P001_front",
            "body_mode": "bare",
            "adult_mode": True,
            "dry_run": True,
        },
    )
    assert resp.status_code == 200
    prompt = resp.json()["prompt"]
    assert "不穿任何服装与配饰" in prompt
    for word in ("非性化", "性暗示", "不得出现性器官"):
        assert word not in prompt, f"成人向提示词不应出现「{word}」"


def test_adult_pair_removes_modesty_clause_keeps_limbs(api, recipe_env, monkeypatch):
    """V5：18+ + 服装 + 双人 → 去掉禁裸露句，人数/四肢约束逐字保留。"""
    monkeypatch.setattr(settings, "reference_allow_nsfw", True)
    _seed_pair_pose(recipe_env)
    resp = api.post(
        "/api/reference/recipes",
        json={
            "portrait_id": "p1",
            "costume_id": "SPR-0001",
            "pose_id": "psl-D026",
            "adult_mode": True,
            "dry_run": True,
        },
    )
    assert resp.status_code == 200
    prompt = resp.json()["prompt"]
    assert "不得出现性器官、胸部、臀部裸露" not in prompt
    assert "每人只有两条腿、两只脚、两只手" in prompt
    assert "两人的手、手指、手臂、腿、脚必须完整自然出现" in prompt
    assert "禁止合并成一个人" in prompt


def test_adult_mode_requires_backend_gate(api, recipe_env):
    """总闸关闭时（fixture 默认 False），adult_mode=true 直接 400。"""
    resp = api.post(
        "/api/reference/recipes",
        json={
            "portrait_id": "p1",
            "pose_id": "P001_front",
            "body_mode": "bare",
            "adult_mode": True,
            "dry_run": True,
        },
    )
    assert resp.status_code == 400
    assert "18+ 总闸" in resp.json()["detail"]

def test_recipe_400_separates_unrecognized_roles_from_missing_slot(
    api, recipe_env, captured, monkeypatch,
):
    """两种 400 必须可区分，且都带工作流文件名：

    ① 整条工作流一个角色都认不出（典型：UI 格式 .json）→ 提示换用 .api.json；
    ② 角色可识别但本次要用的槽不存在 → 「该工作流没有{label}输入」。
    """
    studio = recipe_env["library_root"] / "图库专用工作流"

    # ① 两个 LoadImage 的标题都是「主体」/「参考图」→ role_nodes 为空
    unroleable = studio / "角色不可识别.api.json"
    _write_json(
        unroleable,
        {
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": "a.png"},
                "_meta": {"title": "主体参考"},
            },
            "2": {
                "class_type": "LoadImage",
                "inputs": {"image": "b.png"},
                "_meta": {"title": "参考图"},
            },
            "8": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["9", 0], "text": ""},
            },
        },
    )
    monkeypatch.setattr(ref_router, "_resolve_studio_workflow", lambda requested: unroleable)
    bad_roles = api.post(
        "/api/reference/recipes", json={"portrait_id": "p1", "dry_run": True},
    )
    assert bad_roles.status_code == 400
    detail = bad_roles.json()["detail"]
    assert "无法识别角色" in detail
    assert "请换用 .api.json 工作流" in detail
    assert "角色不可识别.api.json" in detail

    # ② 角色可识别（人像 + 姿势），但没有服装槽
    no_costume = studio / "只有人像和姿势.api.json"
    _write_json(
        no_costume,
        {
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": "a.png"},
                "_meta": {"title": "图1：人像参考 (Portrait)"},
            },
            "2": {
                "class_type": "LoadImage",
                "inputs": {"image": "b.png"},
                "_meta": {"title": "图2：姿势参考 (Pose)"},
            },
            "8": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["9", 0], "text": ""},
            },
        },
    )
    monkeypatch.setattr(ref_router, "_resolve_studio_workflow", lambda requested: no_costume)
    missing = api.post(
        "/api/reference/recipes",
        json={"portrait_id": "p1", "costume_id": "SPR-0001", "dry_run": True},
    )
    assert missing.status_code == 400
    missing_detail = missing.json()["detail"]
    assert missing_detail == "该工作流没有服装输入：只有人像和姿势.api.json"
    assert "无法识别角色" not in missing_detail

    assert not captured, "校验失败不应进入提交"


# ---------------------------------------------------------------------------
# POST /api/reference/trim-check：提交前可裁剪探测（2026-11-06）
#
# 前端只在 M（非空槽数）< N（input_count）时调用：
# - all_trimmable=true → 直接提交 + toast（不再弹确认框）；
# - all_trimmable=false → 弹原降级确认框，且框内不再给「仍用当前工作流提交」。
# 因此探测与提交必须是**同一判定**：探测说能提交，提交就不能再 400。
# ---------------------------------------------------------------------------


def test_trim_check_qwen_single_slot_is_trimmable(api, recipe_env):
    """Qwen 系缺槽可裁：探测直接放行，不再需要用户确认。"""
    body = api.post("/api/reference/trim-check", json={"roles": ["pose"]}).json()

    assert body["all_trimmable"] is True
    item = body["workflows"][0]
    assert item["name"] == ref_router.DEFAULT_STUDIO_WORKFLOW
    assert (item["input_count"], item["slot_count"]) == (3, 1)
    assert item["trimmable"] is True
    assert item["reason"] == ""


def test_trim_check_flux_blocked_reason_matches_submit_400(api, recipe_env):
    """Flux 系参考图不进文本编码器：探测必须说裁不掉，且原因与提交 400 完全一致。"""
    flux = "测试_Flux三图_不可裁.api.json"
    body = api.post(
        "/api/reference/trim-check",
        json={"workflows": [flux], "roles": ["portrait", "pose"]},
    ).json()

    assert body["all_trimmable"] is False
    item = body["workflows"][0]
    assert item["trimmable"] is False
    assert item["reason"] == "该工作流有 3 个输入且无法裁剪到 2 个；请至少提供 3 张参考图"

    rejected = api.post(
        "/api/reference/recipes",
        json={
            "portrait_id": "p1",
            "pose_id": "P001_front",
            "workflow": flux,
            "dry_run": True,
        },
    )
    assert rejected.status_code == 400
    assert rejected.json()["detail"] == item["reason"]


def test_trim_check_trimmable_true_means_submit_succeeds(api, recipe_env, captured):
    """探测 all_trimmable=true 时，同一组合的提交必须真的走到 faceswap_batch。"""
    body = api.post(
        "/api/reference/trim-check",
        json={"roles": ["pose", "costume"]},
    ).json()
    assert body["all_trimmable"] is True

    resp = api.post(
        "/api/reference/recipes",
        json={"pose_id": "P001_front", "costume_id": "SPR-0001", "dry_run": True},
    )
    assert resp.status_code == 200
    assert len(captured) == 1


def test_trim_check_mixed_workflows_reports_each(api, recipe_env):
    """多选工作流逐条给结论：任一不可裁，整体 all_trimmable=false。"""
    body = api.post(
        "/api/reference/trim-check",
        json={
            "workflows": [
                ref_router.DEFAULT_STUDIO_WORKFLOW,
                "测试_Flux三图_不可裁.api.json",
            ],
            "roles": ["pose"],
        },
    ).json()

    flags = {item["name"]: item["trimmable"] for item in body["workflows"]}
    assert flags == {
        ref_router.DEFAULT_STUDIO_WORKFLOW: True,
        "测试_Flux三图_不可裁.api.json": False,
    }
    assert body["all_trimmable"] is False


def test_trim_check_rejects_unknown_role_and_empty_slots(api, recipe_env):
    unknown = api.post("/api/reference/trim-check", json={"roles": ["face"]})
    assert unknown.status_code == 400
    assert "未知槽位" in unknown.json()["detail"]

    empty = api.post("/api/reference/trim-check", json={"roles": []})
    assert empty.status_code == 400
    assert "请至少选择一个参考图" in empty.json()["detail"]


# ---------------------------------------------------------------------------
# 缺服装 → 自动素体展示（2026-11-06 真出图实测结论）
#
# 实测（Qwen21 三图、人像+姿势 与 仅姿势）两张连续出裸体：`costume` 模式下服装槽为空时
# 提示词里没有任何服装约束，模型自由发挥。因此后端统一按 `bare`（中性素体条款）生成，
# 并在响应里回传生效值供前端 toast 说明。
# ---------------------------------------------------------------------------


def test_empty_costume_auto_switches_to_bare(api, recipe_env):
    """未声明 bare 但服装槽为空 → 自动素体展示，且不出现裸露/性感词。"""
    resp = api.post(
        "/api/reference/recipes",
        json={"portrait_id": "p1", "pose_id": "P001_front", "dry_run": True},
    )
    assert resp.status_code == 200
    body = resp.json()

    assert (body["body_mode"], body["body_mode_auto"]) == ("bare", True)
    prompt = body["prompt"]
    assert "素体展示" in prompt
    assert "服装：让人物穿上" not in prompt
    for word in ("裸露", "性感", "裸体"):
        assert word not in prompt, f"素体提示词不应出现「{word}」"


def test_costume_slot_present_keeps_costume_mode(api, recipe_env):
    """有服装参考时保持 costume 模式，不做素体兜底。"""
    resp = api.post("/api/reference/recipes", json=THREE_BODY)
    assert resp.status_code == 200
    body = resp.json()

    assert (body["body_mode"], body["body_mode_auto"]) == ("costume", False)
    assert "图3中展示的整套服装" in body["prompt"]


def test_trim_resolves_multi_level_conditioning_chain(api, recipe_env, captured):
    """多级 ReferenceLatent 链必须解析到存活节点，不能留悬空引用。

    真实事故（2026-11-06 实测）：QwenEdit 标准工作流只留姿势时，KSampler.positive
    仍指向被删的 ReferenceLatent → ComfyUI 返回 prompt_outputs_failed_validation 400。
    原因：共享 latent 让整条参考链一起进 drop，单层替换只退一步。
    """
    studio = recipe_env["library_root"] / "图库专用工作流"
    _write_json(
        studio / "多级参考链.api.json",
        {
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": "portrait.webp"},
                "_meta": {"title": "图1：人像参考 (Portrait)"},
            },
            "2": {
                "class_type": "LoadImage",
                "inputs": {"image": "costume.webp"},
                "_meta": {"title": "图2：服装参考 (Costume)"},
            },
            "3": {
                "class_type": "LoadImage",
                "inputs": {"image": "pose.webp"},
                "_meta": {"title": "图3：姿势参考 (Pose)"},
            },
            "8": {"class_type": "CLIPLoader", "inputs": {}},
            "11": {"class_type": "EmptyLatentImage", "inputs": {}},
            "12": {
                "class_type": "TextEncodeQwenImage21",
                "inputs": {
                    "clip": ["8", 0],
                    "prompt": "",
                    "images.image_1": ["1", 0],
                    "images.image_2": ["2", 0],
                    "images.image_3": ["3", 0],
                },
            },
            "13": {
                "class_type": "TextEncodeQwenImage21",
                "inputs": {
                    "clip": ["8", 0],
                    "prompt": "",
                    "images.image_1": ["1", 0],
                    "images.image_2": ["2", 0],
                    "images.image_3": ["3", 0],
                },
            },
            # 共享 latent：整条参考链会一起被裁（真实工作流就是这样）
            "21": {
                "class_type": "VAEEncode",
                "inputs": {"pixels": ["1", 0], "vae": ["8", 0]},
            },
            "24": {
                "class_type": "ReferenceLatent",
                "inputs": {"conditioning": ["12", 0], "latent": ["21", 0]},
            },
            "25": {
                "class_type": "ReferenceLatent",
                "inputs": {"conditioning": ["24", 0], "latent": ["21", 0]},
            },
            "26": {
                "class_type": "ReferenceLatent",
                "inputs": {"conditioning": ["13", 0], "latent": ["21", 0]},
            },
            "27": {
                "class_type": "ReferenceLatent",
                "inputs": {"conditioning": ["26", 0], "latent": ["21", 0]},
            },
            "14": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["8", 0],
                    "positive": ["25", 0],
                    "negative": ["27", 0],
                    "latent_image": ["11", 0],
                    "seed": 1,
                    "steps": 4,
                    "cfg": 1.0,
                    "sampler_name": "euler",
                    "scheduler": "simple",
                    "denoise": 1.0,
                },
            },
        },
    )
    rl.clear_cache()

    resp = api.post(
        "/api/reference/recipes",
        json={"pose_id": "P001_front", "workflow": "多级参考链.api.json", "dry_run": True},
    )
    assert resp.status_code == 200
    trimmed = json.loads(captured[0].workflow_content)
    node_ids = set(trimmed)

    # 递归解析到存活编码器，而不是停在已删的 ReferenceLatent
    assert trimmed["14"]["inputs"]["positive"] == ["12", 0]
    assert trimmed["14"]["inputs"]["negative"] == ["13", 0]
    for node_id, node in trimmed.items():
        for key, value in (node.get("inputs") or {}).items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                assert value[0] in node_ids, f"节点{node_id}.{key} 指向已删节点 {value[0]}"

def test_extra_text_requires_extra_image(api, recipe_env):
    """纯文字第 4 槽不成立：有 extra_text 必须同时有图。"""
    resp = api.post(
        "/api/reference/recipes",
        json={
            "portrait_id": "p1",
            "extra_text": "冷棕色，刘海偏分",
            "dry_run": True,
        },
    )
    assert resp.status_code == 400
    assert "第 4 槽文字补充必须同时提供" in resp.json()["detail"]
