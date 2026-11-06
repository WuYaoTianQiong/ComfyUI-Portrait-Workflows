"""工作流目录：历史工作流参与扫描，视频工作流默认隐藏。"""
import json
from pathlib import Path


def _write(path: Path, class_type: str):
    path.write_text(
        json.dumps({"1": {"class_type": class_type, "inputs": {"filename_prefix": "x"}}}),
        encoding="utf-8",
    )


def test_is_video_workflow_detects_save_video_nodes():
    from app.services.workflow_parser import is_video_workflow

    assert is_video_workflow({"1": {"class_type": "SaveVideo", "inputs": {}}})
    assert is_video_workflow({"1": {"class_type": "VHS_VideoCombine", "inputs": {}}})
    assert not is_video_workflow({"1": {"class_type": "SaveImage", "inputs": {}}})
    assert not is_video_workflow({"1": {"class_type": "SaveAnimatedWEBP", "inputs": {}}})


def test_list_valid_workflows_hides_video_and_ignores_archive(tmp_path, monkeypatch):
    from app.services import workflow_catalog

    root = tmp_path / "root"
    archive = tmp_path / "历史工作流"
    root.mkdir()
    archive.mkdir()
    _write(root / "文生图_image.json", "SaveImage")
    _write(root / "文生图_video.json", "SaveVideo")
    _write(archive / "归档_image.json", "SaveImage")

    # 自动扫描只认库根目录；归档目录要靠前端手动上传
    monkeypatch.setattr(workflow_catalog, "search_dirs", lambda: [root])

    visible = workflow_catalog.list_valid_workflows()
    names = {row["name"] for row in visible}
    assert names == {"文生图_image.json"}
    assert all(row["media_kind"] == "image" for row in visible)

    everything = workflow_catalog.list_valid_workflows(include_video=True)
    assert {row["name"] for row in everything} == {"文生图_image.json", "文生图_video.json"}
    assert next(r for r in everything if r["name"] == "文生图_video.json")["media_kind"] == "video"

    # 默认工作流不能落到视频上，即使视频文件名也带「文生图」
    assert workflow_catalog.find_default_workflow().endswith("文生图_image.json")


def test_archive_is_known_but_not_scanned():
    from app.config import settings
    from app.services import workflow_catalog

    assert workflow_catalog.ARCHIVE_DIR.name == "历史工作流"
    assert workflow_catalog.search_dirs() == [settings.library_root]

