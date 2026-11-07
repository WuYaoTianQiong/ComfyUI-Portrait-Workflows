"""P0 文件一致性回归：软删不复活、缩略图不串图、媒体只读图片。"""
from app.config import settings


def _write_output(name: str, data: bytes = b"x") -> None:
    path = settings.output_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_soft_delete_is_not_resurrected_by_disk_scan(api, seed_history):
    from app.models import Image
    from app.routers import images as images_router
    from app.services.tombstones import tombstone_key, tombstoned_keys

    _write_output("deleted_but_on_disk.png")
    row = seed_history(filename="deleted_but_on_disk.png")

    assert api.delete(f"/api/images/{row.id}").status_code == 200
    assert tombstone_key("deleted_but_on_disk.png") in tombstoned_keys()

    images_router._sync_disk_orphans(force=True)

    live = Image.select().where(Image.is_deleted == False).count()
    assert live == 0, "软删除的图不能被磁盘扫描重新入库"


def test_tombstone_survives_row_purge(api, seed_history):
    from app.models import Image
    from app.routers import images as images_router

    _write_output("purged_then_scan.png")
    row = seed_history(filename="purged_then_scan.png")

    assert api.delete(f"/api/images/{row.id}").status_code == 200
    Image.delete().where(Image.id == row.id).execute()

    images_router._sync_disk_orphans(force=True)

    assert Image.select().where(Image.filename == "purged_then_scan.png").count() == 0


def test_restore_clears_tombstone(api, seed_history):
    from app.models import Image
    from app.services.tombstones import tombstoned_keys, tombstone_key

    _write_output("restored.png")
    row = seed_history(filename="restored.png")
    api.delete(f"/api/images/{row.id}")

    resp = api.post(f"/api/images/{row.id}/restore")

    assert resp.status_code == 200
    assert tombstone_key("restored.png") not in tombstoned_keys()
    assert Image.get_by_id(row.id).is_deleted is False


def test_thumbnail_prefix_does_not_collide():
    from app.services.thumbnail import _thumb_prefix, clear_thumbnails_for, THUMBNAIL_DIR

    first = _thumb_prefix("a_b", "c", "output")
    second = _thumb_prefix("a", "b_c", "output")
    assert first != second, "下划线拼接会让 a_b/c 与 a/b_c 互删"

    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
    keep = THUMBNAIL_DIR / f"{second}_300_1_1_v2.webp"
    gone = THUMBNAIL_DIR / f"{first}_300_1_1_v2.webp"
    keep.write_bytes(b"x")
    gone.write_bytes(b"x")
    try:
        assert clear_thumbnails_for("a_b", "c", "output") == 1
        assert not gone.exists()
        assert keep.exists(), "删除 A 不能误删 B 的缩略图"
    finally:
        keep.unlink(missing_ok=True)
        gone.unlink(missing_ok=True)


def test_media_rejects_non_image_extension(api):
    _write_output("secret.json", b'{"password": "x"}')

    resp = api.get("/api/media/image", params={
        "filename": "secret.json", "subfolder": "", "type": "output",
    })

    assert resp.status_code == 400
