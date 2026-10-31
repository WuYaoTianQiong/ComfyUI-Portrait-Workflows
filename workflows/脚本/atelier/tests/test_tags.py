"""标签收敛测试：标签文本 → entity_tags 的同步，以及读路径是否真的走新表。

这一组用例对应 S1-2 的验收：线上曾出现「136 个标签、0 条关联」——文本、关联表、
筛选三套数据互不相干，而界面上没有任何报错。这里把三条链路都锁死。
"""


def _prompt_tag_names(prompt_id: int) -> set[str]:
    from app.models import EntityTag

    return {
        row.tag.name
        for row in EntityTag.select()
        .where((EntityTag.entity_type == "prompt") & (EntityTag.entity_id == prompt_id))
    }


def test_create_prompt_parses_tag_text(api):
    """建提示词时按逗号/分号拆标签，去重、去空白，标签不存在则自动创建。"""
    r = api.post(
        "/api/prompts",
        json={"name": "A", "prompt": "x", "tags": "夏日, 街拍 ;夏日"},
    )
    assert r.status_code == 201
    assert _prompt_tag_names(r.json()["id"]) == {"夏日", "街拍"}


def test_update_prompt_syncs_tags(api):
    """改标签文本要全量重算关联：文本里删掉的标签必须真的消失。"""
    pid = api.post(
        "/api/prompts", json={"name": "B", "prompt": "x", "tags": "夏日,街拍"}
    ).json()["id"]

    api.put(f"/api/prompts/{pid}", json={"tags": "夏日,夜景"})
    assert _prompt_tag_names(pid) == {"夏日", "夜景"}

    api.put(f"/api/prompts/{pid}", json={"tags": ""})
    assert _prompt_tag_names(pid) == set()


def test_tag_filter_uses_entity_tags(api):
    """提示词按标签筛选必须查 entity_tags（旧实现 join prompt_tags，恒为空）。"""
    from app.models import Tag

    hit = api.post(
        "/api/prompts", json={"name": "tagged", "prompt": "x", "tags": "夏日"}
    ).json()["id"]
    api.post("/api/prompts", json={"name": "clean", "prompt": "x", "tags": ""})

    tag = Tag.get(Tag.name == "夏日")
    body = api.get(f"/api/prompts?tag_ids={tag.id}").json()
    assert [p["id"] for p in body["prompts"]] == [hit]


def test_image_inherits_prompt_tags(api, seed_history):
    """图片继承来源提示词的标签后，画廊按标签筛选能命中。"""
    from app.models import Tag

    pid = api.post(
        "/api/prompts", json={"name": "src", "prompt": "x", "tags": "夏日"}
    ).json()["id"]
    img = seed_history(filename="inherit.png", prompt_id=pid)

    assert api.post(f"/api/images/{img.id}/inherit").status_code == 200

    tag = Tag.get(Tag.name == "夏日")
    assert api.get(f"/api/images/ids?tag_ids={tag.id}").json()["ids"] == [img.id]


def test_tag_counts_by_scope(api, seed_history):
    """prompt 维度数提示词、image 维度数去重图片，两者都要反映真实关联。"""
    pid = api.post(
        "/api/prompts", json={"name": "c1", "prompt": "x", "tags": "夏日,夜景"}
    ).json()["id"]
    img = seed_history(filename="c.png", prompt_id=pid)
    api.post(f"/api/images/{img.id}/inherit")

    prompt_counts = {
        t["name"]: t["prompt_count"] for t in api.get("/api/tags?count_scope=prompt").json()["tags"]
    }
    assert prompt_counts["夏日"] == 1
    assert prompt_counts["夜景"] == 1

    image_counts = {
        t["name"]: t["prompt_count"] for t in api.get("/api/tags?count_scope=image").json()["tags"]
    }
    assert image_counts["夏日"] == 1
    assert image_counts["夜景"] == 1


def test_history_tag_match_all_vs_any(api, seed_history):
    """多标签：all=交集（同时满足），any=并集（任一满足）。"""
    from app.models import EntityTag, Tag

    tag_a = Tag.create(name="甲")
    tag_b = Tag.create(name="乙")
    both = seed_history(filename="both.png")
    only_a = seed_history(filename="only_a.png")
    EntityTag.create(entity_type="image", entity_id=both.id, tag=tag_a.id)
    EntityTag.create(entity_type="image", entity_id=both.id, tag=tag_b.id)
    EntityTag.create(entity_type="image", entity_id=only_a.id, tag=tag_a.id)

    ids_all = api.get(
        f"/api/images/ids?tag_ids={tag_a.id},{tag_b.id}&tag_match=all"
    ).json()["ids"]
    ids_any = api.get(
        f"/api/images/ids?tag_ids={tag_a.id},{tag_b.id}&tag_match=any"
    ).json()["ids"]

    assert ids_all == [both.id]
    assert sorted(ids_any) == sorted([both.id, only_a.id])


def test_prompt_tag_match_all_vs_any(api):
    """提示词侧的多标签语义与画廊保持一致。"""
    from app.models import Tag

    both = api.post(
        "/api/prompts", json={"name": "both", "prompt": "x", "tags": "甲,乙"}
    ).json()["id"]
    only_a = api.post(
        "/api/prompts", json={"name": "only_a", "prompt": "x", "tags": "甲"}
    ).json()["id"]

    tag_a = Tag.get(Tag.name == "甲")
    tag_b = Tag.get(Tag.name == "乙")
    query = f"tag_ids={tag_a.id},{tag_b.id}"

    all_ids = [p["id"] for p in api.get(f"/api/prompts?{query}&tag_match=all").json()["prompts"]]
    any_ids = [p["id"] for p in api.get(f"/api/prompts?{query}&tag_match=any").json()["prompts"]]

    assert all_ids == [both]
    assert sorted(any_ids) == sorted([both, only_a])


def test_add_and_remove_prompt_tag_endpoint(api):
    """通过标签接口给提示词打/去标签时，文本与关联表必须同时更新。"""
    from app.models import Prompt, Tag

    pid = api.post("/api/prompts", json={"name": "D", "prompt": "x", "tags": ""}).json()["id"]
    tag = api.post("/api/tags", json={"name": "手工标签"}).json()["id"]

    assert api.post(f"/api/tags/{tag}/prompts/{pid}").status_code == 200
    assert "手工标签" in Prompt.get_by_id(pid).tags
    assert _prompt_tag_names(pid) == {"手工标签"}

    assert api.delete(f"/api/tags/{tag}/prompts/{pid}").status_code == 200
    assert "手工标签" not in (Prompt.get_by_id(pid).tags or "")
    assert _prompt_tag_names(pid) == set()
    assert Tag.get_by_id(tag) is not None
