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
