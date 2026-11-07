/**
 * 统一错误文案：`ApiError` 带 status 时按类别给出可执行提示，
 * 普通 Error 保持原样。刻意不 import ApiError，避免测试里 mock client 后
 * `instanceof` 失效。
 */
export function formatApiError(error: unknown, fallback = '请求失败'): string {
  const message = error instanceof Error ? error.message : String(error ?? '')
  const status = (error as { status?: unknown } | null)?.status
  if (typeof status === 'number') {
    const clean = message.replace(/^\d{3}\s*/, '') || fallback
    if (status === 400) return `请求不合法：${clean}`
    if (status === 404) return `未找到：${clean}`
    if (status === 409) return `状态冲突：${clean}`
    if (status >= 500) return `服务端错误：${clean}`
    return clean
  }
  return message || fallback
}
