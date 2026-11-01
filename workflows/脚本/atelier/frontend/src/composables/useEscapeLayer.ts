import { onBeforeUnmount, watch, type Ref } from 'vue'

/**
 * 弹层 Esc 栈。
 *
 * 旧实现每个 Modal / Lightbox / CompareModal 各自监听 window keydown，一次 Esc
 * 会把所有打开的层一起关掉。这里维护一个模块级栈：只有最后打开的层响应 Esc，
 * 并且关闭后焦点回到打开前的元素。
 */
interface EscapeLayer {
  id: symbol
  close: () => void
}

const layers: EscapeLayer[] = []
let listening = false

function onKey(event: KeyboardEvent) {
  if (event.key !== 'Escape' || event.defaultPrevented) return
  const top = layers[layers.length - 1]
  if (!top) return
  event.preventDefault()
  top.close()
}

function ensureListener() {
  if (listening || typeof window === 'undefined') return
  window.addEventListener('keydown', onKey)
  listening = true
}

function removeLayer(id: symbol) {
  const index = layers.findIndex((layer) => layer.id === id)
  if (index >= 0) layers.splice(index, 1)
  if (!layers.length && listening) {
    window.removeEventListener('keydown', onKey)
    listening = false
  }
}

export function useEscapeLayer(
  active: Ref<boolean> | (() => boolean),
  close: () => void,
): void {
  const id = Symbol('escape-layer')
  const isActive = typeof active === 'function' ? active : () => active.value

  watch(
    isActive,
    (open) => {
      removeLayer(id)
      if (open) {
        ensureListener()
        layers.push({ id, close })
      }
    },
    { immediate: true },
  )

  onBeforeUnmount(() => removeLayer(id))
}
