"""临时试跑「存为提示词」后把整批图认领过去的归属接口。

试跑用 source_prompt_id=0 出图时 prompt_id 为空，新建提示词后若不认领，
新提示词的出图历史永远是空的 —— 这是「试 → 满意 → 存」闭环最后一环。
"""


def _image(filename, prompt_id=None, deleted=False):
    from app.models import Image

    return Image.create(
        filename=filename, subfolder="", img_type="output",
        job_id=None, prompt_id=prompt_id, comfyui_prompt_id=filename,
        view_url=f"/{filename}", preview="", prompt_params=None,
        captured_at=None, source="single", is_deleted=deleted,
    )


def test_link_moves_whole_batch(api, seed_prompt):
    prompt = seed_prompt(name="试跑存下来的")
    a = _image("trial_a.png")
    b = _image("trial_b.png")

    resp = api.post("/api/images/link_prompt", json={
        "image_ids": [a.id, b.id], "prompt_id": prompt.id,
    })
    assert resp.status_code == 200
    assert resp.json() == {"success": True, "linked": 2}

    from app.models import Image

    assert Image.get(Image.id == a.id).prompt_id == prompt.id
    assert Image.get(Image.id == b.id).prompt_id == prompt.id


def test_link_overwrites_previous_owner(api, seed_prompt):
    old = seed_prompt(name="旧载体")
    new = seed_prompt(name="新提示词")
    img = _image("owned.png", prompt_id=old.id)

    api.post("/api/images/link_prompt", json={"image_ids": [img.id], "prompt_id": new.id})

    from app.models import Image

    assert Image.get(Image.id == img.id).prompt_id == new.id


def test_unknown_prompt_is_404(api):
    img = _image("orphan.png")
    resp = api.post("/api/images/link_prompt", json={"image_ids": [img.id], "prompt_id": 999999})
    assert resp.status_code == 404

    from app.models import Image

    assert Image.get(Image.id == img.id).prompt_id is None


def test_deleted_and_missing_ids_are_skipped(api, seed_prompt):
    prompt = seed_prompt()
    alive = _image("alive.png")
    gone = _image("gone.png", deleted=True)

    resp = api.post("/api/images/link_prompt", json={
        "image_ids": [alive.id, gone.id, 999999], "prompt_id": prompt.id,
    })
    assert resp.json()["linked"] == 1

    from app.models import Image

    assert Image.get(Image.id == gone.id).prompt_id is None


def test_empty_batch_is_noop(api, seed_prompt):
    prompt = seed_prompt()
    resp = api.post("/api/images/link_prompt", json={"image_ids": [], "prompt_id": prompt.id})
    assert resp.status_code == 200
    assert resp.json() == {"success": True, "linked": 0}


def test_inherits_prompt_taxonomy(api, seed_prompt):
    prompt = seed_prompt(name="带分类的", tags="女性,衬衫")
    img = _image("inherit.png")

    api.post("/api/images/link_prompt", json={"image_ids": [img.id], "prompt_id": prompt.id})

    from app.models import EntityTag

    names = list(
        EntityTag.select()
        .where((EntityTag.entity_type == "image") & (EntityTag.entity_id == img.id))
    )
    assert names, "认领后应继承来源提示词的标签"


def test_can_skip_taxonomy_inheritance(api, seed_prompt):
    prompt = seed_prompt(name="带标签的", tags="女性")
    img = _image("noinherit.png")

    api.post("/api/images/link_prompt", json={
        "image_ids": [img.id], "prompt_id": prompt.id, "inherit_taxonomy": False,
    })

    from app.models import EntityTag, Image

    assert Image.get(Image.id == img.id).prompt_id == prompt.id
    assert EntityTag.select().where(
        (EntityTag.entity_type == "image") & (EntityTag.entity_id == img.id)
    ).count() == 0
