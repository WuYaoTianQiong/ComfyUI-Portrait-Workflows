"""图片路径安全契约：任何越界路径都不能被读、写、下载。"""
from pathlib import Path

from app.config import settings


def test_safe_image_ref_accepts_nested_subfolder():
    from app.services.paths import is_safe_image_ref

    assert is_safe_image_ref("a.png", "2026-11/人像", "output")
    assert is_safe_image_ref("a.png", "a\\b", "input")
    assert is_safe_image_ref("a.png", "", "temp")


def test_safe_image_ref_rejects_traversal_and_absolute_paths():
    from app.services.paths import is_safe_image_ref

    assert not is_safe_image_ref("../secret.png", "", "output")
    assert not is_safe_image_ref("a.png", "../..", "output")
    assert not is_safe_image_ref("a.png", "a/../../b", "output")
    assert not is_safe_image_ref("a.png", "/abs", "output")
    assert not is_safe_image_ref("a.png", "C:\\abs", "output")
    assert not is_safe_image_ref("dir/a.png", "", "output")
    assert not is_safe_image_ref("C:/x.png", "", "output")
    assert not is_safe_image_ref("a.png", "", "unknown")


def test_resolve_image_path_never_escapes_output(tmp_path):
    from app.services.paths import resolve_image_path

    secret = settings.comfyui_root.parent / "outside_secret.png"
    secret.write_bytes(b"secret")
    try:
        assert resolve_image_path(secret.name, "..", "output") is None
        assert resolve_image_path("../outside_secret.png", "", "output") is None
        assert resolve_image_path(str(secret), "", "output") is None
    finally:
        secret.unlink(missing_ok=True)


def test_media_endpoint_rejects_traversal(api):
    for params in (
        {"filename": "a.png", "subfolder": ".."},
        {"filename": "../a.png", "subfolder": ""},
        {"filename": "a.png", "subfolder": "C:\\Windows"},
    ):
        resp = api.get("/api/media/image", params=params)
        assert resp.status_code == 400, (params, resp.status_code, resp.text)


def test_browser_image_only_serves_image_extensions(api, tmp_path):
    txt = tmp_path / "secret.txt"
    txt.write_text("not an image", encoding="utf-8")
    png = tmp_path / "ok.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")

    blocked = api.get("/api/browser/image", params={"path": str(txt)})
    assert blocked.status_code == 200
    assert blocked.headers["content-type"].startswith("image/svg+xml")

    served = api.get("/api/browser/image", params={"path": str(png)})
    assert served.status_code == 200
    assert served.content == b"\x89PNG\r\n\x1a\n"


def test_download_respects_img_type(api, seed_history):
    src = settings.comfyui_root / "input" / "from_input.png"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"input-image")
    try:
        row = seed_history(filename=src.name, img_type="input")
        resp = api.get(f"/api/images/{row.id}/download")
        assert resp.status_code == 200
        assert resp.content == b"input-image"
    finally:
        src.unlink(missing_ok=True)


def test_cors_does_not_allow_arbitrary_origin(api):
    resp = api.get("/api/system/config", headers={"Origin": "https://evil.example"})
    assert resp.headers.get("access-control-allow-origin") in (None, "")
