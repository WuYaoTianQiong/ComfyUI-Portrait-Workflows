import { onBeforeUnmount } from 'vue'

/** 浏览器对 <img> 没有超时机制：请求挂起（后端重启、代理卡死）会永远停在「加载中」。 */
export function useLoadTimeout(onTimeout: () => void, ms = 30_000) {
  let timer: number | null = null

  function stop() {
    if (timer !== null) {
      window.clearTimeout(timer)
      timer = null
    }
  }

  function start() {
    stop()
    timer = window.setTimeout(() => {
      timer = null
      onTimeout()
    }, ms)
  }

  onBeforeUnmount(stop)

  return { start, stop }
}