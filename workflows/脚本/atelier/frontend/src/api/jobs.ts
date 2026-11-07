/** 任务域：列表 / 详情 / 取消 / 重试 / SSE 地址。 */
import type { components } from './openapi'
import { apiGet, apiPost } from './client'
import type { JobSnapshot } from './types'

type Schemas = components['schemas']

export type JobListResponse = Required<Schemas['JobListResponse']>

export interface SimpleJobActionResponse {
  success: boolean
  job_id: number
}

export interface StopAllResponse {
  success: boolean
  stopped: number
}

export interface RetryJobResponse {
  success: boolean
  job_id: number
  submitted: number
  total: number
  errors: Array<{ index?: number; error: string }>
  idempotent: boolean
}

export function listJobs(params: { limit?: number; active?: boolean } = {}) {
  return apiGet<JobListResponse>('/api/jobs', {
    limit: params.limit,
    active: params.active ? 1 : undefined,
  })
}

export function getJob(jobId: number) {
  return apiGet<JobSnapshot>(`/api/jobs/${jobId}`)
}

export function cancelJob(jobId: number) {
  return apiPost<SimpleJobActionResponse>(`/api/jobs/${jobId}/cancel`)
}

export function stopAllJobs() {
  return apiPost<StopAllResponse>('/api/jobs/stop_all')
}

export function retryJob(jobId: number, indexes?: number[]) {
  return apiPost<RetryJobResponse>(
    `/api/jobs/${jobId}/retry`,
    indexes?.length ? { indexes } : undefined,
  )
}

/** SSE 地址集中在任务域，composable 不再手拼路径。 */
export function jobEventsUrl(ids?: number[] | null): string {
  return ids?.length ? `/api/jobs/events?ids=${ids.join(',')}` : '/api/jobs/events'
}
