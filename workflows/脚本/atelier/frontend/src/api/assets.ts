/** 资产元数据覆盖层：18+ 分级 / 姿势可用性 / 人数风险（只写 atelier DB）。 */
import { apiPost, apiPut } from './client'

export interface AssetOverridePatch {
  /** `''` = 清空为继承素材默认；`nsfw` / `safe` = 显式分级 */
  rating?: 'nsfw' | 'safe' | ''
  usable?: boolean
  usable_note?: string
  risk?: string
}

export interface AssetOverrideRow {
  asset_type: string
  asset_key: string
  rating: string | null
  usable: boolean | null
  usable_note: string
  risk: string
  updated_at: string
}

export function setAssetOverride(
  assetType: string,
  assetKey: string,
  patch: AssetOverridePatch,
): Promise<AssetOverrideRow> {
  // 工作流类 key 可能带 `/`，按路径段编码，避免被当成多余路由段
  const key = assetKey.split('/').map(encodeURIComponent).join('/')
  return apiPut<AssetOverrideRow>(
    `/api/assets/overrides/${encodeURIComponent(assetType)}/${key}`,
    patch,
  )
}

/**
 * 批量写覆盖（画廊"标记 18+ / 安全"用）。
 *
 * 一次请求写完全部选中项：几百张图逐张 PUT 既慢又会把对话框卡住。
 */
export function batchSetAssetOverrides(
  assetType: string,
  keys: string[],
  patch: AssetOverridePatch,
): Promise<{ updated: number }> {
  return apiPost<{ updated: number }>('/api/assets/overrides/batch', {
    asset_type: assetType,
    keys,
    ...patch,
  })
}