def test_studio_slots_skip_unrecognized_loadimage_titles(api, tmp_path, monkeypatch):
    """C-REF-WF-SLOTS@1：认不出角色的 LoadImage 不进 slots，但仍计入 input_count。"""
    from app.services import workflow_catalog

    studio = tmp_path / "图库专用工作流"
    studio.mkdir()
    (studio / "混合角色.api.json").write_text(
        json.dumps(
            {
                "1": {
                    "class_type": "LoadImage",
                    "inputs": {"image": "subject.png"},
                    "_meta": {"title": "主体参考"},
                },
                "2": {
                    "class_type": "LoadImage",
                    "inputs": {"image": "portrait.png"},
                    "_meta": {"title": "图1：人像参考 (Portrait)"},
                },
                "3": {
                    "class_type": "LoadImage",
                    "inputs": {"image": "pose.png"},
                    "_meta": {"title": "姿势参考 (Pose)"},
                },
                "4": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"clip": ["5", 0], "text": ""},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # 路由层与目录层都指向临时目录，避免读到真实库
    monkeypatch.setattr(workflow_catalog, "studio_dirs", lambda: [studio])
    monkeypatch.setattr(workflow_catalog, "search_dirs", lambda: [tmp_path])

    resp = api.get("/api/workflows", params={"scope": "studio"})
    assert resp.status_code == 200
    rows = resp.json()["workflows"]
    assert [row["name"] for row in rows] == ["混合角色.api.json"]

    row = rows[0]
    assert row["slots"] == ["portrait", "pose"], "「主体」不是业务角色，不能进 slots"
    assert row["input_count"] == 3, "认不出角色的 LoadImage 仍占一个输入位"

def test_studio_slots_degrade_to_empty_on_parse_error(api, tmp_path, monkeypatch):
    """解析失败的工作流不能拖垮整张列表：slots 降级为 []，请求仍然 200。

    这是防御性兜底：真实路径下目录层 `_studio_slots()` 解析失败会先判不可用，
    文件根本进不了 studio 列表；只有「目录层解析成功、路由层再次解析却失败」
    这种极端竞态才会走到这里，仍要求不抛异常。
    """
    from app.routers import comfyui as comfyui_router
    from app.services import workflow_catalog

    studio = tmp_path / "图库专用工作流"
    studio.mkdir()
    (studio / "坏文件.api.json").write_text(
        json.dumps(
            {
                "1": {
                    "class_type": "LoadImage",
                    "inputs": {"image": "portrait.png"},
                    "_meta": {"title": "图1：人像参考 (Portrait)"},
                },
                "2": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"clip": ["3", 0], "text": ""},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(workflow_catalog, "studio_dirs", lambda: [studio])
    monkeypatch.setattr(workflow_catalog, "search_dirs", lambda: [tmp_path])

    def boom(*_args, **_kwargs):
        raise ValueError("模拟解析失败")

    # 只让「补 slots / input_count」这条路径失败：目录扫描仍能正常列出该文件
    monkeypatch.setattr(comfyui_router, "load_workflow", boom)

    resp = api.get("/api/workflows", params={"scope": "studio"})
    assert resp.status_code == 200
    rows = resp.json()["workflows"]
    assert [row["name"] for row in rows] == ["坏文件.api.json"]
    assert rows[0]["slots"] == []
    assert rows[0]["input_count"] == 0

#: 本机 studio 白名单基线（2026-11-06 实测）：7 条能识别角色的参考合成工作流。
STUDIO_ROLE_WORKFLOWS = {
    "图库专用_Qwen21+VNCCS_三图_25步_单人.api.json",
    "图库专用_QwenEdit_GGUF-Q5KM_三图_4步_全身构图.api.json",
    "图库专用_QwenEdit_GGUF-Q5KM_三图_4步_全身构图_自动裁切.api.json",
    "图库专用_QwenEdit_GGUF-Q5KM_三图_4步_标准.api.json",
    "图库专用_QwenEdit_Nunchaku-fp4_三图_4步_低显存.api.json",
    "PornMaster_Flux2Klein9B_三图角色合成_6步_自动尺寸.api.json",
    "PornMaster_Flux2Klein9B_四图参考_6步_自动尺寸.api.json",
}

#: UI 格式 .json：能解析出 LoadImage，但标题一个业务角色都认不出 → 合成台永远失败。
UNROLEABLE_UI_WORKFLOWS = {
    "PornMaster_Flux2Klein9B_三图参考编辑_自动尺寸.json",
    "PornMaster_Flux2Klein9B_单图编辑_可选遮罩.json",
    "PornMaster_Flux2Klein9B_双图参考换衣_可选遮罩.json",
}


def test_studio_whitelist_excludes_workflows_without_recognizable_roles():
    """studio 白名单不能包含「有 LoadImage 但角色全认不出」的工作流。

    这类工作流选中后必然 400「该工作流没有人像输入」，属于永远不可能成功的选项。
    """
    from app.services.workflow_catalog import list_valid_workflows

    names = {row["name"] for row in list_valid_workflows(scope="studio")}
    assert STUDIO_ROLE_WORKFLOWS <= names, "可识别角色的 7 条必须保留"
    assert not (names & UNROLEABLE_UI_WORKFLOWS), "角色全认不出的 3 条必须剔除"
    assert names == STUDIO_ROLE_WORKFLOWS


def test_scope_all_still_sees_unroleable_ui_workflows():
    """scope=all 行为不变：其他页面（分类与标签 → 工作流）仍能看到这些文件。"""
    from app.services.workflow_catalog import list_valid_workflows

    names = {row["name"] for row in list_valid_workflows()}
    assert UNROLEABLE_UI_WORKFLOWS <= names
