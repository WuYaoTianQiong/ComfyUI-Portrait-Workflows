"""AssetStore：Comfy / 参考库 / 上传图统一走 resolve / thumbnail / delete。"""
from PIL import Image as PILImage

from app.config import settings
from app.services.asset_store import (
    AssetStore,
    ComfyAssetRef,
    LibraryAssetRef,
    RemoteAssetRef,
    UploadAssetRef,
)
from app.services import uploads


def _png(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with PILImage.new("RGB", (12, 12), (30, 120, 200)) as img:
        img.save(path, "PNG")
    return path


def test_comfy_asset_resolves_and_thumbnails():
    path = _png(settings.output_dir / "asset_store_probe.png")
    store = AssetStore()
    ref = ComfyAssetRef("asset_store_probe.png", "", "output")
    try:
        payload = store.resolve(ref)
        assert payload.kind == "file"
        assert payload.path == path
        assert store.exists(ref) is True
        assert store.thumbnail(ref, 64).kind in ("file", "bytes")
    finally:
        path.unlink(missing_ok=True)


def test_upload_asset_is_confined_to_uploads_dir(tmp_path):
    upload_dir = uploads.uploads_dir()
    path = _png(upload_dir / "asset_store_upload.png")
    store = AssetStore()
    try:
        payload = store.resolve(UploadAssetRef(str(path)))
        assert payload.kind == "file"
        assert store.thumbnail(UploadAssetRef(str(path)), 64).kind == "bytes"

        outside = _png(tmp_path / "outside.png")
        assert store.resolve(UploadAssetRef(str(outside))).kind == "missing"
        assert store.delete_upload(UploadAssetRef(str(outside))) is False

        assert store.delete_upload(UploadAssetRef(str(path))) is True
        assert not path.exists()
    finally:
        path.unlink(missing_ok=True)


def test_library_asset_delegates_to_reference_resolver(monkeypatch, tmp_path):
    from app.services import reference_library

    path = _png(tmp_path / "library_thumb.png")
    monkeypatch.setattr(
        reference_library, "resolve_image",
        lambda library, item_id, kind: path,
    )
    store = AssetStore()
    ref = LibraryAssetRef("pose", "p1", "thumb")

    assert store.resolve(ref).path == path
    assert store.thumbnail(ref).kind == "file"
    assert store.exists(ref) is True


def test_library_missing_becomes_missing_payload(monkeypatch):
    from app.services import reference_library

    def boom(*_args, **_kwargs):
        raise reference_library.ReferenceImageError(404, "没有")

    monkeypatch.setattr(reference_library, "resolve_image", boom)
    assert AssetStore().resolve(LibraryAssetRef("pose", "p1")).kind == "missing"


def test_remote_asset_is_not_sync_resolved():
    store = AssetStore()
    ref = RemoteAssetRef("costume-anime", "O001", "thumb", "https://example.test/a.jpg")
    assert store.resolve(ref).kind == "missing"
    assert store.thumbnail(ref).kind == "missing"
    assert store.exists(ref) is False
