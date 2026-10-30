<script setup lang="ts">
import { computed, ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'

import GalleryView from './views/GalleryView.vue'
import PromptView from './views/PromptView.vue'
import ComposerView from './views/ComposerView.vue'
import { apiGet } from './api/client'

/** ComfyUI 在线状态：离线时不该让用户以为能出图（历史上因此白跑 27 个任务）。 */
const { data: status } = useQuery<{ comfyui: string }>({
  queryKey: ['status'],
  queryFn: () => apiGet('/api/status'),
  refetchInterval: 10_000,
})

const online = computed(() => status.value?.comfyui === 'online')

/**
 * 壳层：一个极简页签。
 *
 * 目前只迁了画廊（旧前端里痛点最集中的一页：734 行 gallery.js + 956 行
 * imageViewer.js）。提示词页/组合器在 S2-3、S2-4 按同样方式接入，
 * 旧页面在此期间保持可用（新前端只跑在 5173）。
 */
type TabKey = 'gallery' | 'prompt' | 'composer'

const activeTab = ref<TabKey>('gallery')
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <span class="logo">PB</span>
        <span class="title">Prompt Browser</span>
        <span class="badge">Vue 重构版 · 开发中</span>
      </div>

      <nav class="tabs">
        <button
          class="btn btn-sm"
          :class="{ active: activeTab === 'gallery' }"
          @click="activeTab = 'gallery'"
        >
          画廊
        </button>
        <button
          class="btn btn-sm"
          :class="{ active: activeTab === 'prompt' }"
          @click="activeTab = 'prompt'"
        >
          提示词
        </button>
        <button
          class="btn btn-sm"
          :class="{ active: activeTab === 'composer' }"
          @click="activeTab = 'composer'"
        >
          组合器
        </button>
      </nav>

      <div class="status" :class="{ online }">
        <span class="dot" />
        <span>{{ online ? 'ComfyUI 在线' : 'ComfyUI 离线' }}</span>
      </div>

      <a class="legacy-link" href="http://127.0.0.1:8656/" target="_blank" rel="noreferrer">
        打开旧版 ↗
      </a>
    </header>

    <main class="content">
      <GalleryView v-if="activeTab === 'gallery'" />
      <ComposerView v-else-if="activeTab === 'composer'" />
      <PromptView v-else />
    </main>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.topbar {
  display: flex;
  align-items: center;
  gap: var(--gap);
  padding: 0 var(--gap-lg);
  height: 52px;
  border-bottom: 1px solid var(--border);
  background: var(--panel);
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
}

.logo {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: var(--radius-sm);
  background: var(--primary);
  font-size: var(--fs-sm);
  font-weight: 700;
}

.title {
  font-size: var(--fs-lg);
  font-weight: 600;
}

.badge {
  font-size: var(--fs-xs);
  color: var(--muted);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 1px 8px;
}

.tabs {
  display: flex;
  gap: var(--gap-xs);
  margin-left: var(--gap-lg);
}

.status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-xs);
  color: var(--muted);
  margin-left: auto;
}

.status .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--danger);
}

.status.online .dot {
  background: var(--success);
}

.status.online {
  color: var(--muted);
}

.legacy-link {
  font-size: var(--fs-sm);
  color: var(--muted);
  text-decoration: none;
}

.legacy-link:hover {
  color: var(--primary);
}

.content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
</style>
