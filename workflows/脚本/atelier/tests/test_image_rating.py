"""图片内容分级契约：不逐张人工标，继承来源提示词的三态口径。

口径见 `app/services/asset_meta.py`：
- 图片显式覆盖 > 来源提示词分级（nsfw / safe / pending）> 安全；
- 列表 / 全选 id / 分面必须同口径（否则"筛出来 3 张、全选选到 5 张"）；
- 未关联提示词的历史图按安全处理，仍可单张覆盖成 18+。
"""
from __future__ import annotations

import pytest

from app.services import asset_meta


@pytest.fixture()
def rated_images(api, seed_prompt, seed_history):
    """一组覆盖三种分级 + 一张未关联提示词的图片。"""
    pending_prompt = seed_prompt(name="泳装", prompt="【人物服饰】泳装", tags="泳装")
    nsfw_prompt = seed_prompt(name="显式18+", prompt="【人物服饰】成人向", tags="18+")
    asset_meta.set_override("prompt", str(nsfw_prompt.id), rating="nsfw")
    safe_prompt = seed_prompt(name="普通", prompt="【人物服饰】白衬衫", tags="日常")

    return {
        "pending": seed_history(filename="pending_00001_.png", prompt_id=pending_prompt.id),
        "nsfw": seed_history(filename="nsfw_00001_.png", prompt_id=nsfw_prompt.id),
        "safe": seed_history(filename="safe_00001_.png", prompt_id=safe_prompt.id),
        "orphan": seed_history(filename="orphan_00001_.png"),
    }


def test_image_inherits_prompt_rating(api, rated_images):
    """图片跟着来源提示词走：提示词标了 18+，它出的图也是 18+。"""
    expected = {
        "nsfw": {rated_images["nsfw"].id},
        "pending": {rated_images["pending"].id},
        "safe": {rated_images["safe"].id, rated_images["orphan"].id},
    }
    for rating, ids in expected.items():
        body = api.get("/api/images", params={"content_rating": rating}).json()
        assert {item["id"] for item in body["items"]} == ids
        assert all(item["content_rating"] == rating for item in body["items"])


def test_image_list_ids_and_stats_share_one_rule(api, rated_images):
    """列表 / 全选 id / 分面 / 统计必须同一口径。"""
    ids = api.get("/api/images/ids", params={"content_rating": "nsfw"}).json()["ids"]
    assert ids == [rated_images["nsfw"].id]

    listed = api.get("/api/images", params={"content_rating": "nsfw"}).json()["items"]
    assert [item["id"] for item in listed] == ids

    stats = api.get("/api/assets/stats").json()["image"]
    assert stats == {"total": 4, "nsfw": 1, "pending": 1, "safe": 2}


def test_image_override_beats_prompt_rating(api, rated_images):
    """单张覆盖优先：提示词是待确认，但人工看图确认安全就能放行。"""
    asset_meta.set_override("image", str(rated_images["pending"].id), rating="safe")

    safe_ids = {
        item["id"]
        for item in api.get("/api/images", params={"content_rating": "safe"}).json()["items"]
    }
    assert rated_images["pending"].id in safe_ids

    pending_ids = {
        item["id"]
        for item in api.get("/api/images", params={"content_rating": "pending"}).json()["items"]
    }
    assert rated_images["pending"].id not in pending_ids


def test_empty_result_is_not_a_sql_error(api, seed_prompt, seed_history):
    """没有任何 nsfw 图时筛选要返回空列表，不能因为 IN () 触发 500。"""
    seed_history(filename="only_safe_00001_.png", prompt_id=seed_prompt().id)
    resp = api.get("/api/images", params={"content_rating": "nsfw"})
    assert resp.status_code == 200
    assert resp.json()["items"] == []
    assert resp.json()["total"] == 0


def test_ratings_for_accepts_single_row(api, seed_history):
    """单条路径（详情页）与批量路径结果一致。"""
    image = seed_history(filename="single_00001_.png")
    assert asset_meta.image_ratings_for([image]) == {image.id: "safe"}
