"""前后端契约一致性测试 —— 运行时字段断言。

历史背景：`frontend/src/api/types.ts` 曾是后端 JSON 的**第二份手写镜像**，
改了一边另一边不会自动知道，直到用户在页面上看到 `undefined`。那时这里用正则
解析前端 `export interface X { ... }` 再与 Pydantic 模型比对。

P3 起这条链路换了做法（命名规范 §8.3 / §9）：`types.ts` 只是
`openapi.d.ts`（由 `tools/gen_api_types.py` 从 `/openapi.json` 生成）的别名层，
"两边字段对不上"在生成阶段就不可能发生，所以正则比对的用例已经完成使命并删除。
**替代它的是 `tests/test_openapi_snapshot.py`**：快照与后端 schema 不一致就直接失败。

本文件保留另一半价值：真的打一次端点，断言响应里确有前端依赖的字段 ——
响应模型过滤/字段改名这类**运行期**问题，只有真发请求才看得见。
"""

import app.schemas as schemas  # noqa: F401  （保留：便于在本文件里追加模型级断言）


def test_history_response_contains_frontend_fields(api, seed_history):
    """实际请求画廊端点，断言前端用到的字段真的在响应里。"""
    seed_history(filename="contract.png")
    data = api.get("/api/images?page_size=5").json()
    assert set(data) >= {"items", "total", "page", "page_size"}
    item = data["items"][0]
    required = {
        "id", "filename", "view_url", "is_favorite", "missing",
        "created_at", "captured_at", "source", "prompt_name",
        "categories", "tags",
        # 缩略图强缓存依赖它拼 URL 的 v（源文件 st_mtime_ns 字符串）
        "version",
    }
    assert required <= set(item), f"画廊响应缺字段：{required - set(item)}"


def test_prompt_responses_contain_frontend_fields(api, seed_prompt):
    """提示词列表与详情的字段。"""
    listed = api.get("/api/prompts?page_size=5").json()
    assert set(listed) >= {"prompts", "total", "page", "page_size"}
    if listed["prompts"]:
        required = {"id", "prompt_preview", "tags", "name", "created_at",
                    "is_favorite", "is_pinned", "usage_count"}
        assert required <= set(listed["prompts"][0]), \
            f"提示词列表缺字段：{required - set(listed['prompts'][0])}"

    prompt = seed_prompt(name="契约测试")
    detail = api.get(f"/api/prompts/{prompt.id}").json()
    required = {
        "id", "name", "prompt", "negative_prompt", "steps", "cfg_scale",
        "sampler", "seed", "model", "width", "height", "tags", "note",
        "created_at", "updated_at", "is_favorite", "is_pinned",
        "usage_count", "last_used_at", "rating", "categories", "tags_detail",
    }
    assert required <= set(detail), f"提示词详情缺字段：{required - set(detail)}"


def test_tag_and_category_responses_contain_frontend_fields(api, seed_taxonomy):
    """标签与分类树的字段。"""
    tags = api.get("/api/tags").json()
    assert set(tags) >= {"tags"}
    if tags["tags"]:
        required = {"id", "name", "color", "usage_count", "prompt_count"}
        assert required <= set(tags["tags"][0]), \
            f"标签响应缺字段：{required - set(tags['tags'][0])}"

    cats = api.get("/api/categories?tree=true&count_scope=prompt").json()
    assert set(cats) >= {"categories"}
    if cats["categories"]:
        required = {"id", "name", "color", "parent_id", "prompt_count", "children"}
        assert required <= set(cats["categories"][0]), \
            f"分类响应缺字段：{required - set(cats['categories'][0])}"


def test_job_and_stats_responses_contain_frontend_fields(api, seed_history):
    """任务与统计。"""
    jobs = api.get("/api/jobs?limit=5").json()
    assert set(jobs) >= {"jobs"}

    stats = api.get("/api/system/stats").json()
    required = {"prompt_count", "history_count", "job_count", "fragment_count", "top_tags"}
    assert required <= set(stats), f"统计响应缺字段：{required - set(stats)}"


def test_fragment_and_workflow_responses(api):
    """碎片与工作流列表。"""
    frags = api.get("/api/fragments").json()
    assert set(frags) >= {"items", "total"}

    wfs = api.get("/api/workflows").json()
    assert set(wfs) >= {"workflows", "default"}
