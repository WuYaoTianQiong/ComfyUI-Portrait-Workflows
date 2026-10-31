"""前后端契约一致性测试。

背景：`frontend/src/api/types.ts` 是后端 JSON 的 TypeScript 镜像，两边各写一份，
改了一边另一边不会自动知道 —— 直到用户在页面上看到 `undefined`。

这里把两边**对起来**：

1. 用正则解析前端 types.ts 的 `export interface X { ... }`，取出字段名；
2. 与后端 Pydantic 模型的字段集比对 —— 前端声明的字段后端必须都有；
3. 实际请求端点，断言响应里真的有这些字段。

这样"后端删字段 / 改字段名"会在 CI 就炸，而不是等用户撞上。

新增接口时：后端加 Pydantic 模型 → 前端 types.ts 加同名 interface →
在本文件的 MODELS 映射里登记。
"""

import re
from pathlib import Path

import app.schemas as schemas

V4 = Path(__file__).resolve().parents[1]
TYPES_TS = V4 / "frontend" / "src" / "api" / "types.ts"

# 前端 interface 名 → 后端 Pydantic 模型
MODELS = {
    "TagRef": schemas.TagRef,
    "CategoryRef": schemas.CategoryRef,
    "TagRow": schemas.TagRow,
    "HistoryItem": schemas.HistoryItem,
    "HistoryPage": schemas.HistoryListResponse,
    "CategoryNode": schemas.CategoryNode,
    "JobItem": schemas.JobItem,
    "JobSnapshot": schemas.JobSnapshot,
    "PromptListItem": schemas.PromptListItem,
    "PromptListPage": schemas.PromptListResponse,
    "PromptDetail": schemas.PromptDetail,
}


def _frontend_interfaces() -> dict:
    """解析前端 types.ts，返回 {interface 名: 字段名列表}。"""
    text = TYPES_TS.read_text(encoding="utf-8")
    out = {}
    for match in re.finditer(r"export interface (\w+)[^{]*\{(.*?)\n\}", text, re.S):
        name, body = match.group(1), match.group(2)
        # 只要形如 `field: Type` 或 `field?: Type` 的行；跳过方法签名与注释
        fields = re.findall(r"^\s{2}(\w+)\??:", body, re.M)
        out[name] = fields
    return out


def test_frontend_types_file_exists():
    assert TYPES_TS.is_file(), "前端 types.ts 不见了 —— 契约测试的前提是两边都有"


def test_frontend_interfaces_are_parsed():
    """解析器本身要可靠：漏解析会静默让后面的比对变成空断言。"""
    interfaces = _frontend_interfaces()
    assert "HistoryItem" in interfaces
    assert "filename" in interfaces["HistoryItem"]
    assert "id" in interfaces["TagRef"]


def test_frontend_declared_fields_exist_in_backend_models():
    """前端 types.ts 声明的每个字段，后端模型都必须有。"""
    interfaces = _frontend_interfaces()
    problems = []
    for name, fields in interfaces.items():
        model = MODELS.get(name)
        if model is None:
            continue  # 未登记的接口不参与比对
        backend = set(model.model_fields.keys())
        missing = [f for f in fields if f not in backend]
        if missing:
            problems.append(f"{name}: 后端模型缺 {missing}")
    assert not problems, "前端声明了后端没有的字段：\n" + "\n".join(problems)


def test_every_registered_model_is_used_by_frontend():
    """登记进 MODELS 的模型，前端也要有对应 interface —— 防止后端加了模型却没同步。"""
    interfaces = _frontend_interfaces()
    unused = [name for name in MODELS if name not in interfaces]
    assert not unused, f"这些后端模型在前端没有对应 interface：{unused}"


def test_history_response_contains_frontend_fields(api, seed_history):
    """实际请求画廊端点，断言前端用到的字段真的在响应里。"""
    seed_history(filename="contract.png")
    data = api.get("/api/images?page_size=5").json()
    assert set(data) >= {"items", "total", "page", "page_size"}
    item = data["items"][0]
    required = {
        "id", "filename", "view_url", "favorite", "missing",
        "created_at", "captured_at", "source", "prompt_name",
        "categories", "tags",
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
