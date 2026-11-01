"""提示词列表的「碎片级筛选」契约（`/api/prompts` 的 fragment_* 参数）。

锁住三条容易退化的语义：
1. `only` 是"出现过的类型集合恰好等于所选" —— 这才是"只有某一段描写的提示词"，
   自动分类的「单项提示词」把 1~3 类型混在一起，给不出这个粒度；
2. `has` 是"包含所选类型"，多出来的类型不影响命中；
3. `fragment_kw` 必须命中**碎片正文**（不是 name/note/整段 prompt 的任意位置），
   且指定类型时得落在所选类型的那一片里 —— 否则搜一个词会把该提示词的全部碎片都算命中。
"""

FACE_ONLY = "【人物面部】\n黑色长发，冷白皮"
FACE_AND_DRESS = "【人物面部】\n黑色长发\n\n【人物服饰】\n白衬衫"
KW_IN_FACE = "【人物面部】\n戴着白衬衫领结\n\n【场景环境】\n雨天街道"


def _seed(seed_prompt):
    return {
        "face_only": seed_prompt(name="只有面部", prompt=FACE_ONLY).id,
        "face_and_dress": seed_prompt(name="面部+服饰", prompt=FACE_AND_DRESS).id,
        # 「白衬衫」出现在【人物面部】这一片里，而不是【人物服饰】里
        "kw_in_face": seed_prompt(name="白衬衫在面部", prompt=KW_IN_FACE).id,
    }


def _ids(api, **params):
    resp = api.get("/api/prompts", params={"page_size": 100, **params})
    assert resp.status_code == 200, resp.text
    return {row["id"] for row in resp.json()["prompts"]}


def test_only_matches_prompts_with_exactly_that_type(api, seed_prompt):
    ids = _seed(seed_prompt)

    only_face = _ids(api, fragment_types="人物面部", fragment_match="only")

    assert only_face == {ids["face_only"]}


def test_has_matches_prompts_containing_the_type(api, seed_prompt):
    ids = _seed(seed_prompt)

    has_face = _ids(api, fragment_types="人物面部", fragment_match="has")

    assert has_face == {ids["face_only"], ids["face_and_dress"], ids["kw_in_face"]}


def test_only_with_multiple_types_requires_exact_set(api, seed_prompt):
    ids = _seed(seed_prompt)

    both = _ids(api, fragment_types="人物面部,人物服饰", fragment_match="only")

    assert both == {ids["face_and_dress"]}


def test_keyword_only_hits_fragment_body(api, seed_prompt):
    """『白衬衫』两条提示词里都有，但只有一条落在【人物服饰】这一片里。"""
    ids = _seed(seed_prompt)

    in_any_fragment = _ids(api, fragment_kw="白衬衫")
    in_dress = _ids(api, fragment_kw="白衬衫", fragment_types="人物服饰", fragment_match="has")

    assert in_any_fragment == {ids["face_and_dress"], ids["kw_in_face"]}
    assert in_dress == {ids["face_and_dress"]}


def test_keyword_does_not_match_name_or_note(api, seed_prompt):
    """名字/备注里有这个词，正文碎片里没有 —— 不该命中（否则还是原来的全文本搜索）。"""
    hit = seed_prompt(name="不锈钢水杯", prompt=FACE_ONLY, note="不锈钢")
    resp = api.get("/api/prompts", params={"page_size": 100, "fragment_kw": "不锈钢"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 0
    assert hit.id is not None


def test_empty_match_is_false_condition(api, seed_prompt):
    """没有任何提示词含「画风技术」时返回空列表，而不是把全部返回（空 in_ 的坑）。"""
    _seed(seed_prompt)
    resp = api.get("/api/prompts", params={"page_size": 100, "fragment_types": "画风技术"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 0


def test_prompts_full_uses_same_fragment_filter(api, seed_prompt):
    """批量替换走 /api/prompts/full，筛选必须与列表同源，否则"看到的"和"替换的"不是一批。"""
    ids = _seed(seed_prompt)

    resp = api.get(
        "/api/prompts/full",
        params={"fragment_types": "人物面部", "fragment_match": "only"},
    )
    assert resp.status_code == 200, resp.text
    assert {row["id"] for row in resp.json()["items"]} == {ids["face_only"]}
