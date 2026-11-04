/**
 * 本机 ComfyUI 工作流目录（atelier 后端 `/api/workflows`）。
 *
 * 列表只返回元信息（path/name/caps/params，后端 `WorkflowRow` 已按 mtime 倒序），
 * 选中某个工作流后再按需读取 JSON 内容，避免一次把所有工作流正文都传给浏览器。
 * 请求使用同源相对路径：gallery-web 由 atelier 静态挂载在 `/ref-web` 下，
 * 站点根路径 `/api` 即后端 API。
 */

export interface WorkflowCatalogItem {
  /** 工作流文件的绝对路径（后端已限定在库根目录内） */
  path: string
  /** 文件名，如 `Qwen21_文生图_....json` */
  name: string
  /** 相对库根的路径；子目录里的工作流靠它区分同名文件 */
  rel_path: string
  /** 来源标签：参考库专用 / 画廊本机改版 / 库根 */
  source: string
  /** 文件修改时间（epoch 秒） */
  mtime: number
  /** 工作流可注入能力（如是否支持负向提示词） */
  caps: Record<string, boolean>
  /** 工作流参数结构描述（含 quality_tiers 等可选扩展）；后端可能返回 null */
  params: Record<string, unknown> | null
  /** 工作流里的 LoadImage* 槽位数（能塞几张参考图） */
  image_slots: number
  /** 能否用于参考图库合成台（有图片槽位 + 有文本编码节点） */
  studio_ready: boolean
}

export interface WorkflowCatalogResponse {
  workflows: WorkflowCatalogItem[]
  /** 后端推荐的默认工作流路径（studio 范围优先"人像+服装+姿势"三槽那个） */
  default: string
}

export interface WorkflowContentResponse {
  path: string
  name: string
  /** 已转换为 ComfyUI API 格式的工作流对象 */
  content: Record<string, unknown>
}

async function requestJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  let body: unknown = null
  try {
    body = await res.json()
  } catch {
    // 非 JSON 响应：开发服务器（5173）未代理 /api 时会返回 index.html
  }
  if (!res.ok) {
    // 后端错误统一是 {detail: "..."}；解析失败时退回 HTTP 状态码。
    const detail =
      body && typeof body === 'object' && typeof (body as { detail?: unknown }).detail === 'string'
        ? (body as { detail: string }).detail
        : ''
    throw new Error(detail || `HTTP ${res.status}`)
  }
  if (body === null) {
    throw new Error('接口返回的不是 JSON（请确认 atelier 后端已启动，且当前地址可访问 /api）')
  }
  return body as T
}

/**
 * 拉取本机可用工作流列表（后端默认隐藏视频工作流）。
 *
 * `scope="studio"` 只返回**能做参考合成**的工作流（有 LoadImage 槽位 + 文本编码节点），
 * 来源包括参考库专用目录（`ai-pose-gallery-zh/src/workflows`）、画廊本机改版
 * （`历史工作流/画廊旧版`）与库根；文生图 / 纯超分这类塞不进参考图的不再出现。
 */
export function fetchWorkflowCatalog(scope: 'all' | 'studio' = 'all'): Promise<WorkflowCatalogResponse> {
  const query = scope === 'studio' ? '?scope=studio' : ''
  return requestJson<WorkflowCatalogResponse>(`/api/workflows${query}`)
}

/** 按路径读取工作流内容；后端会校验路径必须在库根目录内 */
export function fetchWorkflowContent(path: string): Promise<WorkflowContentResponse> {
  return requestJson<WorkflowContentResponse>(
    `/api/workflows/content?path=${encodeURIComponent(path)}`
  )
}