"""主要资源的 CRUD 行为基线。

补齐 test_contract.py 之外的写路径：分类、碎片、标签、提示词标记、图片动作。
重点是"删得干净"和"关联不留孤儿" —— 这两类问题在 SQLite 外键开启后
会直接变成 500，而不是悄悄留下脏数据。
"""


# ---------------------------------------------------------------------------
# 分类
# ---------------------------------------------------------------------------

def test_category_crud_lifecycle(api, seed_prompt):
    created = api.post("/api/categories", json={"name": "测试分类", "color": "#123456"})
    assert created.status_code == 201
    cid = created.json()["id"]

    cats = api.get("/api/categories").json()["categories"]
    assert any(c["id"] == cid and c["name"] == "测试分类" for c in cats)

    prompt = seed_prompt(name="分类用")
    assert api.post(f"/api/categories/{cid}/prompts/{prompt.id}").status_code == 200

    cats = api.get("/api/categories").json()["categories"]
    assert next(c for c in cats if c["id"] == cid)["prompt_count"] == 1

    assert api.put(f"/api/categories/{cid}", json={"name": "改过名"}).status_code == 200
    assert any(
        c["name"] == "改过名" for c in api.get("/api/categories").json()["categories"]
    )

    assert api.delete(f"/api/categories/{cid}/prompts/{prompt.id}").status_code == 200
    assert api.delete(f"/api/categories/{cid}").status_code == 200
    assert api.delete(f"/api/categories/{cid}").status_code == 404


def test_delete_category_with_links_does_not_500(api, seed_prompt):
    """删分类时必须连关联一起清掉：外键开启后留下 PromptCategory 会直接 500。"""
    from app.models import Category, PromptCategory

    cid = api.post("/api/categories", json={"name": "带关联"}).json()["id"]
    prompt = seed_prompt(name="p")
    api.post(f"/api/categories/{cid}/prompts/{prompt.id}")

    assert api.delete(f"/api/categories/{cid}").status_code == 200
    assert Category.get_or_none(Category.id == cid) is None
    assert PromptCategory.select().where(PromptCategory.category == cid).count() == 0


def test_category_image_count_excludes_soft_deleted(api, seed_history):
    """侧栏分类计数必须和画廊里实际能看到的图一致：软删除的图不能算进去。"""
    from app.models import ImageCategory

    cid = api.post("/api/categories", json={"name": "计数"}).json()["id"]
    live = seed_history(filename="live.png")
    gone = seed_history(filename="gone.png")
    ImageCategory.create(image=live.id, category=cid)
    ImageCategory.create(image=gone.id, category=cid)
    api.delete(f"/api/images/{gone.id}")

    tree = api.get("/api/categories?tree=true&count_scope=image").json()["categories"]
    node = next(c for c in tree if c["id"] == cid)
    assert node["prompt_count"] == 1


def test_category_tree_envelope(api, seed_prompt):
    parent = api.post("/api/categories", json={"name": "父"}).json()["id"]
    child = api.post(
        "/api/categories", json={"name": "子", "parent_id": parent}
    ).json()["id"]

    tree = api.get("/api/categories?tree=true").json()["categories"]
    node = next(c for c in tree if c["id"] == parent)
    assert [c["id"] for c in node["children"]] == [child]


# ---------------------------------------------------------------------------
# 碎片库
# ---------------------------------------------------------------------------

def test_fragment_crud(api):
    created = api.post(
        "/api/fragments",
        json={"name": "测试碎片", "fragment_type": "人物面部", "content": "微笑"},
    )
    assert created.status_code == 201
    fid = created.json()["id"]

    listed = api.get("/api/fragments").json()
    assert any(f["id"] == fid for f in listed["items"])

    assert api.get("/api/fragments?search=微笑").json()["total"] >= 1
    assert "grouped" in api.get("/api/fragments/by_type").json()

    assert api.put(f"/api/fragments/{fid}", json={"content": "大笑"}).status_code == 200
    assert api.delete(f"/api/fragments/{fid}").status_code == 200
    assert api.delete(f"/api/fragments/{fid}").status_code == 404


# ---------------------------------------------------------------------------
# 标签
# ---------------------------------------------------------------------------

def test_tag_crud(api):
    created = api.post("/api/tags", json={"name": "新标签", "color": "#ff0000"})
    assert created.status_code == 201
    tid = created.json()["id"]

    assert api.put(f"/api/tags/{tid}", json={"name": "改名标签"}).status_code == 200
    names = [t["name"] for t in api.get("/api/tags").json()["tags"]]
    assert "改名标签" in names

    assert api.delete(f"/api/tags/{tid}").status_code == 200
    assert api.get("/api/tags").json()["tags"] == []


def test_delete_tag_clears_entity_links(api, seed_history):
    """删标签要连带清掉 entity_tags，否则筛选时会查到不存在标签的图片。"""
    from app.models import EntityTag

    tid = api.post("/api/tags", json={"name": "待删"}).json()["id"]
    img = seed_history(filename="t.png")
    api.post(f"/api/images/{img.id}/tags/{tid}")

    assert api.delete(f"/api/tags/{tid}").status_code == 200
    assert EntityTag.select().where(EntityTag.tag == tid).count() == 0


