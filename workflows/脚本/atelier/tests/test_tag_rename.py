"""标签改名/删除必须同步提示词文本，避免旧名在下次保存时复活。"""
from app.models import EntityTag, Prompt, Tag
from app.services.tagging import sync_prompt_tags


def _prompt_with_tags(seed_prompt, tags: str):
    prompt = seed_prompt(tags=tags)
    sync_prompt_tags(prompt.id, tags)
    return prompt


def test_rename_tag_rewrites_prompt_text(api, seed_prompt):
    prompt = _prompt_with_tags(seed_prompt, "甲，乙")
    tag = Tag.get(Tag.name == "甲")

    resp = api.put(f"/api/tags/{tag.id}", json={"name": "丙"})
    assert resp.status_code == 200, resp.text

    row = Prompt.get_by_id(prompt.id)
    assert row.tags == "丙, 乙"
    assert Tag.get_or_none(Tag.name == "甲") is None
    assert Tag.get_or_none(Tag.name == "丙") is not None

    # 用改名后的文本再保存一次，旧名不会复活
    api.put(f"/api/prompts/{prompt.id}", json={"tags": row.tags})
    assert Tag.get_or_none(Tag.name == "甲") is None
    assert any(t.name == "丙" for t in Tag.select())


def test_rename_tag_keeps_spaced_names(api, seed_prompt):
    prompt = _prompt_with_tags(seed_prompt, "Moody Photography；乙")
    tag = Tag.get(Tag.name == "Moody Photography")

    resp = api.put(f"/api/tags/{tag.id}", json={"name": "Moody Photo"})
    assert resp.status_code == 200, resp.text
    assert Prompt.get_by_id(prompt.id).tags == "Moody Photo, 乙"


def test_rename_to_existing_tag_is_rejected(api, seed_prompt):
    _prompt_with_tags(seed_prompt, "甲；乙")
    tag = Tag.get(Tag.name == "甲")

    resp = api.put(f"/api/tags/{tag.id}", json={"name": "乙"})
    assert resp.status_code == 400
    assert "已存在" in resp.json()["detail"]


def test_delete_tag_removes_text_and_associations(api, seed_prompt):
    prompt = _prompt_with_tags(seed_prompt, "甲, 乙")
    tag = Tag.get(Tag.name == "甲")
    assert EntityTag.select().where(EntityTag.tag == tag.id).count() == 1

    resp = api.delete(f"/api/tags/{tag.id}")
    assert resp.status_code == 200, resp.text

    assert Prompt.get_by_id(prompt.id).tags == "乙"
    assert Tag.get_or_none(Tag.name == "甲") is None
