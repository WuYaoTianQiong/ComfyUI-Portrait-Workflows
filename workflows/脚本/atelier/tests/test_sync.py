"""历史同步互斥与磁盘增量扫描。"""
import shutil


def test_sync_all_skips_when_another_scan_holds_lock(monkeypatch):
    from app.routers import images

    called = []
    monkeypatch.setattr(images, "_sync_comfyui_history", lambda: called.append("history") or 1)
    monkeypatch.setattr(
        images, "_sync_disk_orphans", lambda force=False: called.append(("disk", force)) or 1
    )

    images._sync_lock.acquire()
    try:
        assert images.sync_all(force=True) == 0
        assert called == []
    finally:
        images._sync_lock.release()


def test_disk_scan_does_not_duplicate_and_force_recovers(api):
    from app.config import settings
    from app.models import Image
    from app.routers import images

    images._dir_mtimes.clear()
    images._last_full_scan = -1e9
    nested = settings.output_dir / "incremental" / "a"
    nested.mkdir(parents=True, exist_ok=True)
    image = nested / "incremental.png"
    image.write_bytes(b"x")
    try:
        images._sync_disk_orphans(force=True)
        row = Image.get_or_none(
            (Image.filename == image.name) & (Image.subfolder == "incremental/a")
        )
        assert row is not None

        # 非强制扫描：目录 mtime 在 Windows 上可能抖动，允许重扫，但绝不能重复入库
        images._sync_disk_orphans(force=False)
        count = Image.select().where(
            (Image.filename == image.name) & (Image.subfolder == "incremental/a")
        ).count()
        assert count == 1

        # 记录被删、文件仍在：强制全量扫描能把它捡回来
        row.delete_instance()
        images._sync_disk_orphans(force=True)
        assert Image.get_or_none(
            (Image.filename == image.name) & (Image.subfolder == "incremental/a")
        ) is not None
    finally:
        shutil.rmtree(settings.output_dir / "incremental", ignore_errors=True)
        images._dir_mtimes.clear()
        images._last_full_scan = -1e9
