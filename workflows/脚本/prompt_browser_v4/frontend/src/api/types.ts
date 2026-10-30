/**
 * 后端 JSON 契约的 TypeScript 镜像。
 *
 * 这些字段来自 `/api/history`、`/api/tags` 等现有端点（契约由
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
  view_url: string
  favorite: boolean
  /** 文件缺失（派生状态，可自愈）：只影响展示与筛选，不代表记录被删除 */
  missing: boolean
  width?: number
  height?: number
  file_size?: number
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
