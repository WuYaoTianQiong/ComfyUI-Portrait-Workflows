import { ref } from 'vue'

export type ToastKind = 'info' | 'success' | 'error'

export interface ToastMessage {
  id: number
  text: string
  kind: ToastKind
}

/**
 * 全局轻提示。
 *
 * 旧前端靠 `window.showToast()` —— 一个全局函数 + 一个全局容器，跨模块靠约定串联。
 * 这里做成模块级单例 + 显式 composable：调用点看得出来源，也不依赖加载顺序。
 */
const toasts = ref<ToastMessage[]>([])
let seq = 0

export function useToast() {
  function push(text: string, kind: ToastKind = 'info', ttl = 4000) {
    const id = ++seq
    toasts.value = [...toasts.value, { id, text, kind }]
    setTimeout(() => {
      toasts.value = toasts.value.filter((t) => t.id !== id)
    }, ttl)
  }

  return {
    toasts,
    info: (text: string) => push(text, 'info'),
    success: (text: string) => push(text, 'success'),
    error: (text: string) => push(text, 'error', 7000),
  }
}
