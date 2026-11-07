"""AssetRef 底座：本地 / 远程 / 缺失三态。"""
from pathlib import Path

from app.config import settings
from app.services import assets


def _write(name: str, data: bytes = b"x") -> Path:
    path = settings.output_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_raw_payload_prefers_local(monkeypatch):
    path = _write("asset-local.png")
    try:
        payload = assets.raw_payload(assets.AssetRef("asset-local.png"))
        assert payload.kind == "file"
        assert payload.path == path
        assert payload.media_type == "image/png"
    finally:
        path.unlink(missing_ok=True)


def test_raw_payload_falls_back_to_remote(monkeypatch):
    monkeypatch.setattr(assets, "fetch_remote", lambda ref: (b"remote-bytes", "image/webp"))
    payload = assets.raw_payload(assets.AssetRef("asset-remote.webp"))
    assert payload.kind == "bytes"
    assert payload.data == b"remote-bytes"
    assert payload.media_type == "image/webp"


def test_payload_missing_when_local_and_remote_absent(monkeypatch):
    monkeypatch.setattr(assets, "fetch_remote", lambda ref: None)
    assert assets.raw_payload(assets.AssetRef("asset-none.png")).kind == "missing"
    assert assets.thumbnail_payload(assets.AssetRef("asset-none.png")).kind == "missing"


def test_thumbnail_uses_generated_cache_and_clamps_size(monkeypatch):
    thumb = settings.thumbnail_dir / "asset-thumb.webp"
    thumb.parent.mkdir(parents=True, exist_ok=True)
    thumb.write_bytes(b"webp")
    seen: list[int] = []

    def fake_generate(filename, subfolder, img_type, size):
        seen.append(size)
        return thumb

    monkeypatch.setattr(assets, "generate_thumbnail", fake_generate)
    payload = assets.thumbnail_payload(assets.AssetRef("asset-local.png"), 99999)
    try:
        assert payload.kind == "file"
        assert payload.path == thumb
        assert payload.cache_control == assets.IMMUTABLE
        assert seen == [1024]
    finally:
        thumb.unlink(missing_ok=True)


def test_media_timeout_maps_to_504(api, monkeypatch):
    def boom(_ref):
        raise assets.AssetTimeoutError("slow")

    monkeypatch.setattr(assets, "raw_payload", boom)
    resp = api.get("/api/media/image?filename=x.png")
    assert resp.status_code == 504
    assert "slow" in resp.json()["detail"]
