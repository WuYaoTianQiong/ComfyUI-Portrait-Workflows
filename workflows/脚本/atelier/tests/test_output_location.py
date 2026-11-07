"""出图归档位置：子目录清洗、变量展开、保存节点前缀。"""
import json
import re
from datetime import datetime

import pytest

from app.services.output_location import (
    OutputLocationError,
    apply_output_subfolder,
    expand_subfolder,
    sanitize_subfolder,
    with_subfolder,
)


def test_sanitize_subfolder_accepts_nested_chinese():
    assert sanitize_subfolder("2026-11/人像") == "2026-11/人像"
    assert sanitize_subfolder(" a\\b / c ") == "a/b/c"
    assert sanitize_subfolder("") == ""


@pytest.mark.parametrize("raw", ["..", "../x", "a/../../b", "/abs", "C:\\abs", "a:b", "a?b", "a/b/c/d"])
def test_sanitize_subfolder_rejects_escape_and_invalid(raw):
    with pytest.raises(OutputLocationError):
        sanitize_subfolder(raw)


def test_expand_subfolder_supports_variables():
    now = datetime(2026, 11, 1, 12, 0, 0)
    assert expand_subfolder(
        "{date}/{workflow}", workflow_path="F:/wf/人像\\Portrait.json", now=now
    ) == "2026-11-01/Portrait"
    assert expand_subfolder(
        "{month}/{job_id}", job_id=12, now=now
    ) == "2026-11/12"


def test_expand_subfolder_rejects_unknown_variable():
    with pytest.raises(OutputLocationError):
        expand_subfolder("{unknown}/x")
    with pytest.raises(OutputLocationError):
        expand_subfolder("{date/x}")


def test_apply_output_subfolder_prepends_without_losing_prefix():
    wf = {
        "1": {"class_type": "SaveImage", "inputs": {"filename_prefix": "orig"}},
        "2": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "video/x"}},
        "3": {"class_type": "KSampler", "inputs": {"seed": 1}},
    }
    assert apply_output_subfolder(wf, "2026-11") == 2
    assert wf["1"]["inputs"]["filename_prefix"] == "2026-11/orig"
    assert wf["2"]["inputs"]["filename_prefix"] == "2026-11/video/x"
    assert wf["3"]["inputs"]["seed"] == 1


def test_apply_output_subfolder_is_noop_when_empty():
    wf = {"1": {"class_type": "SaveImage", "inputs": {"filename_prefix": "orig"}}}
    assert apply_output_subfolder(wf, "") == 0
    assert wf["1"]["inputs"]["filename_prefix"] == "orig"


def test_with_subfolder():
    assert with_subfolder("", "fs1_a") == "fs1_a"
    assert with_subfolder("2026-11", "fs1_a") == "2026-11/fs1_a"


def test_comfyui_root_env_override_is_applied(tmp_path):
    from app.config import Settings

    root = tmp_path / "comfyui"
    (root / "output").mkdir(parents=True)
    settings = Settings(comfyui_root_env=str(root))
    assert settings.comfyui_root == root
    assert settings.output_dir == root / "output"


def test_output_dir_defaults_to_root_and_can_be_overridden(tmp_path):
    from app.config import Settings

    base = Settings()
    assert base.output_dir == base.comfyui_root / "output"

    overridden = Settings(comfyui_output_dir=tmp_path)
    assert overridden.output_dir == tmp_path
    assert base.input_dir == base.comfyui_root / "input"
    assert base.temp_dir == base.comfyui_root / "temp"


def test_disk_scan_recurses_and_stores_subfolder(api):
    from app.config import settings
    from app.models import Image
    from app.routers.images import _sync_disk_orphans

    nested = settings.output_dir / "2026-11" / "人像"
    nested.mkdir(parents=True, exist_ok=True)
    image = nested / "nested_scan.png"
    image.write_bytes(b"nested")
    try:
        _sync_disk_orphans()
        row = Image.get_or_none(
            (Image.filename == image.name) & (Image.subfolder == "2026-11/人像")
        )
        assert row is not None
        assert row.img_type == "output"
        assert _sync_disk_orphans() == 0  # 第二次不重复插入
    finally:
        image.unlink(missing_ok=True)
        import shutil

        shutil.rmtree(settings.output_dir / "2026-11", ignore_errors=True)


