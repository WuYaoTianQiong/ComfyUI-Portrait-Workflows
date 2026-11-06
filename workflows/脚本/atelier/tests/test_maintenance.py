"""墓碑回收：关联表、缩略图、标签计数都要一起清干净。"""
from datetime import datetime


def test_purge_tombstones_cleans_entity_tags_thumbnails_and_counts(api, seed_history):
    from app.models import EntityTag, Image, Tag
    from app.services import maintenance
    from app.services.thumbnail import THUMBNAIL_DIR

    old = seed_history(filename="old.png")
    live = seed_history(filename="live.png")
    Image.update(is_deleted=True, created_at=datetime(2020, 1, 1)).where(
        Image.id == old.id
    ).execute()

    tag = Tag.create(name="墓碑标签")
    EntityTag.create(entity_type="image", entity_id=old.id, tag=tag.id)
    EntityTag.create(entity_type="image", entity_id=live.id, tag=tag.id)
    Tag.update(usage_count=99).where(Tag.id == tag.id).execute()

    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
    thumb = THUMBNAIL_DIR / "old.png__output_999_1_100.webp"
    thumb.write_bytes(b"x")
    try:
        result = maintenance.purge_tombstones(keep_days=7, dry_run=False)
        assert result["deleted"] == 1
        assert Image.get_or_none(Image.id == old.id) is None
        assert EntityTag.select().where(EntityTag.entity_id == old.id).count() == 0
        assert not thumb.exists()
        assert Tag.get_by_id(tag.id).usage_count == 1
    finally:
        thumb.unlink(missing_ok=True)

def test_rotate_backups_never_deletes_manual_restore_points(tmp_path, monkeypatch):
    """轮转只作用于 *.db.startup_*；人工恢复点 *.db.pre_* 永不自动删除。"""
    from app.config import settings
    from app.services import maintenance

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    d = tmp_path / "backups"
    d.mkdir()

    manual = [d / f"prompts.db.pre_cleanup_20260101_00000{i}" for i in range(2)]
    auto = [d / f"prompts.db.startup_20260101_0000{i:02d}" for i in range(3)]
    for p in manual + auto:
        p.write_bytes(b"x")

    result = maintenance.rotate_backups(keep=2)

    assert all(p.exists() for p in manual), "人工恢复点不得被轮转删除"
    assert sum(1 for p in auto if p.exists()) == 2, "自动备份应按 keep 保留 2 个"
    assert result["removed"] == 1
    assert len(maintenance.list_auto_backups()) == 2
