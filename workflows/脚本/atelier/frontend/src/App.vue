<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQuery } from '@tanstack/vue-query'

import ToastHost from './components/ToastHost.vue'
import OutputLocationField from './components/OutputLocationField.vue'
import { getSystemStatus, listJobs, type SystemStatus } from './api/endpoints'
import { setupNaive } from './utils/naive'

// 只初始化一次；测试不挂载 App，不会触发
setupNaive()

/**
 * 顶栏的「进行中任务」角标。
 *
 * 只查 active 的任务、每 5 秒一次 —— 任务中心页面自己走 SSE 实时推送，
 * 这里只需要一个粗粒度计数，不值得再开一条长连接。
 */
const { data: activeJobs } = useQuery({
  queryKey: ['jobs', 'active-badge'],
  queryFn: () => listJobs({ active: true, limit: 50 }),
  refetchInterval: 5_000,
  staleTime: 2_000,
})

const activeCount = computed(() => activeJobs.value?.jobs?.length ?? 0)

/** ComfyUI 在线状态：离线时不该让用户以为能出图（历史上因此白跑 27 个任务）。 */
const { data: status } = useQuery({
  queryKey: ['status'],
  queryFn: getSystemStatus,
  refetchInterval: 10_000,
})

const online = computed(() => status.value?.comfyui === 'online')


/**
 * 参考图库 Web（上游 React 台）入口。
 *
 * 后端未下发地址（旧后端）或显式置空时不渲染；v0.8 起同源 `/ref-web`，
 * 因此同标签打开，不再新开窗口。
 */
const referenceWebUrl = computed(
  () =>
    (status.value as (SystemStatus & { reference_web_url?: string | null }) | undefined)
      ?.reference_web_url ?? '',
)

const route = useRoute()
const router = useRouter()

/** 当前页签：路径第一段（/gallery → gallery）。 */
const activeKey = computed(() => route.path.split('/')[1] || 'gallery')

function go(key: string) {
  router.push(`/${key}`)
}

/** 从画廊「跳到提示词」：走真实路由，可深链、可返回。 */
function jumpToPrompt(promptId: number) {
  router.push(`/prompt/${promptId}`)
}
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <span class="logo">AT</span>
        <span class="title">画室 Atelier</span>
      </div>

      <nav class="tabs">
        <button
          class="btn btn-sm"
          :class="{ active: activeKey === 'gallery' }"
          @click="go('gallery')"
        >
          画廊
        </button>
        <a
          v-if="referenceWebUrl"
          class="btn btn-sm"
          :href="referenceWebUrl"
        >
          参考图库
        </a>
        <button
          class="btn btn-sm"
          :class="{ active: activeKey === 'prompt' }"
          @click="go('prompt')"
        >
          提示词
        </button>
        <button
          class="btn btn-sm"
          :class="{ active: activeKey === 'composer' }"
          @click="go('composer')"
        >
          组合器
        </button>
        <button
          class="btn btn-sm"
          :class="{ active: activeKey === 'editor' }"
          @click="go('editor')"
        >
          图像编辑
        </button>
        <button
          class="btn btn-sm"
          :class="{ active: activeKey === 'upscale' }"
          @click="go('upscale')"
        >
          批量超分
        </button>
        <button
          class="btn btn-sm"
          :class="{ active: activeKey === 'taxonomy' }"
          @click="go('taxonomy')"
        >
          分类与标签
        </button>
        <button
          class="btn btn-sm"
          :class="{ active: activeKey === 'jobs' }"
          @click="go('jobs')"
        >
          任务
          <span v-if="activeCount" class="job-badge">{{ activeCount }}</span>
        </button>
        <button
          class="btn btn-sm"
          :class="{ active: activeKey === 'stats' }"
          @click="go('stats')"
        >
          统计
        </button>
      </nav>

      <div class="status" :class="{ online }">
        <span class="dot" />
        <span>{{ online ? 'ComfyUI 在线' : 'ComfyUI 离线' }}</span>
      </div>

      <OutputLocationField />
    </header>

    <main class="content">
      <RouterView v-slot="{ Component }">
        <component :is="Component" @jump-to-prompt="jumpToPrompt" />
      </RouterView>
    </main>

    <ToastHost />
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

.tabs {
  display: flex;
  gap: var(--gap-xs);
  margin-left: var(--gap-lg);
  align-items: center;
}

.job-badge {
  display: inline-grid;
  place-items: center;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  margin-left: 4px;
  border-radius: 999px;
  background: var(--primary);
  color: #fff;
  font-size: 10px;
  line-height: 1;
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

.content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
</style>