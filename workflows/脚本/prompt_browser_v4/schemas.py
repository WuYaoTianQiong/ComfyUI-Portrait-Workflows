"""API 响应模型（Pydantic）。

此前所有端点都返回**裸 dict**：后端删一个字段、改一个字段名，前端毫无察觉，
只有用户点进去看到 `undefined` 才炸。这里给前端实际依赖的核心端点加响应模型：

- **响应会按模型过滤** —— 模型里没声明的字段会被丢掉；模型声明了而端点没给，
  会在请求时直接报错。好处是"契约漂移"在首次请求就暴露，而不是等用户撞上。
- 字段与 `frontend/src/api/types.ts` 一一对应，改动必须同步两边。
  两边不一致时，前端的 TS 类型会与实际 JSON 对不上（编译期无感知，运行时才发现）。

新增端点时照这个模式加模型即可；不必一次覆盖全部 69 个端点。
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 标签 / 分类
# ---------------------------------------------------------------------------


class TagRef(BaseModel):
    id: int
    name: str
    color: str


class CategoryRef(BaseModel):
    id: int
    name: str
    color: str


class TagRow(BaseModel):
    id: int
    name: str
    color: str
    usage_count: int = 0
    # 语义随 count_scope 变化：prompt 维度=提示词数，image 维度=去重图片数
    prompt_count: int = 0


class TagListResponse(BaseModel):
    tags: list[TagRow] = Field(default_factory=list)


class CategoryNode(CategoryRef):
    parent_id: Optional[int] = None
    prompt_count: int = 0
    children: list["CategoryNode"] = Field(default_factory=list)


class CategoryTreeResponse(BaseModel):
    categories: list[CategoryNode] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 画廊
# ---------------------------------------------------------------------------


class HistoryItem(BaseModel):
    id: int
    job_id: Optional[int] = None
    prompt_id: Optional[int] = None
    comfyui_prompt_id: Optional[str] = None
    filename: str
    subfolder: Optional[str] = None
    img_type: Optional[str] = None
    # 后端可能给 None（没有可拼的地址）—— 如实反映，别让前端以为一定是字符串
    view_url: Optional[str] = None
    favorite: bool = False
    # 文件缺失（派生状态，可自愈）：只影响展示与筛选，不代表记录被删除
    missing: bool = False
    width: Optional[int] = None
    height: Optional[int] = None
    file_size: Optional[int] = None
    created_at: str = ""
    captured_at: str = ""
    source: str = ""
    prompt_name: str = ""
    prompt_params: Optional[dict[str, Any]] = None
    categories: list[CategoryRef] = Field(default_factory=list)
    tags: list[TagRef] = Field(default_factory=list)


class HistoryListResponse(BaseModel):
    items: list[HistoryItem] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 0


class FacetsResponse(BaseModel):
    source: dict[str, int] = Field(default_factory=dict)
    date: dict[str, int] = Field(default_factory=dict)
    model: dict[str, int] = Field(default_factory=dict)
    orientation: dict[str, int] = Field(default_factory=dict)


class HistoryIdsResponse(BaseModel):
    ids: list[int] = Field(default_factory=list)
    total: int = 0


# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------


class PromptListItem(BaseModel):
    id: int
    prompt_preview: str = ""
    tags: str = ""
    steps: Optional[int] = None
    sampler: str = ""
    model: str = ""
    name: str = ""
    created_at: str = ""
    is_favorite: bool = False
    is_pinned: bool = False
    rating: Optional[int] = None
    usage_count: int = 0


class PromptListResponse(BaseModel):
    prompts: list[PromptListItem] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 0


class PromptDetail(BaseModel):
    id: int
    name: str = ""
    prompt: str = ""
    negative_prompt: str = ""
    steps: Optional[int] = None
    cfg_scale: Optional[float] = None
    sampler: str = ""
    seed: Optional[int] = None
    model: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    tags: str = ""
    note: str = ""
    created_at: str = ""
    updated_at: str = ""
    is_favorite: bool = False
    is_pinned: bool = False
    usage_count: int = 0
    last_used_at: str = ""
    rating: Optional[int] = None
    categories: list[CategoryRef] = Field(default_factory=list)
    tags_detail: list[TagRef] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 碎片
# ---------------------------------------------------------------------------


class FragmentRow(BaseModel):
    id: int
    name: str = ""
    fragment_type: str = ""
    content: str = ""
    tags: str = ""
    usage_count: int = 0
    created_at: str = ""
    updated_at: str = ""


class FragmentListResponse(BaseModel):
    items: list[FragmentRow] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 0


# ---------------------------------------------------------------------------
# 任务
# ---------------------------------------------------------------------------


class JobImage(BaseModel):
    filename: str
    subfolder: Optional[str] = None
    type: Optional[str] = None


class JobItem(BaseModel):
    prompt_id: Optional[int] = None
    seed: Optional[int] = None
    prompt_preview: Optional[str] = None
    status: Optional[str] = None
    error: Optional[str] = None
    comfyui_prompt_id: Optional[str] = None
    images: list[JobImage] = Field(default_factory=list)


class JobSnapshot(BaseModel):
    id: int
    job_type: str = ""
    status: str = ""
    title: str = ""
    total: int = 0
    done_count: int = 0
    error_count: int = 0
    items: list[JobItem] = Field(default_factory=list)
    workflow_path: Optional[str] = None
    orientation: Optional[str] = None
    quality: Optional[str] = None
    extra: Optional[dict[str, Any]] = None
    created_at: str = ""
    updated_at: str = ""


class JobListResponse(BaseModel):
    jobs: list[JobSnapshot] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 其它
# ---------------------------------------------------------------------------


class StatsResponse(BaseModel):
    prompt_count: int = 0
    history_count: int = 0
    job_count: int = 0
    fragment_count: int = 0
    top_tags: list[dict[str, Any]] = Field(default_factory=list)


class WorkflowRow(BaseModel):
    path: str
    name: str


class WorkflowListResponse(BaseModel):
    workflows: list[WorkflowRow] = Field(default_factory=list)
    default: str = ""


class TagRefListResponse(BaseModel):
    """给"按标签取实体"这类只返回 id 列表的端点用。"""

    ids: list[int] = Field(default_factory=list)
    total: int = 0
