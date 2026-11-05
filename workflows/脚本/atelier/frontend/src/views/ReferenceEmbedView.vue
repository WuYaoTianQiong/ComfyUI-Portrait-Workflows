<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { useRoute } from 'vue-router'

import { getSystemStatus, type SystemStatus } from '../api/endpoints'

/**
 * 参考图库（上游 React 台 `/ref-web`）的 iframe 承载页。
 *
 * 阶段一曾用 `location.replace('/ref-web/')` 整页跳走；用户本轮拍板改为
 * iframe 承载，外层 Vue 的顶栏与导航常驻，切页完全无感。
 *
 * 地址仍来自后端 `/api/system/status` 的 `reference_web_url`（可能是
 * `/ref-web` 或 `/ref-web/`）。iframe 必须带 `embedded=1`：gallery-web
 * 只有「在 iframe 内且该参数为 1」时才隐藏自己的全局导航（见 gallery-web
 * `src/lib/embedded.ts`），否则会出现两套导航。
 *
 * 另外支持 `?path=` 深链：gallery-web 在非内嵌状态直接打开 `/ref-web/poses`
 * 之类的旧链接时，会整页 replace 到 `/reference?path=<原始深链>`；本页校验
 * 通过后把该 path 作为 iframe 的 base，保留原来的菜单定位与 query。
 *
 * 后端未下发地址或接口失败时回落 `/ref-web/`，与阶段一兜底一致。
 */

/** React 参考图库的挂载前缀；`path` 深链必须落在这个前缀下。 */
const REFERENCE_WEB_PATH = '/ref-web'

/** 后端未下发入口或请求失败时的兜底地址。 */
const REFERENCE_WEB_FALLBACK = '/ref-web/'

/** `/api/system/status` 的参考图库扩展字段（openapi 里尚未声明）。 */
interface SystemStatusWithReference extends SystemStatus {
  reference_web_url?: string | null
}

const route = useRoute()

/**
 * 校验 `?path=` 深链的原始字符串。
 *
 * 只接受：
 * - `/ref-web` 本身，或其后紧跟 `/`、`?`、`#` 的深链（避免 `/ref-webevil` 混入）；
 * - 不含 `..`（路径穿越）、`//`（协议相对地址或主机注入）、`\`（部分浏览器等价 `/`）、
 *   `:`（绝对 URL / 端口注入）的值。
 *
 * 不合法一律返回 null，由调用方回落到 `reference_web_url`，页面不白屏。
 */
function sanitizeReferencePath(value: unknown): string | null {
  // vue-router 的 query 可能是字符串数组（重复参数）；只取第一个，其余忽略。
  const raw = Array.isArray(value) ? value[0] : value
  if (typeof raw !== 'string') return null

  const path = raw.trim()
  if (!path) return null

  const hasValidPrefix =
    path === REFERENCE_WEB_PATH ||
    path.startsWith(`${REFERENCE_WEB_PATH}/`) ||
    path.startsWith(`${REFERENCE_WEB_PATH}?`) ||
    path.startsWith(`${REFERENCE_WEB_PATH}#`)
  if (!hasValidPrefix) return null

  if (path.includes('..') || path.includes('//') || path.includes('\\') || path.includes(':')) {
    return null
  }

  return path
}

/**
 * 同源解析后再次校验实际 pathname。
 *
 * 百分号编码的目录穿越（例如 `%2e%2e` 被 WHATWG URL 当作 `.` 处理）能绕过
 * 字符串层面的 `..` 检查，因此必须看解析结果，并确认仍落在 `/ref-web` 下。
 * 返回归一化后的 path + search + hash；校验失败返回 null。
 */
function resolveExplicitPath(path: string): string | null {
  try {
    const url = new URL(path, window.location.origin)
    if (url.origin !== window.location.origin) return null

    if (url.pathname !== REFERENCE_WEB_PATH && !url.pathname.startsWith(`${REFERENCE_WEB_PATH}/`)) {
      return null
    }

    return `${url.pathname}${url.search}${url.hash}`
  } catch {
    return null
  }
}

const { data: status } = useQuery({
  queryKey: ['status'],
  queryFn: getSystemStatus,
})

const referenceWebUrl = computed(
  () => (status.value as SystemStatusWithReference | undefined)?.reference_web_url ?? '',
)

/** 校验并归一化后的深链；null 表示没有 `?path=` 或该值不合法。 */
const explicitReferencePath = computed(() => {
  const path = sanitizeReferencePath(route.query.path)
  return path ? resolveExplicitPath(path) : null
})

/** iframe 首次加载完成前显示占位，`load` 事件后隐藏。 */
const loaded = ref(false)

/**
 * 组装 iframe 地址：
 * - 有合法深链时以该 path 为 base（同源解析），否则用 `reference_web_url`；
 * - 空值回落 `/ref-web/`；
 * - 目录入口补尾斜杠：`/ref-web` 与 `/ref-web/` 都归一为 `/ref-web/`，避免静态
 *   挂载多一次 307；深链（如 `/ref-web/poses`）不是目录，保持原样；
 * - 强制 `embedded=1`，保留其它既有 query；
 * - 同源时只取 pathname + search，避免后端下发 host/端口与当前反代不一致；
 *   跨源地址保留完整 URL。
 */
function buildEmbedSrc(raw: string | null | undefined, explicitPath: string | null): string {
  const base = explicitPath ?? (raw?.trim() || REFERENCE_WEB_FALLBACK)
  try {
    const url = new URL(base, window.location.origin)
    if (!url.pathname.endsWith('/') && (url.pathname === REFERENCE_WEB_PATH || !explicitPath)) {
      url.pathname = `${url.pathname}/`
    }
    url.searchParams.set('embedded', '1')
    if (url.origin === window.location.origin) {
      return `${url.pathname}${url.search}${url.hash}`
    }
    return url.toString()
  } catch {
    // 极端脏值（例如带非法字符）交给浏览器按原样处理，不让页面白屏。
    return base
  }
}

const embedSrc = computed(() => buildEmbedSrc(referenceWebUrl.value, explicitReferencePath.value))

/**
 * 只有最终 src 变化时才重新等待加载：`reference_web_url` 从空值变为
 * 默认值 `/ref-web` 时 embedSrc 仍是 `/ref-web/`，若按原始 URL 监听会把
 * 已加载完成的占位重新挂出来，而 src 没变又不会再触发 load，占位会卡住。
 * 深链切换（`?path=` 变化）同样会命中这里，重新展示加载占位。
 */
watch(embedSrc, () => {
  loaded.value = false
})
</script>

<template>
  <div class="reference-embed">
    <iframe
      :src="embedSrc"
      title="参考图库"
      class="ref-frame"
      allow="fullscreen"
      @load="loaded = true"
    />
    <div v-if="!loaded" class="ref-placeholder">正在加载参考图库…</div>
  </div>
</template>

<style scoped>
.reference-embed {
  position: relative;
  width: 100%;
  height: 100%;
  border: 0;
  display: block;
  background: var(--panel);
}

.ref-frame {
  width: 100%;
  height: 100%;
  border: 0;
  display: block;
  background: var(--panel);
}

/* 加载前的极简占位：盖在 iframe 上，加载完成后移除，不打断 iframe。 */
.ref-placeholder {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  background: var(--panel);
  color: var(--muted);
  font-size: var(--fs-sm);
}
</style>