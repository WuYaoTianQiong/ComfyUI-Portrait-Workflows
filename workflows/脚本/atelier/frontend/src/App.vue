<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQuery } from '@tanstack/vue-query'

import ToastHost from './components/ToastHost.vue'
import OutputLocationField from './components/OutputLocationField.vue'
import { getSystemStatus, listJobs, type SystemStatus } from './api/endpoints'
import { setupNaive } from './utils/naive'
import {
  applyInitialTheme,
  applyTheme,
  persistTheme,
  readStoredTheme,
  toggledTheme,
  type Theme,
} from './utils/theme'

// 只初始化一次；测试不挂载 App，不会触发
setupNaive()

/**
 * 主题状态。
 *
 * `applyInitialTheme()` 在 main.ts 挂载前已执行过一次；这里再读一次是为了
 * 组件被单独挂载（测试 / 嵌入）时也能拿到一致的值。切换时同步三件事：
 * 更新 `<html data-theme>`、写入 `pb.theme_v1`、更新按钮文案。
 */
const theme = ref<Theme>(readStoredTheme())
applyInitialTheme()

const themeLabel = computed(() => (theme.value === 'dark' ? '浅色' : '深色'))
const themeAriaLabel = computed(() => `切换到${themeLabel.value}主题`)

function switchTheme() {
  theme.value = toggledTheme(theme.value)
  applyTheme(theme.value)
  persistTheme(theme.value)
}

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
 * 参考图库入口开关。
 *
 * `ATELIER_REFERENCE_ENABLED=0` 时后端不注册 `/api/reference/*`，入口也不渲染；
 * 旧后端没有该字段时按开启处理。阶段 4.3 起旧的状态字段随旧静态挂载
 * 一并移除，入口只由开关决定（纯 Vue 版不再有第二套地址）。
 */
const referenceEnabled = computed(
  () =>
    (status.value as (SystemStatus & { reference_enabled?: boolean }) | undefined)
      ?.reference_enabled !== false,
)

const showReferenceEntry = computed(() => referenceEnabled.value)

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
        <button
          v-if="showReferenceEntry"
          class="btn btn-sm"
          :class="{ active: activeKey === 'reference' }"
          @click="go('reference')"
        >
          参考图库
        </button>
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

      <button
        class="btn btn-sm theme-toggle"
        type="button"
        :aria-label="themeAriaLabel"
        :title="themeAriaLabel"
        @click="switchTheme"
      >
        {{ themeLabel }}
      </button>

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
  /* 品牌区不参与收缩，窄屏优先压缩中部 tabs。 */
  flex-shrink: 0;
}

.logo {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: var(--radius-sm);
  background: var(--primary);
  /* 品牌块上的字必须用反色前景：浅色主题的 primary 更深，不能再继承正文黑字。 */
  color: var(--on-primary);
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
  /* 窄屏允许压缩并在内部横向滚动，避免 9 个页签撑破页面宽度。 */
  flex: 1 1 auto;
  min-width: 0;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: none;
}

.tabs::-webkit-scrollbar {
  display: none;
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
  color: var(--on-primary);
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
  /* 状态区不参与收缩，窄屏单独隐藏，避免继续与 tabs 抢宽度。 */
  flex-shrink: 0;
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

/* 主题切换按钮：文案显示「要切到的主题」，不参与窄屏收缩。 */
.theme-toggle {
  flex: none;
}

/* 窄屏：压缩顶栏留白，隐藏状态文字；页签仍可横向滚动，桌面端视觉不变。 */
@media (max-width: 640px) {
  .topbar {
    padding: 0 12px;
    gap: 8px;
  }

  .tabs {
    margin-left: 8px;
  }

  .status {
    display: none;
  }

  /* 出图位置保持内容宽度；否则会被压到 30px 左右，内部文字溢出顶栏。 */
  .topbar > .output-location {
    flex-shrink: 0;
  }
}

.content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
</style>