# ---------------------------------------------------------------------------
# 提示词标记
# ---------------------------------------------------------------------------

def test_prompt_flag_endpoints(api):
    pid = api.post("/api/prompts", json={"name": "标记", "prompt": "x"}).json()["id"]

    fav = api.post(f"/api/prompts/{pid}/favorite").json()
    assert fav["is_favorite"] is True

    assert api.post(f"/api/prompts/{pid}/pin").json()["is_pinned"] is True
    assert api.post(f"/api/prompts/{pid}/rate?rating=5").json()["rating"] == 5
    assert api.post(f"/api/prompts/{pid}/use").json()["usage_count"] == 1
    assert api.get(f"/api/prompts/{pid}/history").status_code == 200


# ---------------------------------------------------------------------------
# 图片动作
# ---------------------------------------------------------------------------

def test_history_item_actions(api, seed_history):
    from app.models import Image

    img = seed_history(filename="act.png")

    assert api.post(f"/api/images/{img.id}/favorite").json()["is_favorite"] is True

    cid = api.post("/api/categories", json={"name": "图片分类"}).json()["id"]
    assert api.post(f"/api/images/{img.id}/categories/{cid}").status_code == 200
    assert api.delete(f"/api/images/{img.id}/categories/{cid}").status_code == 200

    tid = api.post("/api/tags", json={"name": "图片标签"}).json()["id"]
    assert api.post(f"/api/images/{img.id}/tags/{tid}").status_code == 200
    assert api.delete(f"/api/images/{img.id}/tags/{tid}").status_code == 200

    assert api.delete(f"/api/images/{img.id}").status_code == 200
    assert bool(Image.get_by_id(img.id).is_deleted) is True


def test_history_batch_delete_keeps_prompt_records(api, seed_history):
    """批量删图只软删，不碰提示词。"""
    from app.models import Image, Prompt

    prompt = Prompt.create(name="保留", prompt="x")
    a = seed_history(filename="b1.png", prompt_id=prompt.id)
    b = seed_history(filename="b2.png", prompt_id=prompt.id)

    assert api.post("/api/images/batch_delete", json={"ids": [a.id, b.id]}).status_code == 200
    assert all(
        bool(Image.get_by_id(i).is_deleted) for i in (a.id, b.id)
    )
    assert Prompt.get_or_none(Prompt.id == prompt.id) is not None


def test_delete_only_touches_disk_when_asked(api, seed_history):
    """delete_files 默认关闭：不传就只软删记录，磁盘原图必须留着。"""
    from app.config import settings
    from app.models import Image

    out_dir = settings.comfyui_root / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    keep = out_dir / "keep_on_disk.png"
    keep.write_bytes(b"x")

    img = seed_history(filename="keep_on_disk.png")
    assert api.post("/api/images/batch_delete", json={"ids": [img.id]}).status_code == 200

    assert keep.exists(), "未勾选删除文件时不应动磁盘"
    assert bool(Image.get_by_id(img.id).is_deleted) is True
    keep.unlink()


def test_delete_with_delete_files_removes_source_and_counts(api, seed_history):
    """单条与批量删除都要能按 delete_files 真删原图，并回报删掉的文件数。"""
    from app.config import settings
    from app.models import Image

    out_dir = settings.comfyui_root / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    single = out_dir / "single_drop.png"
    b1 = out_dir / "batch_drop_1.png"
    b2 = out_dir / "batch_drop_2.png"
    for f in (single, b1, b2):
        f.write_bytes(b"x")

    i_single = seed_history(filename="single_drop.png")
    i1 = seed_history(filename="batch_drop_1.png")
    i2 = seed_history(filename="batch_drop_2.png")
    i_missing = seed_history(filename="already_gone.png")

    resp = api.delete(f"/api/images/{i_single.id}", params={"delete_files": True})
    assert resp.status_code == 200
    assert resp.json()["files_deleted"] == 1
    assert not single.exists()

    resp = api.post(
        "/api/images/batch_delete",
        json={"ids": [i1.id, i2.id, i_missing.id], "delete_files": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] == 3
    # 磁盘上本来就没文件的记录不该被算进 files_deleted
    assert body["files_deleted"] == 2
    assert not b1.exists() and not b2.exists()
    assert all(
        bool(Image.get_by_id(i).is_deleted) for i in (i1.id, i2.id, i_missing.id)
    )


def test_batch_delete_prompts_detaches_history(api, seed_history):
    """批量删提示词只解除关联，不能把画廊里的图片记录一起删掉。"""
    from app.models import Image, Prompt

    prompt = Prompt.create(name="批量删", prompt="x")
    img = seed_history(filename="detach.png", prompt_id=prompt.id)

    resp = api.post("/api/prompts/batch_delete", json={"ids": [prompt.id]})
    assert resp.status_code == 200

    row = Image.get_by_id(img.id)
    assert row.prompt_id is None
    assert bool(row.is_deleted) is False
