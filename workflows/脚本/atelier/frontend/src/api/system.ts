/** 系统域：连接状态、配置、统计与维护动作。 */
import { apiGet, apiPost } from './client'
import type { SystemStats } from './types'

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

export function getSystemStatus() {
  return apiGet<SystemStatus>('/api/system/status')
}

export function getSystemConfig() {
  return apiGet<SystemConfig>('/api/system/config')
}

export function getSystemStats() {
  return apiGet<SystemStats>('/api/system/stats')
}

export function openOutputDir() {
  return apiPost<{ success: boolean; path?: string; message?: string }>(
    '/api/system/open-output',
  )
}

export function clearThumbnailCache() {
  return apiPost<{ success: boolean; deleted: number }>('/api/media/thumbnail/clear')
}
