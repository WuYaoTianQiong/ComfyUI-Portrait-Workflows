/** 分类与标签：列表 / 增删改 / 自动归类。图片与提示词共用同一套词表。 */
import { apiDelete, apiGet, apiPost, apiPut } from './client'
import type { CategoryNode, TagRow } from './types'

export type CountScope = 'prompt' | 'image'

export interface CategoryListResponse {
  categories: CategoryNode[]
}

export interface TagListResponse {
  tags: TagRow[]
}

export function listCategories(
  params: { tree?: boolean; count_scope?: CountScope } = {},
) {
  return apiGet<CategoryListResponse>('/api/categories', params)
}

export function listTags(params: { count_scope?: CountScope } = {}) {
  return apiGet<TagListResponse>('/api/tags', params)
}

export function createCategory(name: string, color: string) {
  return apiPost<{ success: boolean; id: number }>('/api/categories', { name, color })
}

export function updateCategory(id: number, payload: { name?: string; color?: string }) {
  return apiPut<{ success: boolean }>(`/api/categories/${id}`, payload)
}

export function deleteCategory(id: number) {
  return apiDelete<{ success: boolean }>(`/api/categories/${id}`)
}

export function createTag(name: string, color: string) {
  return apiPost<{ success: boolean; id: number }>('/api/tags', { name, color })
}

export function updateTag(id: number, payload: { name?: string; color?: string }) {
  return apiPut<{ success: boolean }>(`/api/tags/${id}`, payload)
}

export function deleteTag(id: number) {
  return apiDelete<{ success: boolean }>(`/api/tags/${id}`)
}

/** 全库自动归类；返回重新归类的条数。 */
export function autoClassifyAll() {
  return apiPost<{ success: boolean; reclassified: number }>(
    '/api/categories/auto-classify',
  )
}

/** 单条提示词自动归类（按正文里的【类型】数量）。 */
export function autoClassifyPrompt(id: number) {
  return apiPost<{ success: boolean }>(`/api/categories/auto-classify/${id}`)
}
