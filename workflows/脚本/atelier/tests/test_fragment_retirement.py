"""fragments 表与旧端点已退役；统计改为实时碎片池口径。"""
from app.models import db


def test_fragments_table_and_endpoint_are_gone(api, seed_prompt):
    row = db.execute_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='fragments'"
    ).fetchone()
    assert row is None, "fragments 表应已由 v6 迁移删除"
    assert api.get("/api/fragments").status_code == 404


def test_stats_counts_live_fragment_pool(api, seed_prompt):
    seed_prompt(prompt="【人物面部】a\n\n【画质技术】b")
    stats = api.get("/api/system/stats").json()
    assert stats["fragment_count"] == 2
