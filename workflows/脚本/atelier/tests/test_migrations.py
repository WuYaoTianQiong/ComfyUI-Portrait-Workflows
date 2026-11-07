"""迁移框架测试：版本记录、幂等、失败回滚。

这些用例保护的是重构期的地基：任何一次 schema 改动都靠它保证
"版本号推进了 = 结构真的改了"，而不是被 `_migrate_column` 的吞异常悄悄糊过去。
"""

import pytest

from app.models import MIGRATIONS, db
from app.services.migrations import applied_versions, apply_migrations


def test_schema_version_recorded():
    """conftest 里已经 init_db 过，MIGRATIONS 里的版本必须都已登记。"""
    assert applied_versions(db) == [version for version, _, _ in MIGRATIONS]


def test_apply_migrations_is_idempotent():
    """再跑一次不应重复应用任何迁移。"""
    assert apply_migrations(db, MIGRATIONS) == []


def test_v1_creates_partial_unique_index():
    """部分唯一索引是 ON CONFLICT 写入的前提，缺了所有出图入库都会静默失败。"""
    row = db.execute_sql(
        "SELECT sql FROM sqlite_master WHERE type='index' "
        "AND name='gen_history_filename_subfolder_img_type'"
    ).fetchone()
    assert row is not None, "部分唯一索引缺失"
    assert "WHERE is_deleted = 0" in row[0].replace("\n", " ")


def test_failed_migration_rolls_back_and_is_not_recorded():
    """迁移中途抛错：整体回滚、不写版本号，下次启动才会重试。"""

    def boom(_db):
        _db.execute_sql("CREATE TABLE _mig_probe (id INTEGER)")
        raise RuntimeError("故意失败")

    with pytest.raises(RuntimeError):
        apply_migrations(db, [(99, "失败用例", boom)])

    assert 99 not in applied_versions(db)
    probe = db.execute_sql(
        "SELECT name FROM sqlite_master WHERE name='_mig_probe'"
    ).fetchone()
    assert probe is None, "迁移失败后 DDL 没有回滚"


def test_v5_normalizes_legacy_quality_keys():
    """历史库里的 2K..12K/high 必须落成倍率键，且重复执行不改坏。"""
    from app.models import GenJob, _migrate_v5_quality_keys

    job = GenJob.create(
        job_type="single", status="done", title="画质键", total=1,
        done_count=1, error_count=0, items="[]", quality="8K",
    )
    _migrate_v5_quality_keys(db)
    assert GenJob.get_by_id(job.id).quality == "1.5x"

    _migrate_v5_quality_keys(db)
    assert GenJob.get_by_id(job.id).quality == "1.5x"
