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


def test_batch_replace_reports_old_content_and_skips_missing_type(api):
    data = api.post(
        "/api/composition/batch_replace",
        json={
            "texts": [
                {"id": 1, "text": MARKED},
                {"id": 2, "text": "【人物面部】\n黑色长发"},
            ],
            "type": "人物服饰",
            "content": "统一服饰",
        },
    ).json()

    by_id = {item["id"]: item for item in data["items"]}
    assert by_id[1]["replaced"] == "【人物面部】\n黑色长发\n\n【人物服饰】\n统一服饰"
    assert by_id[1]["old_content"] == "白色连衣裙"
    # 没有这一片的提示词不能被凭空加上一段
    assert by_id[2]["replaced"] is None
    assert data["skipped"] == 1
