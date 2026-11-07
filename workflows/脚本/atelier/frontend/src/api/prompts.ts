/** 提示词域：列表 / 详情 / 出图历史 / 元数据 / 批量操作 / 导入导出。 */
import { apiDelete, apiGet, apiPost, apiPut, type QueryParams } from './client'
import type { PromptDetail, PromptListPage } from './types'

export interface PromptHistoryRefs {
  items: Array<{ id: number }>
}

export const PROMPT_EXPORT_URL = '/api/prompts/export'

export function listPrompts(params: QueryParams = {}) {
  return apiGet<PromptListPage>('/api/prompts', params)
}

export function getPrompt(id: number) {
  return apiGet<PromptDetail>(`/api/prompts/${id}`)
}

/** 只取 id，再由画廊同一套 `/api/images?ids=` 序列化，避免第二套图片 DTO。 */
export function getPromptHistoryRefs(id: number, limit = 24) {
  return apiGet<PromptHistoryRefs>(`/api/prompts/${id}/history`, { limit })
}

export function updatePrompt(id: number, payload: Partial<PromptDetail>) {
  return apiPut<{ success: boolean }>(`/api/prompts/${id}`, payload)
}

export function setPromptFavorite(id: number) {
  return apiPost<{ success: boolean; is_favorite: boolean }>(`/api/prompts/${id}/favorite`)
}

export function setPromptPinned(id: number) {
  return apiPost<{ success: boolean; is_pinned: boolean }>(`/api/prompts/${id}/pin`)
}

export function ratePrompt(id: number, rating: number) {
  return apiPost<{ success: boolean; rating: number }>(
    `/api/prompts/${id}/rate`,
    undefined,
    { rating },
  )
}

export function deletePrompt(id: number) {
  return apiDelete<{ success: boolean }>(`/api/prompts/${id}`)
}

export function batchFavoritePrompts(ids: number[]) {
  return apiPost<{ success: boolean }>('/api/prompts/batch_favorite', { ids }, { favorite: true })
}

export function batchDeletePrompts(ids: number[]) {
  return apiPost<{ success: boolean; deleted: number }>('/api/prompts/batch_delete', { ids })
}

export function importPrompts(prompts: unknown[]) {
  return apiPost<{ success: boolean; imported: number; message: string }>(
    '/api/prompts/import',
    { prompts },
  )
}
