"""自动分类按 system_key 匹配，分类改名不再失联或重生默认分类。"""
from app.models import AUTO_CATEGORIES, Category, PromptCategory, ensure_auto_categories


def test_auto_categories_have_stable_keys(api):
    ensure_auto_categories()
    for info in AUTO_CATEGORIES.values():
        assert Category.get_or_none(Category.system_key == info["system_key"]) is not None


def test_renamed_auto_category_still_receives_prompts(api, seed_prompt):
    ensure_auto_categories()
    original = Category.get(Category.system_key == "auto:composite")

    renamed = api.put(f"/api/categories/{original.id}", json={"name": "组合-改名"})
    assert renamed.status_code == 200, renamed.text

    prompt = seed_prompt(prompt=(
        "【人物面部】a\n\n【人物身材】b\n\n【人物服饰】c\n\n【场景环境】d"
    ))
    resp = api.post(f"/api/categories/auto-classify/{prompt.id}")
    assert resp.status_code == 200, resp.text

    linked = {
        row.category_id
        for row in PromptCategory.select().where(PromptCategory.prompt == prompt.id)
    }
    assert original.id in linked
    # 不会重新创建一个叫「组合提示词」的默认分类
    assert Category.get_or_none(
        (Category.name == "组合提示词") & (Category.system_key.is_null())
    ) is None
    assert Category.get_by_id(original.id).name == "组合-改名"
