import type { GenerationHistoryItem } from '@/types/gallery'
import { idbGet } from './idbStorage'

/**
 * 与 studioStore 中 HISTORY_KEY 保持一致。
 * 本模块只读取该键，绝不调用任何删除或清空 IDB 的操作。
 */
export const LEGACY_HISTORY_KEY = 'pose_atlas_history_v3'

export interface LegacyExportSummary {
  count: number
  jsonName: string
  pngNames: string[]
  failures: Array<{ id: string; reason: string }>
}

const JSON_FILE_PREFIX = 'gallery-web-legacy-history'
/** 连续多文件下载容易被浏览器拦截，逐张之间至少留出该间隔。 */
const DOWNLOAD_INTERVAL_MS = 150

function pad(value: number, length = 2): string {
  return String(value).padStart(length, '0')
}

/** 生成 `gallery-web-legacy-history-YYYYMMDD-HHmmss.json`。 */
function buildJsonName(date: Date): string {
  const stamp = `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`
  return `${JSON_FILE_PREFIX}-${stamp}.json`
}

/** 只保留文件名安全字符，避免 id 中的特殊字符影响下载名。 */
function sanitizeFileSegment(value: string): string {
  const cleaned = value
    .replace(/[^a-zA-Z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48)
  return cleaned || 'record'
}

/**
 * 旧数据可能来自更早版本，这里做最小校验与字段归一化，
 * 保证返回的条目符合 GenerationHistoryItem 且不会把 undefined 带进导出 JSON。
 */
function normalizeLegacyItem(raw: unknown): GenerationHistoryItem | null {
  if (!raw || typeof raw !== 'object') return null
  const record = raw as Record<string, unknown>

  const rawId = record.id
  const id = typeof rawId === 'string' || typeof rawId === 'number' ? String(rawId) : ''
  if (!id) return null

  return {
    id,
    createdAt: typeof record.createdAt === 'number' ? record.createdAt : Date.now(),
    provider: 'comfyui',
    model: typeof record.model === 'string' ? record.model : '',
    prompt: typeof record.prompt === 'string' ? record.prompt : '',
    imageUrl: typeof record.imageUrl === 'string' ? record.imageUrl : '',
    recipeSummary: typeof record.recipeSummary === 'string' ? record.recipeSummary : '',
  }
}

/** 读取 IndexedDB 中的旧生成记录；不存在或读取失败均返回空数组。 */
export async function readLegacyHistory(): Promise<GenerationHistoryItem[]> {
  try {
    const stored = await idbGet<unknown>(LEGACY_HISTORY_KEY)
    if (!Array.isArray(stored)) return []
    return stored
      .map(normalizeLegacyItem)
      .filter((item): item is GenerationHistoryItem => item !== null)
  } catch {
    return []
  }
}

/** 把 data URL 直接解析为 Blob，避免多余的 fetch 往返。 */
function dataUrlToBlob(dataUrl: string): Blob {
  const commaIndex = dataUrl.indexOf(',')
  if (commaIndex < 0) throw new Error('图片数据格式无效')

  const meta = dataUrl.slice('data:'.length, commaIndex)
  const payload = dataUrl.slice(commaIndex + 1)
  const mime = meta.split(';')[0] || 'image/png'
  if (!mime.startsWith('image/')) throw new Error('图片数据格式无效')

  let bytes: Uint8Array<ArrayBuffer>
  if (/;base64/i.test(meta)) {
    const binary = atob(payload.replace(/\s/g, ''))
    bytes = new Uint8Array(binary.length)
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index)
    }
  } else {
    // 兼容极少数非 base64 的 data URL，按百分号转义逐字节还原。
    const decoded: number[] = []
    for (let index = 0; index < payload.length; index += 1) {
      if (payload[index] === '%' && index + 2 < payload.length) {
        const code = Number.parseInt(payload.slice(index + 1, index + 3), 16)
        if (!Number.isNaN(code)) {
          decoded.push(code)
          index += 2
          continue
        }
      }
      decoded.push(payload.charCodeAt(index) & 0xff)
    }
    bytes = new Uint8Array(decoded)
  }

  return new Blob([bytes], { type: mime })
}

/** 将 data URL、同源路径或 http(s) 地址统一取成图片 Blob。 */
async function loadImageBlob(imageUrl: string): Promise<Blob> {
  const url = imageUrl.trim()
  if (!url) throw new Error('图片地址为空')
  if (url.startsWith('data:image/')) return dataUrlToBlob(url)

  const isRemote = /^https?:\/\//i.test(url)
  if (!isRemote && !url.startsWith('/')) throw new Error('不支持的图片地址')

  const response = await fetch(url)
  if (!response.ok) throw new Error(`图片下载失败：HTTP ${response.status}`)
  const blob = await response.blob()
  if (!blob.type.startsWith('image/')) throw new Error('返回内容不是图片')
  return blob
}

/** 用临时 object URL 触发一次浏览器下载，随后释放资源。 */
function triggerBlobDownload(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = filename
  anchor.style.display = 'none'
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 10_000)
}

function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, milliseconds)
  })
}

/**
 * 导出旧生成记录：一个 JSON（记录元数据）+ 逐张 PNG。
 * 无数据时返回 count=0 且不触发下载；单张图片失败只记录原因并继续。
 */
export async function exportLegacyHistory(): Promise<LegacyExportSummary> {
  const items = await readLegacyHistory()
  if (items.length === 0) {
    return { count: 0, jsonName: '', pngNames: [], failures: [] }
  }

  const jsonName = buildJsonName(new Date())
  const records = items.map((item) => ({
    id: item.id,
    createdAt: item.createdAt,
    prompt: item.prompt,
    recipeSummary: item.recipeSummary,
    model: item.model,
    imageUrl: item.imageUrl,
  }))
  triggerBlobDownload(
    new Blob([JSON.stringify(records, null, 2)], { type: 'application/json' }),
    jsonName,
  )

  const pngNames: string[] = []
  const failures: LegacyExportSummary['failures'] = []

  for (let index = 0; index < items.length; index += 1) {
    // JSON 下载与第一张 PNG、以及相邻 PNG 之间都留出间隔。
    await sleep(DOWNLOAD_INTERVAL_MS)
    const item = items[index]
    const pngName = `legacy-${index + 1}-${sanitizeFileSegment(item.id)}.png`
    try {
      const blob = await loadImageBlob(item.imageUrl)
      triggerBlobDownload(blob, pngName)
      pngNames.push(pngName)
    } catch (error) {
      failures.push({
        id: item.id,
        reason: error instanceof Error ? error.message : '图片下载失败',
      })
    }
  }

  return { count: items.length, jsonName, pngNames, failures }
}