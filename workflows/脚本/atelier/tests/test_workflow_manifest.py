"""工作流身份：清单 id 稳定、sha256 随内容变化、自定义内容用哈希。"""
import json

from app.config import settings
from app.services import workflow_manifest


def test_manifest_id_is_stable_when_content_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "library_root", tmp_path)
    # 清单是运行数据，落在 data_dir（不再放库根）
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    folder = tmp_path / "通用工作流"
    folder.mkdir()
    workflow = folder / "a.json"
    workflow.write_text('{"1": {"class_type": "SaveImage"}}', encoding="utf-8")

    sha_before = workflow_manifest.content_sha256(workflow)
    manifest = {
        "schema": 1,
        "workflows": [{
            "id": "wf-test",
            "file": "通用工作流/a.json",
            "sha256": sha_before,
        }],
    }
    (tmp_path / workflow_manifest.MANIFEST_FILENAME).write_text(
        json.dumps(manifest), encoding="utf-8",
    )

    first = workflow_manifest.identify(str(workflow))
    assert first is not None
    assert first.id == "wf-test"
    assert first.sha256 == sha_before
    assert first.source == "manifest"

    workflow.write_text('{"1": {"class_type": "SaveImage"}, "2": {}}', encoding="utf-8")
    second = workflow_manifest.identify(str(workflow))
    assert second is not None
    assert second.id == "wf-test", "内容变化不能改变稳定 id"
    assert second.sha256 != sha_before


def test_build_job_extra_records_identity(tmp_path, monkeypatch):
    from app.services import job_state

    monkeypatch.setattr(settings, "library_root", tmp_path)
    folder = tmp_path / "通用工作流"
    folder.mkdir()
    workflow = folder / "a.json"
    workflow.write_text("{}", encoding="utf-8")

    extra = job_state.build_job_extra(str(workflow), None)

    assert extra["workflow_id"].startswith("wf-")
    assert len(extra["workflow_sha256"]) == 64
    assert extra["workflow_rel_path"] == "通用工作流/a.json"


def test_unregistered_file_gets_stable_path_id(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "library_root", tmp_path)
    folder = tmp_path / "通用工作流"
    folder.mkdir()
    workflow = folder / "b.json"
    workflow.write_text("{}", encoding="utf-8")

    first = workflow_manifest.identify(str(workflow))
    second = workflow_manifest.identify(str(workflow))
    assert first is not None and second is not None
    assert first.id == second.id
    assert first.id == workflow_manifest.stable_id_for_path("通用工作流/b.json")
    assert first.source == "file"


def test_custom_content_uses_content_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "library_root", tmp_path)

    first = workflow_manifest.identify("custom://abc", '{"a": 1}')
    second = workflow_manifest.identify("custom://abc", '{"a": 2}')
    assert first is not None and second is not None
    assert first.id.startswith("custom-")
    assert first.id != second.id
    assert first.source == "custom"


def test_missing_path_without_content_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "library_root", tmp_path)
    assert workflow_manifest.identify(str(tmp_path / "nope.json")) is None
