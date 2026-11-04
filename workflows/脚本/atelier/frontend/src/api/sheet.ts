/**
 * 参考板导出（M5）。
 *
 * 后端 `GET /api/reference/sheet` 返回 1800×1200 PNG：三张图三列、四张图四列，
 * 等比缩放居中；`labels=false` 是纯图版（可喂给带拼图节点的工作流）。
 *
 * 只做下载，不做灯箱预览；产物不进 `gen_history`，也不参与出图输入。
 */
import { buildQuery } from './client'

export interface ReferenceSheetOptions {
  /** 姿势库条目 id */
  pose?: string | null
  /** 服装库条目 id */
  costume?: string | null
  /** 人像库条目 id */
  portrait?: string | null
  /** 第 4 张上传图的绝对路径（后端只接受 uploads 目录内的文件） */
  extra?: string | null
  /** true = 画「图N · 名称」标题条；false = 纯图拼接。 */
  labels?: boolean
}

export const SHEET_WIDTH = 1800
export const SHEET_HEIGHT = 1200
export const SHEET_FILENAME = 'reference-sheet.png'

/** 拼出可直接给 `<img>` / `fetch` 用的地址；空参数由 buildQuery 跳过。 */
export function referenceSheetUrl(options: ReferenceSheetOptions): string {
  return (
    '/api/reference/sheet' +
    buildQuery({
      pose: options.pose,
      costume: options.costume,
      portrait: options.portrait,
      extra: options.extra,
      labels: options.labels === false ? 0 : 1,
    })
  )
}

async function readError(resp: Response): Promise<string> {
  const text = await resp.text().catch(() => '')
  if (!text) return `${resp.status} 生成参考板失败`
  try {
    const body = JSON.parse(text) as { detail?: unknown }
    if (body.detail !== undefined && body.detail !== null) {
      return typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    }
  } catch {
    // 非 JSON：截断原始响应，避免把整页 HTML 弹到提示里
  }
  return `${resp.status} ${text.slice(0, 200)}`
}

/** 请求参考板，返回 PNG Blob；400 时抛出后端的可读 detail。 */
export async function fetchReferenceSheet(options: ReferenceSheetOptions): Promise<Blob> {
  const resp = await fetch(referenceSheetUrl(options), {
    headers: { Accept: 'image/png' },
  })
  if (!resp.ok) throw new Error(await readError(resp))
  return resp.blob()
}

/** 触发浏览器下载（object URL 用完即回收）。 */
export function downloadBlob(blob: Blob, filename = SHEET_FILENAME): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

/** 一步完成「请求 + 下载」，供按钮直接调用。 */
export async function downloadReferenceSheet(
  options: ReferenceSheetOptions,
  filename = SHEET_FILENAME,
): Promise<void> {
  downloadBlob(await fetchReferenceSheet(options), filename)
}