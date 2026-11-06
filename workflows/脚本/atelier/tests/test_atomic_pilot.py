"""原子碎片库跨源实验的契约测试。"""
from __future__ import annotations

from app.services import atomic_pilot
from app.services.costume_policy import costume_covers_lower
from app.services.fragment_syntax import FRAGMENT_TYPES


def test_sample_combo_returns_complete_compatible_bank():
    for seed in range(20):
        combo = atomic_pilot.sample_combo(seed)
        assert combo["bank_version"] >= 4
        assert [item["type"] for item in combo["fragments"]] == FRAGMENT_TYPES
        assert combo["pose_facet"] in {"stand", "walk", "sit", "lean", "kneel"}
        by_type = {item["type"]: item["content"] for item in combo["fragments"]}
        assert costume_covers_lower(by_type["人物服饰"])
        assert all("【" not in content and "\\n" not in content for content in by_type.values())
        assert combo["warning"].startswith("跨源实验")


def test_sample_combo_is_deterministic_with_seed():
    assert atomic_pilot.sample_combo(42) == atomic_pilot.sample_combo(42)


def test_atomic_recipe_endpoint(api):
    resp = api.get("/api/composer/recipes/atomic", params={"seed": "1"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [item["type"] for item in body["fragments"]] == FRAGMENT_TYPES
    assert body["bank_version"] >= 4
    assert body["pose_facet"]
    assert body["warning"].startswith("跨源实验")
