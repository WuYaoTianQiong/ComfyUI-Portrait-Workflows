/** 出图提交域：单图 / 批量 / 文本 / 补缺图。 */
import { apiPost, newIdempotencyKey } from './client'

export interface RunAccepted {
  success: boolean
  job_id: number
  result?: unknown
  seed?: number
  dimensions?: string
}

export interface BatchAccepted {
  success: boolean
  job_id: number
  total: number
  queued: number
  submitted: number
  errors?: Array<{ index?: number; prompt_id?: number; error: string }>
  async?: boolean
  idempotent?: boolean
}

export interface GenerateMissingAccepted {
  success: boolean
  job_id: number | null
  count: number
  message?: string
}

export interface RunBody {
  id: number
  workflow_path: string
  workflow_content?: string
  quality: string
  orientation: string
  aspect_ratio?: string
  output_subfolder?: string
  prompt_override?: string
  negative_prompt_override?: string
  seed?: number | null
}

export interface BatchBody {
  items: Array<{
    prompt_id: number
    seed?: number | null
    prompt_override?: string | null
    workflow_path?: string
    workflow_content?: string
    quality?: string
    orientation?: string
    aspect_ratio?: string
  }>
  workflow_path: string
  workflow_content?: string
  quality: string
  orientation: string
  aspect_ratio?: string
  title?: string
  output_subfolder?: string
}

export interface TextRunBody {
  prompt: string
  negative_prompt?: string
  seed?: number | null
  workflow_path: string
  workflow_content?: string
  quality: string
  orientation: string
  aspect_ratio?: string
  output_subfolder?: string
  source_prompt_id?: number | null
}

export interface GenerateMissingBody {
  prompt_ids: number[]
  workflow_path: string
  workflow_content?: string
  quality: string
  orientation: string
  aspect_ratio?: string
}

function withKey() {
  return { idempotencyKey: newIdempotencyKey() }
}

export function submitRun(body: RunBody) {
  return apiPost<RunAccepted>('/api/runs', body, {}, withKey())
}

export function submitBatch(body: BatchBody) {
  return apiPost<BatchAccepted>('/api/runs/batch', body, {}, withKey())
}

export function submitTextRun(body: TextRunBody) {
  return apiPost<RunAccepted>('/api/runs/text', body, {}, withKey())
}

export function submitGenerateMissing(body: GenerateMissingBody) {
  return apiPost<GenerateMissingAccepted>('/api/generate_missing', body, {}, withKey())
}
