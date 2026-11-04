<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useQuery } from '@tanstack/vue-query'

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
 * 后端未下发地址或接口失败时回落 `/ref-web/`，与阶段一兜底一致。
 */

/** 后端未下发入口或请求失败时的兜底地址。 */
const REFERENCE_WEB_FALLBACK = '/ref-web/'

/** `/api/system/status` 的参考图库扩展字段（openapi 里尚未声明）。 */
interface SystemStatusWithReference extends SystemStatus {
  reference_web_url?: string | null
}

const { data: status } = useQuery({
  queryKey: ['status'],
  queryFn: getSystemStatus,
})

const referenceWebUrl = computed(
  () => (status.value as SystemStatusWithReference | undefined)?.reference_web_url ?? '',
)

/** iframe 首次加载完成前显示占位，`load` 事件后隐藏。 */
const loaded = ref(false)

/**
 * 组装 iframe 地址：
 * - 空值回落 `/ref-web/`；
 * - 目录入口补尾斜杠，`/ref-web` 与 `/ref-web/` 都归一为 `/ref-web/`，
 *   避免静态挂载多一次 307；
 * - 强制 `embedded=1`，保留其它既有 query；
 * - 同源时只取 pathname + search，避免后端下发 host/端口与当前反代不一致；
 *   跨源地址保留完整 URL。
 */
function buildEmbedSrc(raw: string | null | undefined): string {
  const base = raw?.trim() || REFERENCE_WEB_FALLBACK
  try {
    const url = new URL(base, window.location.origin)
    if (!url.pathname.endsWith('/')) {
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

const embedSrc = computed(() => buildEmbedSrc(referenceWebUrl.value))

/**
 * 只有最终 src 变化时才重新等待加载：`reference_web_url` 从空值变为
 * 默认值 `/ref-web` 时 embedSrc 仍是 `/ref-web/`，若按原始 URL 监听会把
 * 已加载完成的占位重新挂出来，而 src 没变又不会再触发 load，占位会卡住。
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