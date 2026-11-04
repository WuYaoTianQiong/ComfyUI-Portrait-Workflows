"""参考图上传（M3）：落盘、去重、白名单、大小上限、HEIC 改名、路径安全。

所有用例都指向临时目录，不写入真实 `library_root/uploads`。
"""
from __future__ import annotations

import io

from pathlib import Path

import pytest
from PIL import Image

from app.config import settings
from app.services import image_formats, uploads  # noqa: F401  image_formats 注册 HEIF 解码
from app.services.workflow_parser import inject_input_image


def png_bytes(size=(64, 48), color=(30, 120, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def heic_bytes(size=(64, 48), color=(200, 80, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="HEIF")
    return buf.getvalue()


@pytest.fixture()
def upload_root(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "library"
    (root / "uploads").mkdir(parents=True)
    monkeypatch.setattr(settings, "library_root", root)
    return root / "uploads"


def _post(api, filename: str, data: bytes):
    return api.post(
        "/api/reference/uploads",
        files={"file": (filename, data, "application/octet-stream")},
    )


def test_png_upload_lands_in_server_dir_with_size(api, upload_root):
    data = png_bytes()
    resp = _post(api, "参考图.png", data)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["name"] == "参考图.png"
    assert body["width"] == 64 and body["height"] == 48
    assert body["dedup"] is False
    assert body["bytes"] > 0

    path = Path(body["path"])
    assert path.parent == upload_root
    assert path.is_file()
    assert path.name.endswith(".png")
    # 文件名由 sha1 前 12 位生成，不接受客户端命名
    assert len(path.stem) == 12 and all(c in "0123456789abcdef" for c in path.stem)
    assert path.read_bytes() == data


def test_same_content_is_deduped(api, upload_root):
    data = png_bytes(color=(10, 20, 30))
    first = _post(api, "a.png", data).json()
    second = _post(api, "另一个名字.png", data).json()

    assert first["dedup"] is False
    assert second["dedup"] is True
    assert second["path"] == first["path"]
    assert second["width"] == first["width"]
    assert len(list(upload_root.iterdir())) == 1


def test_non_image_with_image_extension_is_rejected(api, upload_root):
    resp = _post(api, "fake.png", b"not an image at all")
    assert resp.status_code == 400
    assert "无法识别" in resp.json()["detail"]
    assert not any(upload_root.iterdir())


def test_unsupported_extension_is_rejected(api, upload_root):
    resp = _post(api, "note.txt", b"hello")
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "不支持的文件类型" in detail
    assert "png" in detail


@pytest.mark.parametrize(
    "filename",
    ["../escape.png", "sub/dir/a.png", "C:/Windows/a.png", "a:b.png", ".."],
)
def test_path_like_filenames_are_rejected(api, upload_root, filename):
    resp = _post(api, filename, png_bytes())
    assert resp.status_code == 400
    assert "文件名" in resp.json()["detail"]
    assert not any(upload_root.iterdir())


def test_oversized_file_is_rejected(api, upload_root):
    too_big = b"\0" * (uploads.MAX_UPLOAD_BYTES + 1)
    resp = _post(api, "big.png", too_big)
    assert resp.status_code == 400
    assert "25MB" in resp.json()["detail"]
    assert not any(upload_root.iterdir())


def test_empty_file_is_rejected(api, upload_root):
    resp = _post(api, "empty.png", b"")
    assert resp.status_code == 400
    assert "为空" in resp.json()["detail"]


@pytest.mark.skipif(not image_formats.heif_available(), reason="缺少 pillow-heif")
def test_heic_with_jpg_extension_is_converted_to_png(api, upload_root):
    data = heic_bytes(size=(80, 60))
    resp = _post(api, "截图.jpg", data)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    path = Path(body["path"])
    assert path.suffix == ".png"
    with Image.open(path) as img:
        assert img.format == "PNG"
        assert img.size == (80, 60)
    assert (body["width"], body["height"]) == (80, 60)

    # 同一内容的原始 .heic 再传一次：按 sha1 去重，复用同一份 PNG
    again = _post(api, "原始.heic", data).json()
    assert again["dedup"] is True
    assert again["path"] == body["path"]
    assert len(list(upload_root.iterdir())) == 1


def test_uploaded_file_can_be_injected_into_comfyui_input(api, upload_root, tmp_path):
    body = _post(api, "slot.png", png_bytes(size=(32, 16))).json()

    wf = {"1": {"class_type": "LoadImage", "inputs": {"image": "x"}}}
    dest_dir = tmp_path / "comfy_input"
    name = inject_input_image(wf, body["path"], str(dest_dir), node_id="1", dest_name="slot.png")

    assert wf["1"]["inputs"]["image"] == "slot.png"
    with Image.open(dest_dir / name) as img:
        assert img.size == (32, 16)


def test_save_upload_accepts_injected_root(tmp_path):
    # 服务层可直接指定 root（测试与脚本复用），不需要改全局 settings
    root = tmp_path / "custom"
    result = uploads.save_upload("x.png", png_bytes(), root=root)
    assert Path(result["path"]).parent == root / "uploads"
    assert Path(result["path"]).is_file()


def test_service_rejects_heic_when_decoder_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(image_formats, "_HEIF_AVAILABLE", False)
    with pytest.raises(uploads.UploadError) as exc:
        uploads.save_upload("x.heic", b"\0" * 32, root=tmp_path / "lib")
    assert "pillow-heif" in str(exc.value)
    assert not any((tmp_path / "lib" / "uploads").iterdir())


def test_security_error_does_not_leave_temp_files(api, upload_root):
    # 伪造扩展名 + 内容解码失败：临时文件必须清理干净
    _post(api, "bad.png", b"\x89PNG\r\n\x1a\nbroken")
    assert list(upload_root.glob(".incoming-*")) == []