def test_open_output_endpoint(api, monkeypatch):
    from app.routers import system as system_router

    calls = []
    monkeypatch.setattr(system_router.sys, "platform", "win32")
    monkeypatch.setattr(system_router.os, "startfile", lambda p: calls.append(p), raising=False)

    resp = api.post("/api/system/open-output")
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True
    assert calls


def test_reveal_endpoint(api, seed_history, monkeypatch):
    from app.config import settings
    from app.routers import images as images_router

    path = settings.output_dir / "reveal_me.png"
    path.write_bytes(b"x")
    try:
        row = seed_history(filename=path.name)
        calls = []
        monkeypatch.setattr(images_router.sys, "platform", "win32")
        monkeypatch.setattr(
            images_router.subprocess, "Popen", lambda args: calls.append(args)
        )

        resp = api.post(f"/api/images/{row.id}/reveal")
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is True
        assert calls
    finally:
        path.unlink(missing_ok=True)


def test_run_text_applies_output_subfolder(api, monkeypatch):
    from app.routers import comfyui as comfy_router

    captured = {}

    def fake_push(workflow):
        captured["workflow"] = workflow
        return {"prompt_id": "pid-test"}

    from app.services import generation

    monkeypatch.setattr(generation, "push_prompt", fake_push)

    workflow = {"1": {"class_type": "SaveImage", "inputs": {"filename_prefix": "orig"}}}
    resp = api.post(
        "/api/runs/text",
        json={
            "prompt": "test",
            "workflow_path": "x.json",
            "workflow_content": json.dumps(workflow),
            "output_subfolder": "{date}/{workflow}",
        },
    )
    assert resp.status_code == 200, resp.text
    prefix = captured["workflow"]["1"]["inputs"]["filename_prefix"]
    assert re.match(r"^\d{4}-\d{2}-\d{2}/x/orig_atelier_\d+_\d+$", prefix), prefix

    bad = api.post(
        "/api/runs/text",
        json={
            "prompt": "test",
            "workflow_path": "x.json",
            "workflow_content": json.dumps(workflow),
            "output_subfolder": "../escape",
        },
    )
    assert bad.status_code == 400


def test_output_folder_listing_and_create(api):
    from app.config import settings

    listed = api.get("/api/system/output-folders")
    assert listed.status_code == 200, listed.text
    assert listed.json()["root"] == str(settings.output_dir)

    created = api.post(
        "/api/system/output-folders", json={"parent": "", "name": "2026-11"}
    )
    assert created.status_code == 200, created.text
    assert created.json()["path"] == "2026-11"

    child = api.post(
        "/api/system/output-folders", json={"parent": "2026-11", "name": "人像"}
    )
    assert child.status_code == 200, child.text
    assert child.json()["path"] == "2026-11/人像"

    listed = api.get("/api/system/output-folders", params={"path": "2026-11"})
    assert listed.status_code == 200, listed.text
    assert [d["path"] for d in listed.json()["dirs"]] == ["2026-11/人像"]

    bad = api.get("/api/system/output-folders", params={"path": "../.."})
    assert bad.status_code == 400

    import shutil

    shutil.rmtree(settings.output_dir / "2026-11", ignore_errors=True)


def test_output_config_reports_dir(api):
    from app.config import settings

    body = api.get("/api/system/config").json()
    assert body["output_dir"] == str(settings.output_dir)


def test_reveal_by_filename_without_db_id(api, monkeypatch):
    from app.config import settings
    from app.routers import images as images_router

    path = settings.output_dir / "reveal_by_name.png"
    path.write_bytes(b"x")
    try:
        calls = []
        monkeypatch.setattr(images_router.sys, "platform", "win32")
        monkeypatch.setattr(
            images_router.subprocess, "Popen", lambda args: calls.append(args)
        )
        resp = api.post(
            "/api/images/reveal",
            json={"filename": path.name, "subfolder": "", "img_type": "output"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is True
        assert calls

        bad = api.post(
            "/api/images/reveal",
            json={"filename": "x.png", "subfolder": "../..", "img_type": "output"},
        )
        assert bad.status_code == 404
    finally:
        path.unlink(missing_ok=True)


