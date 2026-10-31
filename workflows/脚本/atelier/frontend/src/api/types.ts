/**
 * 后端 JSON 契约的 TypeScript 镜像。
 *
 * 这些字段来自 `/api/images`、`/api/tags` 等现有端点（契约由
 * tests/test_contract.py + tests/test_endpoints_smoke.py 锁住）。
 * 后端改名会先在测试里炸，前端这边则有编译期提示 —— 两层保护。
 */

export interface TagRef {
  id: number
  name: string
  color: string
}

export interface CategoryRef {
  id: number
  name: string
  color: string
}

export interface HistoryItem {
  id: number
  job_id: number | null
  prompt_id: number | null
  comfyui_prompt_id: string | null
  filename: string
  subfolder: string | null
  img_type: string | null
  /** 后端可能给 null（没有可拼的地址） */
  view_url: string | null
  favorite: boolean
  /** 文件缺失（派生状态，可自愈）：只影响展示与筛选，不代表记录被删除 */
  missing: boolean
  /** 后端可能给 null（没记录宽高），类型要如实反映，否则调用方要到处判空 */
  width?: number | null
  height?: number | null
  file_size?: number | null
  created_at: string
  captured_at: string
  source: string
  prompt_name: string
  prompt_params: Record<string, unknown> | null
  categories: CategoryRef[]
  tags: TagRef[]
}

export interface HistoryPage {
  items: HistoryItem[]
  total: number
  page: number
  page_size: number
}

export interface TagRow {
  id: number
  name: string
  color: string
  usage_count: number
  /** 语义随 count_scope 变化：prompt 维度=提示词数，image 维度=去重图片数 */
  prompt_count: number
}

export interface CategoryNode extends CategoryRef {
  parent_id: number | null
  prompt_count: number
  children: CategoryNode[]
}

// ---------------------------------------------------------------------------
// 任务
// ---------------------------------------------------------------------------

export interface JobItem {
  prompt_id?: number
  seed?: number
  prompt_preview?: string
  status?: string
  error?: string
  comfyui_prompt_id?: string
  images?: Array<{ filename: string; subfolder?: string; type?: string }>
}

export interface JobSnapshot {
  id: number
  job_type: string
  status: string
  title: string
  total: number
  done_count: number
  error_count: number
  items: JobItem[]
  workflow_path?: string
  orientation?: string
  quality?: string
  extra?: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

// ---------------------------------------------------------------------------
// 提示词
// ---------------------------------------------------------------------------

export interface PromptListItem {
  id: number
  prompt_preview: string
  tags: string
  steps: number | null
  sampler: string
  model: string
  name: string
  created_at: string
  is_favorite: boolean
  is_pinned: boolean
  rating: number | null
  usage_count: number
}

export interface PromptListPage {
  prompts: PromptListItem[]
  total: number
  page: number
  page_size: number
}

export interface PromptDetail {
  id: number
  name: string
  prompt: string
  negative_prompt: string
  steps: number | null
  cfg_scale: number | null
  sampler: string
  seed: number | null
  model: string
  width: number | null
  height: number | null
  tags: string
  note: string
  created_at: string
  updated_at: string
  is_favorite: boolean
  is_pinned: boolean
  usage_count: number
  last_used_at: string
  rating: number | null
  categories: CategoryRef[]
  tags_detail: TagRef[]
}
