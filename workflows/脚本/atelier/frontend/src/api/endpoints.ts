/** 端点级类型封装：调用点只关心业务参数与响应，不再各自写泛型。 */
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

export interface SystemStatus {
  comfyui: 'online' | 'offline'
  queue_running: number
  queue_pending: number
}

export interface SystemConfig {
  workflow_path: string
  workflow_name: string
  db_path: string
  output_dir: string
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

export function getSystemStatus() {
  return apiGet<SystemStatus>('/api/system/status')
}

export function getSystemConfig() {
  return apiGet<SystemConfig>('/api/system/config')
}

export function openOutputDir() {
  return apiPost<{ success: boolean; path?: string; message?: string }>(
    '/api/system/open-output',
  )
}
