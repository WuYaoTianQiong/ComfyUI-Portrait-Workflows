/** 图像编辑域：faceswap 节点探测 / 遮罩 / 批量提交。 */
import { apiPost, newIdempotencyKey } from './client'

export interface FaceswapNodes {
  [key: string]: unknown
}

export interface FaceswapBatchAccepted {
  success: boolean
  job_id: number
  total: number
  queued: number
  submitted: number
  errors?: Array<{ index?: number; error: string }>
  async?: boolean
  plan?: unknown
  nodes?: unknown
}

export function getFaceswapNodes(workflowPath: string) {
  return apiPost<FaceswapNodes>('/api/editor/faceswap/nodes', {
    workflow_path: workflowPath,
  })
}

export function createFaceswapMask(body: Record<string, unknown>) {
  return apiPost<{ path: string }>('/api/editor/faceswap/mask', body)
}

export function submitFaceswapBatch(body: Record<string, unknown>) {
  return apiPost<FaceswapBatchAccepted>(
    '/api/editor/faceswap/batch',
    body,
    {},
    { idempotencyKey: newIdempotencyKey() },
  )
}
