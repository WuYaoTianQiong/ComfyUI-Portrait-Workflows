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
