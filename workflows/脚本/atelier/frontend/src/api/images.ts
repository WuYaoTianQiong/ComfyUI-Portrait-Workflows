/** 图库域：列表 / 分面 / 同步 / 批量删除 / 收藏 / 补齐 / 缺失清理。 */
import { apiGet, apiPost, type QueryParams } from './client'
import type { HistoryPage, ImageFacets, ImageIdsPage } from './types'

export interface LightSyncResult {
  added: number
  total: number
  busy: boolean
}

export interface CleanupSample {
  id: number
  filename: string
  subfolder: string
  img_type: string
}

export interface CleanupPreview {
  success: boolean
  dry_run: boolean
  total: number
  will_clean: number
  samples: CleanupSample[]
  guarded: boolean
  message: string
}

export function listImages(params: QueryParams = {}) {
  return apiGet<HistoryPage>('/api/images', params)
}

export function listImageIds(params: QueryParams = {}) {
  return apiGet<ImageIdsPage>('/api/images/ids', params)
}

export function getImageFacets(params: QueryParams = {}) {
  return apiGet<ImageFacets>('/api/images/facets', params)
}

/** 增量扫描 output 目录；`busy=true` 表示后台已在扫描。 */
export function syncImagesLight() {
  return apiPost<LightSyncResult>('/api/images/sync/light')
}

export function setImageFavorite(id: number) {
  return apiPost<{ success: boolean; is_favorite: boolean }>(`/api/images/${id}/favorite`)
}

/** 临时试跑「存为提示词」后把整批图认领到新提示词名下。 */
export function linkImagesToPrompt(imageIds: number[], promptId: number) {
  return apiPost<{ success: boolean; linked: number }>('/api/images/link_prompt', {
    image_ids: imageIds,
    prompt_id: promptId,
  })
}

export function batchDeleteImages(ids: number[], deleteFiles: boolean) {
  return apiPost<{ success: boolean; deleted: number; files_deleted: number }>(
    '/api/images/batch_delete',
    { ids, delete_files: deleteFiles },
  )
}

export function backfillImageTaxonomy() {
  return apiPost<{ success: boolean; backfilled: number }>('/api/images/backfill_taxonomy')
}

/**
 * 缺失记录清理：默认只预览；执行必须显式 `dryRun: false`（后端还要求 confirm）。
 * 缺失占比过半时后端会熔断拒绝，确认文件确实丢失后可传 `force: true` 强制放行。
 */
export function cleanupMissingImages(
  params: QueryParams = {},
  options: { dryRun: boolean; force?: boolean } = { dryRun: true },
) {
  const query: QueryParams = { ...params, dry_run: options.dryRun }
  if (!options.dryRun) query.confirm = true
  if (options.force) query.force = true
  return apiPost<CleanupPreview & { cleaned?: number }>(
    '/api/images/cleanup_missing',
    undefined,
    query,
  )
}
