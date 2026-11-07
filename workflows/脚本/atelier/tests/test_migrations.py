"""迁移框架测试：版本记录、幂等、失败回滚。

这些用例保护的是重构期的地基：任何一次 schema 改动都靠它保证
"版本号推进了 = 结构真的改了"，而不是被 `_migrate_column` 的吞异常悄悄糊过去。
"""

import json
import sqlite3

import pytest

from app.models import MIGRATIONS, db
from app.services.migrations import applied_versions, apply_migrations, pending_versions


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


def test_pending_versions_is_read_only(tmp_path):
    """启动备份发生在 init_db 之前：只能读版本号，不能建表或写库。"""
    path = tmp_path / "before_migrate.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE schema_version ("
            " version INTEGER PRIMARY KEY, applied_at DATETIME, note TEXT)"
        )
        conn.execute("INSERT INTO schema_version(version) VALUES (3)")

    expected = [version for version, _, _ in MIGRATIONS if version > 3]
    assert pending_versions(path, MIGRATIONS) == expected

    # 库还不存在：全部迁移都算待应用
    assert pending_versions(tmp_path / "missing.db", MIGRATIONS) == [
        version for version, _, _ in MIGRATIONS
    ]


def test_v8_backfills_idempotency_and_dedupes():
    """历史键回填到列；重复键保留最新一条，其余清空列值但保留任务。"""
    from app.models import GenJob, _migrate_v8_job_idempotency

    extra = json.dumps({"idempotency_key": "dup-key", "idempotency_scope": "runs_batch"})
    old = GenJob.create(
        job_type="batch", status="done", title="旧", total=0,
        items="[]", extra=extra,
    )
    new = GenJob.create(
        job_type="batch", status="done", title="新", total=0,
        items="[]", extra=extra,
    )

    _migrate_v8_job_idempotency(db)

    old_row = GenJob.get_by_id(old.id)
    new_row = GenJob.get_by_id(new.id)
    assert old_row.idempotency_key is None
    assert new_row.idempotency_key == "dup-key"
    assert new_row.idempotency_scope == "runs_batch"

    index = db.execute_sql(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_gen_jobs_idempotency'"
    ).fetchone()
    assert index is not None


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
