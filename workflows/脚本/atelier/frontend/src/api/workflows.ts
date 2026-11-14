/** 工作流域：列表 / 内容 / 能力探测 / 校验。 */
import { apiGet, apiPost } from './client'
import type {
  SizePreview,
  WorkflowCaps,
  WorkflowParams,
} from '../composables/useWorkflowCaps'

export interface WorkflowRow {
  path: string
  name: string
  /** 后端探测的注入能力；自定义工作流由 inspect 补齐 */
  caps?: WorkflowCaps
  /** 画质/方向参数的作用方式；自定义工作流由 inspect 补齐 */
  params?: WorkflowParams
  /** 档位 × 比例的预演尺寸；后端是唯一计算方 */
  size_preview?: SizePreview
  /** LoadImage 输入槽数量：>0 表示必须喂图（编辑 / 参考 / 超分），不能纯文本出图 */
  image_slots?: number
  /** 自定义上传的工作流（内容存在本地，不在后端磁盘上） */
  custom?: boolean
}

export interface WorkflowListResponse {
  workflows: WorkflowRow[]
  default: string
}

export interface WorkflowInspection {
  caps: WorkflowCaps
  params: WorkflowParams
  size_preview: SizePreview
}

export interface WorkflowValidation {
  valid: boolean
  error?: string
  name?: string
}

export function listWorkflows() {
  return apiGet<WorkflowListResponse>('/api/workflows')
}

/** 自定义工作流只存在 localStorage，必须把内容带上来让后端探测。 */
export function inspectWorkflow(input: {
  workflow_path?: string
  workflow_content?: string
}) {
  return apiPost<WorkflowInspection>('/api/workflows/inspect', input)
}

export function validateWorkflow(path: string) {
  return apiGet<WorkflowValidation>('/api/validate_workflow', { path })
}
