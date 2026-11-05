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
    # 与 ORM 字段同名（DB 列仍是 favorite，见 models.Image）
    is_favorite: bool = False
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


class ImageRunInfo(BaseModel):
    """一次出图的完整上下文：来自任务行 + 参数快照 + ComfyUI history/PNG 元数据。"""

    workflow_path: str = ""
    workflow_name: str = ""
    quality: str = ""
    aspect_ratio: str = ""
    output_subfolder: str = ""
    submitted_at: str = ""
    started_at: str = ""
    finished_at: str = ""
    duration_seconds: Optional[float] = None
    steps: Optional[int] = None
    cfg_scale: Optional[float] = None
    sampler: str = ""
    scheduler: str = ""
    seed: Optional[int] = None
    denoise: Optional[float] = None
    model: str = ""


class ImageDetailResponse(HistoryItem):
    job_type: str = ""
    job_status: str = ""
    job_title: str = ""
    run: ImageRunInfo = Field(default_factory=ImageRunInfo)


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
    #: queued = 还在后台提交队列里，尚未 push 到 ComfyUI
    submit_state: Optional[str] = None
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


class WorkflowCaps(BaseModel):
    """工作流能接受哪些注入项；前端据此隐藏无效旋钮。

    默认全为 True：探测失败时宁可保持旧行为，也不要把功能藏掉。
    `negative` 只表示结构上有没有负向输入；`negative_effective` 才表示
    它是否真的参与采样（负向来自文本节点且 cfg>1）。
    """

    prompt: bool = True
    negative: bool = True
    negative_effective: bool = True
    negative_cfg: float | None = None
    quality: bool = True
    orientation: bool = True


class WorkflowParams(BaseModel):
    """分辨率 / 画质参数的描述，前端据此生成真实档位（而不是固定的 2K..12K）。"""

    quality_mode: str = "none"  # seedvr / scale / megapixels / none
    base_width: int | None = None
    base_height: int | None = None
    base_megapixels: float | None = None
    mp_unit: str = "mp"  # mp（1e6）/ mip（1024²）
    post_scale: float = 1.0  # latent 之后的固定放大倍率（如 ZIT 1.7×）
    orientation_mode: str = "none"  # swap / knob / none
    # 节点真实选项 + 已验证的单程扩展；ZIT 固定放大链路不含 9:21
    aspect_ratios: list[str] = Field(default_factory=list)
    default_ratio: str = ""
    multiple: int = 16
    quality_tiers: list[str] = Field(default_factory=list)
    default_quality: str = ""


class WorkflowRow(BaseModel):
    path: str
    name: str
    #: 相对库根的路径（子目录里的工作流用它在界面上区分同名文件）
    rel_path: str = ""
    #: 来源标签：参考库专用 / 画廊本机改版 / 库根
    source: str = ""
    mtime: float = 0.0
    media_kind: str = "image"
    #: 工作流里的 LoadImage* 槽位数（参考图能塞几张）
    image_slots: int = 0
    #: 是否能用于参考图库合成台（有图片槽位 + 有文本编码节点）
    studio_ready: bool = False
    #: 是否为实测推荐项（三槽齐全 + 姿势 LoRA），前端下拉据此打「推荐」标签
    recommended: bool = False
    caps: WorkflowCaps = Field(default_factory=WorkflowCaps)
    params: WorkflowParams | None = None


class WorkflowListResponse(BaseModel):
    workflows: list[WorkflowRow] = Field(default_factory=list)
    default: str = ""


class TagRefListResponse(BaseModel):
    """给"按标签取实体"这类只返回 id 列表的端点用。"""

    ids: list[int] = Field(default_factory=list)
    total: int = 0
