"""出图配方契约（M2/M2.5）：三/四图节点映射、槽位路径入参、错误分支。

提交动作一律被 `monkeypatch` 掉的 `editor.faceswap_batch` 截获，不会真的向 ComfyUI
推任务；另有一条 `dry_run` 用例走真实实现，用来核对节点 1/2/3 与 1/2/3/78 的映射。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import settings
from app.routers import editor as editor_router
from app.routers import reference_library as ref_router
from app.services import reference_library as rl

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


def _loadimage_workflow(*node_ids: str) -> dict:
    """最小 API 格式工作流：只保留 LoadImage，节点 id 与真实工作流一致。"""
    return {
        str(node_id): {"class_type": "LoadImage", "inputs": {"image": "placeholder.png"}}
        for node_id in node_ids
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
    _write_json(library_root / ref_router.THREE_REF_WORKFLOW, _loadimage_workflow("1", "2", "3"))
    _write_json(library_root / ref_router.FOUR_REF_WORKFLOW, _loadimage_workflow("1", "2", "3", "78"))

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


THREE_BODY = {
    "portrait_id": "p1",
    "costume_id": "SPR-0001",
    "pose_id": "P001_front",
    "dry_run": True,
}


def test_real_dry_run_reports_three_node_mapping(api, recipe_env):
    """走真实实现：三图必须是节点 1/2/3 + 三图工作流，且只做 dry_run。"""
    resp = api.post("/api/reference/recipes", json=THREE_BODY)
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True

    inputs = body["nodes"]["inputs"]
    assert [(item["role"], item["id"]) for item in inputs] == [
        ("target", "1"),
        ("ref1", "2"),
        ("ref2", "3"),
    ]
    assert Path(body["workflow_path"]).name == ref_router.THREE_REF_WORKFLOW
    assert body["plan"][0]["roles"] == ["target", "ref1", "ref2"]
    assert "图1" in body["prompt"] and "图3" in body["prompt"]


def test_real_dry_run_reports_four_node_mapping(api, recipe_env):
    """加第 4 张后自动切四图工作流，链尾节点固定为 78。"""
    body_req = {
        **THREE_BODY,
        "extra_library": "costume",
        "extra_id": "ACC-0001",
    }
    resp = api.post("/api/reference/recipes", json=body_req)
    assert resp.status_code == 200
    body = resp.json()

    inputs = body["nodes"]["inputs"]
    assert [(item["role"], item["id"]) for item in inputs] == [
        ("target", "1"),
        ("ref1", "2"),
        ("ref2", "3"),
        ("ref3", "78"),
    ]
    assert Path(body["workflow_path"]).name == ref_router.FOUR_REF_WORKFLOW
    assert body["plan"][0]["roles"] == ["target", "ref1", "ref2", "ref3"]
    assert "图4" in body["prompt"]
    assert body["references"]["extra"] == "ACC-0001"


def test_three_slot_payload_uses_expected_nodes(api, recipe_env, captured):
    resp = api.post("/api/reference/recipes", json=THREE_BODY)
    assert resp.status_code == 200
    assert len(captured) == 1
    req = captured[0]
    assert req.dry_run is True
    assert (req.main_node, req.ref_node, req.ref2_node, req.ref3_node) == (
        "1",
        "2",
        "3",
        None,
    )
    assert Path(req.workflow_path).name == ref_router.THREE_REF_WORKFLOW
    assert req.ref3_paths == []
    assert [Path(p).name for p in (req.main_paths + req.ref_paths + req.ref2_paths)] == [
        "p1.png",
        "SPR-0001.png",
        "P001_front.png",
    ]


def test_four_slot_payload_includes_node_78(api, recipe_env, captured):
    resp = api.post(
        "/api/reference/recipes",
        json={**THREE_BODY, "extra_library": "costume", "extra_id": "ACC-0001"},
    )
    assert resp.status_code == 200
    req = captured[0]
    assert req.ref3_node == "78"
    assert Path(req.workflow_path).name == ref_router.FOUR_REF_WORKFLOW
    assert [Path(p).name for p in req.ref3_paths] == ["ACC-0001.png"]


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


def test_remote_extra_item_is_400(api, recipe_env, captured):
    resp = api.post(
        "/api/reference/recipes",
        json={
            **THREE_BODY,
            "extra_library": "costume-anime",
            "extra_id": "charadb-O001",
        },
    )
    assert resp.status_code == 400
    assert "外链" in resp.json()["detail"]
    assert not captured, "校验失败不应进入提交"


def test_missing_inputs_are_400(api, recipe_env, captured):
    no_costume = api.post(
        "/api/reference/recipes",
        json={"portrait_id": "p1", "pose_id": "P001_front"},
    )
    assert no_costume.status_code == 400
    assert "缺少服装" in no_costume.json()["detail"]

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