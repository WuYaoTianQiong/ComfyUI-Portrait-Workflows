"""资产元数据覆盖层契约：18+ 三态分级、姿势覆盖、批量写入。

口径见 `app/services/asset_meta.py`：
- 显式 `nsfw` / `safe` 落库；
- 关键词命中但未显式标记 = `pending`（待确认，安全模式隐藏但不写库）；
- 姿势覆盖层可改写来源默认分级、可用性与人数风险。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import settings
from app.models import (
    AssetOverride,
    _PAIR_POSE_RISK_SEEDS,
    _POSE_USABILITY_SEEDS,
    _migrate_v9_asset_overrides,
    _migrate_v10_pose_metrics,
    db,
)
from app.services import asset_meta
from app.services import reference_library as rl


def _write_json(path: Path, payload: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


POSE_ITEMS = [
    {
        "id": "P001_front",
        "体系": "日常",
        "姿势编号": "P001",
        "分类": "站姿",
        "姿势名称": "正面站姿",
        "角度": "正面",
        "缩略图": "thumbs/P001_front.jpg",
        "原图": "img/P001_front.png",
        "检索": "P001_front 日常 站姿 正面站姿 正面",
    },
    {
        "id": "P001_side",
        "体系": "日常",
        "姿势编号": "P001",
        "分类": "站姿",
        "姿势名称": "侧身站姿",
        "角度": "侧面",
        "缩略图": "thumbs/P001_side.jpg",
        "原图": "img/P001_side.png",
        "检索": "P001_side 日常 站姿 侧身站姿 侧面",
    },
    {
        "id": "full_sexy_P002_front",
        "体系": "全身单人・性感系",
        "姿势编号": "P002",
        "分类": "站姿",
        "姿势名称": "S形站姿",
        "角度": "正面",
        "缩略图": "thumbs/full_sexy_P002_front.jpg",
        "原图": "img/full_sexy_P002_front.png",
        "检索": "full_sexy_P002_front 全身单人・性感系 站姿 S形站姿 正面",
    },
]


@pytest.fixture()
def pose_root(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "ai-pose-gallery-zh"
    _write_json(root / "data" / "pose-zh.json", POSE_ITEMS)
    for library in ("costume", "portrait", "costume-anime"):
        _write_json(root / "data" / f"{library}-zh.json", [])
    monkeypatch.setattr(settings, "reference_root", root)
    monkeypatch.setattr(settings, "pose_extra_dir", None)
    monkeypatch.setattr(settings, "pose_vnccs_dir", None)
    monkeypatch.setattr(settings, "costume_character_dir", None)
    monkeypatch.setattr(settings, "hair_character_dir", None)
    monkeypatch.setattr(settings, "reference_allow_nsfw", False)
    rl.clear_cache()
    yield root
    rl.clear_cache()


@pytest.fixture()
def vnccs_root(tmp_path: Path, pose_root: Path, monkeypatch) -> Path:
    """最小的 VNCCS PoseLibrary 目录：只有白模 webp，没有元数据。"""
    root = tmp_path / "PoseLibrary"
    for repo, category, stem in (
        ("MIUProject__VNCCS_PoseLibrary_Main", "站姿", "A001"),
        ("MIUProject__VNCCS_PoseLibrary_Main", "站姿", "A002"),
        ("Totemistyk__General_Poses_PoseStudio", "Uncategorized", "B001"),
    ):
        folder = root / repo / category
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{stem}.webp").write_bytes(b"x")
    monkeypatch.setattr(settings, "pose_vnccs_dir", root)
    rl.clear_cache()
    yield root
    rl.clear_cache()


def test_migration_moves_explicit_18_tag(api, seed_prompt):
    """只有显式 `18+` 标签迁移；标签文本保持原样。"""
    prompt = seed_prompt(tags="18+,卧室")

    _migrate_v9_asset_overrides(db)
    _migrate_v9_asset_overrides(db)  # 可重复执行

    rows = list(
        AssetOverride.select().where(
            (AssetOverride.asset_type == "prompt")
            & (AssetOverride.asset_key == str(prompt.id))
        )
    )
    assert len(rows) == 1
    assert rows[0].rating == "nsfw"
    assert prompt.tags == "18+,卧室"


def test_prompt_content_rating_three_states(api, seed_prompt):
    safe = seed_prompt(name="安全", prompt="【人物面部】普通面部")
    pending = seed_prompt(name="待确认", prompt="【人物面部】普通面部", tags="比基尼")
    explicit = seed_prompt(name="显式", prompt="【人物面部】普通面部", tags="泳装")
    asset_meta.set_override("prompt", str(explicit.id), rating="nsfw")

    expected = {
        "nsfw": {explicit.id},
        "pending": {pending.id},
        "safe": {safe.id},
    }
    for rating, ids in expected.items():
        body = api.get("/api/prompts", params={"content_rating": rating}).json()
        assert {row["id"] for row in body["prompts"]} == ids
        assert all(row["content_rating"] == rating for row in body["prompts"])


def test_composer_safe_mode_hides_nsfw_and_pending(api, seed_prompt):
    seed_prompt(prompt="【场景环境】安全场景")
    seed_prompt(prompt="【场景环境】待确认场景", tags="泳装")
    explicit = seed_prompt(prompt="【场景环境】显式敏感场景", tags="普通")
    asset_meta.set_override("prompt", str(explicit.id), rating="nsfw")

    safe = api.get(
        "/api/composer/fragments", params={"safe_mode": "1"}
    ).json()["grouped"]["场景环境"]
    contents = {entry["content"] for entry in safe}
    assert contents == {"安全场景"}

    full = api.get(
        "/api/composer/fragments", params={"safe_mode": "0"}
    ).json()["grouped"]["场景环境"]
    assert {entry["content"] for entry in full} == {
        "安全场景", "待确认场景", "显式敏感场景",
    }


def test_pose_override_rewrites_rating_usable_and_risk(pose_root):
    items = {record["id"]: record for record in rl._items_with_overrides("pose")}
    assert items["full_sexy_P002_front"]["rating"] == "nsfw"
    assert items["P001_front"]["rating"] == "safe"

    # 把体系默认 18+ 的条目改成 safe → 安全模式下可见
    asset_meta.set_override("pose", "full_sexy_P002_front", rating="safe")
    visible = {record["id"] for record in rl._visible_items("pose")}
    assert "full_sexy_P002_front" in visible

    # 把默认安全条目改成 18+ → 安全模式下隐藏
    asset_meta.set_override("pose", "P001_front", rating="nsfw")
    visible = {record["id"] for record in rl._visible_items("pose")}
    assert "P001_front" not in visible

    # 可用性与人数风险走覆盖层
    asset_meta.set_override(
        "pose", "P001_side", usable=False, usable_note="姿势不跟随", risk="multi",
    )
    item = rl.get_item("pose", "P001_side")
    assert item["usable"] is False
    assert item["usable_note"] == "姿势不跟随"
    assert item["risk"] == "multi"


def test_vnccs_poses_are_readonly_and_unusable_by_default(vnccs_root: Path):
    """VNCCS 白模姿势只读接入：可见可浏览，但默认不进出图候选。"""
    items = [r for r in rl._items_with_overrides("pose") if r["source"] == "vnccs"]
    assert len(items) == 3
    assert all(r["usable"] is False for r in items)
    assert all(r["usable_note"] for r in items)
    # 分组取顶层仓库包，未在 VNCCS_REPO_META 里的按目录名兜底
    assert {r["group"] for r in items} == {"MIU 主姿势库", "通用姿势"}

    # 实测确认后可逐条放行：覆盖层优先级高于来源默认
    key = items[0]["id"]
    asset_meta.set_override("pose", key, usable=True)
    item = rl.get_item("pose", key)
    assert item["usable"] is True
    assert item["usable_note"] == ""


def test_migration_v10_seeds_merge_without_overwriting_manual_edits(api):
    """v10：人数风险 / 可用性进覆盖表；只补空缺，人工判定永远优先。"""
    asset_meta.set_override("pose", "psl-D003", rating="safe", usable=True)
    asset_meta.set_override("pose", "psl-D046", usable=True, usable_note="我这边跑得动")

    _migrate_v10_pose_metrics(db)
    _migrate_v10_pose_metrics(db)  # 可重复执行

    rows = {
        row.asset_key: row
        for row in AssetOverride.select().where(AssetOverride.asset_type == "pose")
    }
    assert len(rows) == len(_PAIR_POSE_RISK_SEEDS) + len(_POSE_USABILITY_SEEDS)
    # 人工分级与可用性保留，空缺的风险被种子补齐
    assert rows["psl-D003"].rating == "safe"
    assert rows["psl-D003"].usable is True
    assert rows["psl-D003"].risk == "multi"
    # 人工改过的可用性不被种子翻回「不可用」
    assert rows["psl-D046"].usable is True
    assert rows["psl-D046"].usable_note == "我这边跑得动"
    # 没人动过的条目按实测结果落库
    assert rows["psl-D042"].usable is False
    assert "姿势跟随不稳定" in rows["psl-D042"].usable_note
    assert rows["pair60_P049_diag"].risk == "missing"


def test_assets_stats_and_batch_override(api, seed_prompt):
    explicit = seed_prompt(tags="18+")
    pending = seed_prompt(tags="泳装")
    plain = seed_prompt()
    _migrate_v9_asset_overrides(db)  # 模拟启动迁移：显式 18+ 落 nsfw

    stats = api.get("/api/assets/stats").json()["prompt"]
    assert stats["total"] == 3
    assert stats["nsfw"] == 1
    assert stats["pending"] == 1
    assert stats["safe"] == 1

    resp = api.post(
        "/api/assets/overrides/batch",
        json={
            "asset_type": "prompt",
            "keys": [str(pending.id), str(plain.id)],
            "rating": "nsfw",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["updated"] == 2

    stats = api.get("/api/assets/stats").json()["prompt"]
    assert stats["nsfw"] == 3
    assert stats["pending"] == 0

    single = api.put(
        f"/api/assets/overrides/prompt/{explicit.id}", json={"rating": "safe"},
    )
    assert single.status_code == 200
    assert single.json()["rating"] == "safe"

    bad = api.put(
        f"/api/assets/overrides/prompt/{explicit.id}", json={"rating": "r18"},
    )
    assert bad.status_code == 400
