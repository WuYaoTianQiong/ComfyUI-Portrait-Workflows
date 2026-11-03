"""`/api/composition/*` 的契约 —— 前端 `utils/segmentation.ts` 全部改调这里。

命名规范 §9：`【类型】` 语法只有后端一份实现。这些用例锁的是"前端依赖的返回
形状"，不只是语法本身（语法在 test_fragment_syntax.py 里测）。
"""

MARKED = "【人物面部】\n黑色长发\n\n【人物服饰】\n白色连衣裙"
MIXED = "【人物面部】\n黑色长发\n\n一个站在窗边的女孩"


def test_parse_returns_fragments_and_leftover(api):
    data = api.post("/api/composition/parse", json={"text": MIXED}).json()
    assert data["fragments"] == [{"type": "人物面部", "content": "黑色长发"}]
    assert data["leftover"] == "一个站在窗边的女孩"
    assert data["types"] == ["人物面部"]
    assert data["problems"] == []


def test_parse_flat_text_has_no_fragments(api):
    data = api.post("/api/composition/parse", json={"text": "扁平提示词"}).json()
    assert data["fragments"] == []
    assert data["leftover"] == "扁平提示词"


def test_render_batches_each_group(api):
    data = api.post(
        "/api/composition/render",
        json={
            "items": [
                [
                    {"type": "人物面部", "content": "黑色长发"},
                    {"type": "人物服饰", "content": "白色连衣裙"},
                ],
                [{"type": "画风技术", "content": "赛璐璐"}],
                [],
            ]
        },
    ).json()
    assert data["texts"] == [
        "【人物面部】\n黑色长发\n\n【人物服饰】\n白色连衣裙",
        "【画风技术】\n赛璐璐",
        "",
    ]


def test_batch_replace_applies_every_type_with_its_own_outcome(api):
    """一份清单里多个类型一起改，每种类型各返回旧内容与动作。"""
    data = api.post(
        "/api/composition/batch_replace",
        json={
            "texts": [{"id": 1, "text": MARKED}],
            "replacements": [
                {"type": "人物面部", "content": "银色长发"},
                {"type": "人物服饰", "content": "统一服饰"},
            ],
        },
    ).json()

    item = data["items"][0]
    assert item["replaced"] == "【人物面部】\n银色长发\n\n【人物服饰】\n统一服饰"
    assert item["outcomes"] == [
        {"type": "人物面部", "old_content": "黑色长发", "action": "replaced"},
        {"type": "人物服饰", "old_content": "白色连衣裙", "action": "replaced"},
    ]


def test_batch_replace_missing_types_follow_per_type_policy(api):
    """清单里每个类型独立决定缺失时跳过还是追加。"""
    data = api.post(
        "/api/composition/batch_replace",
        json={
            "texts": [{"id": 1, "text": "【人物面部】\n黑色长发"}],
            "replacements": [
                {"type": "人物服饰", "content": "统一服饰", "missing": "append"},
                {"type": "人物身材", "content": "纤细修长", "missing": "skip"},
            ],
        },
    ).json()

    item = data["items"][0]
    assert item["outcomes"] == [
        {"type": "人物服饰", "old_content": "", "action": "appended"},
        {"type": "人物身材", "old_content": "", "action": "skipped"},
    ]
    # 追加那一条生效，跳过的那条不能凭空出现
    assert item["replaced"] == "【人物面部】\n黑色长发\n\n【人物服饰】\n统一服饰"


def test_batch_replace_all_skipped_returns_none(api):
    data = api.post(
        "/api/composition/batch_replace",
        json={
            "texts": [{"id": 2, "text": "【人物面部】\n黑色长发"}],
            "replacements": [
                {"type": "人物服饰", "content": "统一服饰"},
                {"type": "人物身材", "content": "纤细修长"},
            ],
        },
    ).json()

    item = data["items"][0]
    assert item["replaced"] is None
    assert [o["action"] for o in item["outcomes"]] == ["skipped", "skipped"]


def test_batch_replace_append_keeps_flat_text(api):
    data = api.post(
        "/api/composition/batch_replace",
        json={
            "texts": [{"id": 1, "text": "白门走廊，黑袍赤足"}],
            "replacements": [
                {"type": "人物身材", "content": "纤细修长", "missing": "append"},
            ],
        },
    ).json()

    item = data["items"][0]
    assert item["outcomes"][0]["action"] == "appended"
    assert item["replaced"] == "白门走廊，黑袍赤足\n\n【人物身材】\n纤细修长"
