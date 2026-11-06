"""P4 同源整套随机 + 随机排除标签的契约测试。"""
from __future__ import annotations

from app.services.fragment_syntax import FRAGMENT_TYPES
from app.services.tagging import RANDOM_EXCLUDE_TAG, RANDOM_EXCLUDE_WARNING


def _recipe(prefix: str = "", *, lower: str = "，搭配蓝色牛仔裤") -> str:
    parts = []
    for ftype in FRAGMENT_TYPES:
        content = f"{prefix}{ftype}内容"
        if ftype == "人物服饰":
            content += lower
        parts.append(f"【{ftype}】\n{content}")
    return "\n\n".join(parts)


def test_random_recipe_returns_complete_8_types(api, seed_prompt):
    first = seed_prompt(name="配方A", prompt=_recipe("A"))
    second = seed_prompt(name="配方B", prompt=_recipe("B"))

    data = api.get("/api/composer/recipes/random").json()

    assert data["prompt_id"] in (first.id, second.id)
    assert data["recipe_count"] == 2
    assert [item["type"] for item in data["fragments"]] == FRAGMENT_TYPES
    assert all(item["content"].startswith(("A", "B")) for item in data["fragments"])


def test_random_recipe_excludes_tagged_and_incomplete(api, seed_prompt):
    usable = seed_prompt(name="可用配方", prompt=_recipe("OK"))
    seed_prompt(name="排除配方", prompt=_recipe("X"), tags=RANDOM_EXCLUDE_TAG)
    seed_prompt(name="缺类配方", prompt="【人物面部】\n只有脸")

    for _ in range(8):
        data = api.get("/api/composer/recipes/random").json()
        assert data["prompt_id"] == usable.id
        assert data["recipe_count"] == 1


def test_random_recipe_404_when_no_complete_recipe(api, seed_prompt):
    seed_prompt(name="排除配方", prompt=_recipe("X"), tags=RANDOM_EXCLUDE_TAG)
    seed_prompt(name="缺类配方", prompt="【人物面部】\n只有脸")

    resp = api.get("/api/composer/recipes/random")

    assert resp.status_code == 404
    assert "完整 8 类配方" in resp.json()["detail"]


def test_random_recipe_exclude_id_avoids_repeat(api, seed_prompt):
    first = seed_prompt(name="配方A", prompt=_recipe("A"))
    second = seed_prompt(name="配方B", prompt=_recipe("B"))

    for _ in range(8):
        data = api.get(
            "/api/composer/recipes/random",
            params={"exclude_id": str(first.id)},
        ).json()
        assert data["prompt_id"] == second.id
        assert data["recipe_count"] == 1


def test_random_recipe_safe_mode_filters_nsfw(api, seed_prompt):
    clean = seed_prompt(name="干净配方", prompt=_recipe("C"))
    seed_prompt(name="敏感配方", prompt=_recipe("N"), tags="NSFW")

    for _ in range(8):
        data = api.get(
            "/api/composer/recipes/random", params={"safe_mode": "1"},
        ).json()
        assert data["prompt_id"] == clean.id


def test_random_recipe_rejects_literal_newline_content(api, seed_prompt):
    broken = _recipe("X").replace(
        "【画风技术】\nX画风技术内容",
        "【画风技术】\nX画风技术内容\\n【场景环境】残留",
    )
    seed_prompt(name="字面量换行配方", prompt=broken)

    resp = api.get("/api/composer/recipes/random")

    assert resp.status_code == 404


def test_fragment_entry_exposes_random_exclude_warning(api, seed_prompt):
    seed_prompt(
        name="排除来源",
        prompt="【场景环境】\n同一段舞台场景",
        tags=RANDOM_EXCLUDE_TAG,
    )

    data = api.get(
        "/api/composer/fragments", params={"fragment_type": "场景环境"},
    ).json()
    entry = next(
        item for item in data["grouped"]["场景环境"]
        if item["content"] == "同一段舞台场景"
    )

    assert entry["warning"] == RANDOM_EXCLUDE_WARNING


def test_clean_duplicate_source_clears_warning(api, seed_prompt):
    seed_prompt(name="干净来源", prompt="【场景环境】\n同一段舞台场景")
    seed_prompt(
        name="排除来源",
        prompt="【场景环境】\n同一段舞台场景",
        tags=RANDOM_EXCLUDE_TAG,
    )

    data = api.get(
        "/api/composer/fragments", params={"fragment_type": "场景环境"},
    ).json()
    entry = next(
        item for item in data["grouped"]["场景环境"]
        if item["content"] == "同一段舞台场景"
    )

    assert entry["dup_count"] == 2
    assert entry["warning"] == ""


def test_random_recipe_skips_top_only_costume(api, seed_prompt):
    usable = seed_prompt(name="完整配方", prompt=_recipe("OK"))
    seed_prompt(name="只有上衣", prompt=_recipe("X", lower=""))

    for _ in range(8):
        data = api.get("/api/composer/recipes/random").json()
        assert data["prompt_id"] == usable.id
        assert data["recipe_count"] == 1


def test_random_recipe_skips_underwear_only_costume(api, seed_prompt):
    usable = seed_prompt(name="完整配方", prompt=_recipe("OK"))
    seed_prompt(
        name="仅内裤",
        prompt=_recipe("X", lower="，下身只穿一条极简内裤"),
    )

    for _ in range(8):
        data = api.get("/api/composer/recipes/random").json()
        assert data["prompt_id"] == usable.id
        assert data["recipe_count"] == 1


def test_random_recipe_safe_mode_skips_explicit_content(api, seed_prompt):
    clean = seed_prompt(name="干净配方", prompt=_recipe("C"))
    explicit = _recipe("N").replace(
        "【场景环境】\nN场景环境内容",
        "【场景环境】\n裸体",
    )
    seed_prompt(name="明确裸露", prompt=explicit)

    for _ in range(8):
        data = api.get(
            "/api/composer/recipes/random", params={"safe_mode": "1"},
        ).json()
        assert data["prompt_id"] == clean.id


def test_fragment_entry_warns_incomplete_costume(api, seed_prompt):
    seed_prompt(name="只有上衣", prompt="【人物服饰】\n白色衬衫")

    data = api.get(
        "/api/composer/fragments", params={"fragment_type": "人物服饰"},
    ).json()
    entry = next(
        item for item in data["grouped"]["人物服饰"] if item["content"] == "白色衬衫"
    )

    assert "服装描述不完整" in entry["warning"]


def test_fragment_entry_has_no_warning_for_complete_costume(api, seed_prompt):
    seed_prompt(name="完整服装", prompt="【人物服饰】\n白色衬衫，搭配蓝色牛仔裤")

    data = api.get(
        "/api/composer/fragments", params={"fragment_type": "人物服饰"},
    ).json()
    entry = next(
        item for item in data["grouped"]["人物服饰"]
        if item["content"] == "白色衬衫，搭配蓝色牛仔裤"
    )

    assert entry["warning"] == ""
