import type { HistoryItem } from '../api/types'

export function formatSize(bytes?: number | null): string {
  if (!bytes) return ''
  return bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.round(bytes / 1024)} KB`
}

export function resolution(item: {
  width?: number | null
  height?: number | null
}): string {
  return item.width && item.height ? `${item.width}×${item.height}` : ''
}

/** captured_at 是真实出图时间（文件 mtime），created_at 只是入库时间。 */
export function shotTime(item: Pick<HistoryItem, 'captured_at' | 'created_at'>): string {
  const raw = item.captured_at || item.created_at
  if (!raw) return ''
  return raw.replace('T', ' ').slice(0, 16)
}

/** 秒 → `45s` / `2m03s` / `1h02m` / `2天3h`。 */
export function formatElapsed(seconds?: number | null): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return ''
  const total = Math.max(0, Math.round(seconds))
  if (total < 60) return `${total}s`
  const minutes = Math.floor(total / 60)
  if (minutes < 60) return `${minutes}m${String(total % 60).padStart(2, '0')}s`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h${String(minutes % 60).padStart(2, '0')}m`
  return `${Math.floor(hours / 24)}天${hours % 24}h`
}

/**
 * 后端时间统一是带 Z 的 UTC ISO；这里转成本机时间显示。
 * 不带时区的老字符串照原样截断，避免被 `new Date()` 再按本地解析一次。
 */
export function formatDateTime(iso?: string | null, withSeconds = false): string {
  if (!iso) return ''
  if (!/[zZ]|[+-]\d{2}:\d{2}$/.test(iso)) return iso.replace('T', ' ').slice(0, withSeconds ? 19 : 16)
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  const head = `${d.getMonth() + 1}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  return withSeconds ? `${head}:${pad(d.getSeconds())}` : head
}

/** 任务状态中文化：后端返回 pending/running/done/error/cancelled/stopped。 */
const STATUS_LABEL: Record<string, string> = {
  pending: '排队中',
  running: '生成中',
  done: '完成',
  error: '失败',
  cancelled: '已取消',
  stopped: '已停止',
}

export function statusLabel(status?: string | null): string {
  return STATUS_LABEL[status ?? ''] ?? status ?? ''
}

/** 来源标签：同步进来的图与本地任务出图在界面上要能区分。 */
export function sourceLabel(source: string): string {
  const map: Record<string, string> = {
    local: '本机出图',
    comfyui_sync: 'ComfyUI 同步',
    disk_scan: '磁盘扫描',
    composer: '组合创作',
    faceswap: '图像编辑',
  }
  return map[source] ?? source ?? ''
}
