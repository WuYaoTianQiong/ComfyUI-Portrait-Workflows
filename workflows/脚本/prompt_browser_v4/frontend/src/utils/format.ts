import type { HistoryItem } from '../api/types'

export function formatSize(bytes?: number): string {
  if (!bytes) return ''
  return bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.round(bytes / 1024)} KB`
}

export function resolution(item: Pick<HistoryItem, 'width' | 'height'>): string {
  return item.width && item.height ? `${item.width}×${item.height}` : ''
}

/** captured_at 是真实出图时间（文件 mtime），created_at 只是入库时间。 */
export function shotTime(item: Pick<HistoryItem, 'captured_at' | 'created_at'>): string {
  const raw = item.captured_at || item.created_at
  if (!raw) return ''
  return raw.replace('T', ' ').slice(0, 16)
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
    faceswap: '换脸',
  }
  return map[source] ?? source ?? ''
}
