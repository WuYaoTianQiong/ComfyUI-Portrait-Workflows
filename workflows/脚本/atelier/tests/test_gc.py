"""资产生命周期：派生缓存按天数回收，上传图只盘点。"""
import os
import time

from app.config import settings
from app.services import gc, uploads


def _write(path, age_days: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    stamp = time.time() - age_days * 86400
    os.utime(path, (stamp, stamp))


def test_thumbnail_gc_dry_run_then_confirm(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "thumbnail_dir", tmp_path / "thumbs")
    old = tmp_path / "thumbs" / "old.webp"
    fresh = tmp_path / "thumbs" / "fresh.webp"
    _write(old, 10)
    _write(fresh, 0)

    dry = gc.gc_thumbnails(dry_run=True, older_than_days=5)
    assert dry["eligible"] == 1
    assert dry["deleted"] == 0
    assert old.exists()

    real = gc.gc_thumbnails(dry_run=False, older_than_days=5)
    assert real["deleted"] == 1
    assert not old.exists()
    assert fresh.exists()


def test_remote_cache_gc(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "reference_cache_dir", tmp_path / "remote")
    old = tmp_path / "remote" / "a" / "image.jpg"
    fresh = tmp_path / "remote" / "b" / "image.jpg"
    _write(old, 40)
    _write(fresh, 0)

    assert gc.gc_remote_cache(dry_run=False, older_than_days=30)["deleted"] == 1
    assert not old.exists()
    assert fresh.exists()


def test_upload_temp_only_and_inventory(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    base = uploads.uploads_dir()
    temp = base / ".incoming-old"
    real = base / "kept.png"
    _write(temp, 3)
    _write(real, 30)

    assert gc.gc_upload_temp(dry_run=False, older_than_days=1)["deleted"] == 1
    assert not temp.exists()
    assert real.exists(), "用户上传图不能自动删除"

    report = gc.inventory_uploads()
    assert report["count"] == 1
    assert report["bytes"] > 0
