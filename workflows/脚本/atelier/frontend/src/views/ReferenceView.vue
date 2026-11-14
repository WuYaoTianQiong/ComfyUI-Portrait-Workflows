<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { withReferenceTab } from './reference/referenceDeepLink'
import {
  readLastReferenceTab,
  writeLastReferenceTab,
} from '../composables/useReferenceStudioSettings'

import ReferenceCostumesTab from './reference/ReferenceCostumesTab.vue'
import ReferenceHairTab from './reference/ReferenceHairTab.vue'
import ReferenceHomeTab from './reference/ReferenceHomeTab.vue'
import ReferencePortraitsTab from './reference/ReferencePortraitsTab.vue'
import ReferencePosesTab from './reference/ReferencePosesTab.vue'
import ReferenceSettingsTab from './reference/ReferenceSettingsTab.vue'
import ReferenceStudioTab from './reference/ReferenceStudioTab.vue'

/**
 * 参考图库六页签（阶段 1.1 骨架 + 阶段 2.3b 首页）。
 *
 * 页签是**内容区内的二级导航**：全局顶栏由 Vue 主站 `App.vue` 承担，
 * 这里绝不重复渲染全局导航（施工手册 §3 / §7「全局」行）。
 *
 * 选中态与 URL query `?tab=` 双向同步：
 * - 读：`?tab=` 决定渲染哪个页签；**缺失或非法值回落 `home`（图库总览）**，
 *   任何 URL 都不白屏。这一缺省值在阶段 2.3b 由 `pose` 改为 `home`，
 *   以承接施工手册 §6 的旧首页深链 → `/reference` 映射（React 首页即图库总览）；
 * - 写：点页签用 `router.replace` 覆盖 `tab`，不产生历史堆积（返回键仍回到
 *   进入参考图库之前的页面），并保留其它业务 query。
 *
 * 阶段 4.3 起 `?shell=` 与 `?path=` 已废弃：入口守卫（`router.ts`
 * `normalizeReferenceEntry`）会把它们翻译或剔除，本视图不再需要转发。
 */

/** 合法页签键；顺序即页签条展示顺序（「图库总览」固定第一位）。 */
const TAB_KEYS = ['home', 'pose', 'costume', 'portrait', 'hair', 'studio', 'settings'] as const

type ReferenceTabKey = (typeof TAB_KEYS)[number]

interface TabDefinition {
  key: ReferenceTabKey
  label: string
}

const TABS: readonly TabDefinition[] = [
  { key: 'home', label: '图库总览' },
  { key: 'pose', label: '姿势' },
  { key: 'costume', label: '服装' },
  { key: 'portrait', label: '人像' },
  { key: 'hair', label: '发型' },
  { key: 'studio', label: '合成台' },
  { key: 'settings', label: '设置' },
]

/**
 * 六个页签的图标路径（16×16，stroke-width 1.3、fill none、currentColor）。
 *
 * 全部用 `<path>` 表达，模板只写一次 `<svg>` + `v-for`，避免六个分支模板；
 * 折叠态图标是唯一的身份标识，因此图标必须与页签语义一一对应。
 */
const TAB_ICONS: Record<ReferenceTabKey, readonly string[]> = {
  home: [
    'M3.5 3.5h3.5v3.5H3.5z',
    'M9 3.5h3.5v3.5H9z',
    'M3.5 9h3.5v3.5H3.5z',
    'M9 9h3.5v3.5H9z',
  ],
  pose: [
    'M8 1.9a1.7 1.7 0 1 0 0 3.4 1.7 1.7 0 0 0 0-3.4z',
    'M8 5.5v4.2',
    'M8 6.5 5.7 8.3',
    'M8 6.5 10.3 8.3',
    'M8 9.7 6 13.4',
    'M8 9.7 10 13.4',
  ],
  costume: ['M8 2.5a1.2 1.2 0 1 1 .9 2l4.7 4.9v2.2H2.4v-2.2l4.7-4.9'],
  portrait: [
    'M8 2.6a2.4 2.4 0 1 0 0 4.8 2.4 2.4 0 0 0 0-4.8z',
    'M3.4 13.3c.5-2.3 2.3-3.9 4.6-3.9s4.1 1.6 4.6 3.9',
  ],
  hair: [
    'M4.2 13.2c-.8-2.1-.7-4.6.3-6.6C5.5 4.5 6.7 3 8 3s2.5 1.5 3.5 3.6c1 2 1.1 4.5.3 6.6',
    'M5.4 8.2c.6-.5 1.6-.8 2.6-.8s2 .3 2.6.8',
    'M5.2 11.2c.7-.5 1.7-.8 2.8-.8s2.1.3 2.8.8',
  ],
  studio: [
    'M8 2.4 13.4 5.6 8 8.8 2.6 5.6 8 2.4z',
    'M2.6 8.4 8 11.6l5.4-3.2',
    'M2.6 11.2 8 14.4l5.4-3.2',
  ],
  settings: [
    'M8 5.9a2.1 2.1 0 1 0 0 4.2 2.1 2.1 0 0 0 0-4.2z',
    'M8 2.2v1.6M8 12.2v1.6M2.2 8h1.6M12.2 8h1.6M4 4l1.1 1.1M10.9 10.9 12 12M12 4l-1.1 1.1M5.1 10.9 4 12',
  ],
}

/**
 * 缺省 / 非法值的统一归宿。
 *
 * 必须是 `home`：施工手册 §6 把 React 首页（旧前缀根路径）映射到 `/reference`，
 * 该 URL 不带 `tab` 参数，只有默认渲染「图库总览」才能承接首页功能。
 */
const DEFAULT_TAB: ReferenceTabKey = 'home'

const route = useRoute()
const router = useRouter()

/** 类型守卫：既是白名单校验，也是 TS 窄化。 */
function isTabKey(value: unknown): value is ReferenceTabKey {
  return typeof value === 'string' && (TAB_KEYS as readonly string[]).includes(value)
}

/**
 * 归一 query 里的 `tab`。
 *
 * vue-router 对重复参数（`?tab=xxx&tab=pose`）返回数组：逐个看，取第一个合法值；
 * 全部非法返回 null，由调用方回落 `DEFAULT_TAB`（图库总览）。不抛错、不白屏。
 */
function normalizeTab(value: unknown): ReferenceTabKey | null {
  const candidates = Array.isArray(value) ? value : [value]
  for (const candidate of candidates) {
    if (isTabKey(candidate)) return candidate
  }
  return null
}

/** 本次 URL 上的合法页签；缺失或非法为 null。 */
const queryTab = computed(() => normalizeTab(route.query.tab))

/**
 * 最后访问的页签（挂载时读一次，之后随 activeTab 变更写回）。
 *
 * 优先级（2026-11-05 用户要求记忆操作）：
 * 1. URL 里有合法 `?tab=` → 用它；
 * 2. URL 无 tab → 用存储里的最后页签；
 * 3. 存储值非法 / 不存在 → 回落 `home`（图库总览）。
 *
 * 只改 activeTab 的初始化来源，不改变页签条 / 面板结构与 `selectTab` 的 URL 规则。
 */
const storedTab = ref<string | null>(readLastReferenceTab())

/** 实际生效页签。 */
const activeTab = computed<ReferenceTabKey>(() => {
  if (queryTab.value) return queryTab.value
  const stored = storedTab.value
  return stored !== null && isTabKey(stored) ? stored : DEFAULT_TAB
})

// 记住最后访问的页签；写失败（隐私模式）在 composable 内静默。
watch(
  activeTab,
  (value) => {
    storedTab.value = value
    writeLastReferenceTab(value)
  },
  { immediate: true },
)


const TAB_COMPONENTS = {
  home: ReferenceHomeTab,
  pose: ReferencePosesTab,
  costume: ReferenceCostumesTab,
  portrait: ReferencePortraitsTab,
  hair: ReferenceHairTab,
  studio: ReferenceStudioTab,
  settings: ReferenceSettingsTab,
} as const

const activeComponent = computed(() => TAB_COMPONENTS[activeTab.value])

/**
 * 各页签的垂直滚动位置。
 *
 * `<KeepAlive>` 只保留组件状态，不保留“页面级”滚动容器（`.reference-page`）
 * 的 scrollTop：切换页签时同一个容器继续滚动，切回原页签会停在别人留下的位置。
 * 这里在页签变化前后记录/恢复，补齐「切回后滚动位置不变」的体验。
 *
 * 只在页签切换时读写，不干预 `activeTab` 的读取与写回逻辑。
 */
const pageElement = ref<HTMLElement | null>(null)
const scrollPositions = new Map<ReferenceTabKey, number>()

watch(activeTab, async (nextTab, previousTab) => {
  const page = pageElement.value
  if (!page) return

  // 旧组件的 DOM 在 watcher（pre-flush）阶段仍然挂载，此时读到的就是用户切走前的位置。
  scrollPositions.set(previousTab, page.scrollTop)

  await nextTick()

  // 目标页签首次进入时没有记录，回落到顶部；已缓存的页签恢复原位置。
  const target = scrollPositions.get(nextTab) ?? 0
  if (pageElement.value) pageElement.value.scrollTop = target
})

/**
 * 切换页签：覆盖 `tab` 并保留其它业务 query。
 *
 * 已废弃的 `shell` / `path` 不再写回 URL（阶段 4.3 删除了 iframe 壳与开关，
 * 入口守卫也会把它们剔除）；这里再删一次，避免手工拼出的 URL 把脏参数带下去。
 *
 * 用 replace 而非 push：页签是同一页面内的视图切换，不应该在浏览器历史里
 * 留下 N 条 `/reference` 记录，否则用户要按很多次返回才能离开参考图库。
 */
function selectTab(key: ReferenceTabKey): void {
  // 已经是合法且唯一的同名值，且没有废弃参数，不重复导航。
  if (route.query.tab === key && route.query.shell === undefined && route.query.path === undefined) {
    return
  }

  void router.replace({
    path: route.path,
    query: withReferenceTab(route.query, key),
    hash: route.hash,
  })
}

// ---------------------------------------------------------------------------
// 左导航折叠（M1）：展开 180px / 折叠 64px 图标 rail
// ---------------------------------------------------------------------------

/** 折叠记忆键：带版本后缀，后续改结构时不会误读旧值。 */
const NAV_COLLAPSED_STORAGE_KEY = 'pb.reference_nav_collapsed_v1'

/** 读取折叠记忆；隐私模式 / 存储不可用时静默回落「展开」。 */
function readStoredNavCollapsed(): boolean {
  try {
    return window.localStorage.getItem(NAV_COLLAPSED_STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

/** 用户手动折叠状态（仅 ≥1024 生效；768–1023 由媒体查询强制折叠）。 */
const userCollapsed = ref(
  typeof window === 'undefined' ? false : readStoredNavCollapsed(),
)

/**
 * 768–1023 强制折叠。
 *
 * 该区间若保持 180px 展开态，内容区会被压到不可用宽度，因此由媒体查询接管；
 * 折叠按钮在该区间隐藏，不允许手动展开。
 */
const forceCollapsed = ref(false)

let compactQuery: MediaQueryList | null = null

function syncForceCollapsed(): void {
  forceCollapsed.value = compactQuery?.matches ?? false
}

/** 实际折叠态：强制折叠优先，其次看用户记忆。 */
const navCollapsed = computed(() => forceCollapsed.value || userCollapsed.value)

function toggleNavCollapsed(): void {
  if (forceCollapsed.value) return
  userCollapsed.value = !userCollapsed.value
  try {
    window.localStorage.setItem(
      NAV_COLLAPSED_STORAGE_KEY,
      userCollapsed.value ? '1' : '0',
    )
  } catch {
    // 写不进去不影响本次会话的视觉状态，只是刷新后回到展开。
  }
}

onMounted(() => {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
  compactQuery = window.matchMedia('(min-width: 768px) and (max-width: 1023px)')
  syncForceCollapsed()
  if (typeof compactQuery.addEventListener === 'function') {
    compactQuery.addEventListener('change', syncForceCollapsed)
  }
})

onBeforeUnmount(() => {
  if (compactQuery && typeof compactQuery.removeEventListener === 'function') {
    compactQuery.removeEventListener('change', syncForceCollapsed)
  }
  compactQuery = null
})
</script>

<template>
  <div ref="pageElement" class="reference-page">
    <div class="reference-page__main">
      <div class="reference-page__inner" :class="{ 'is-rail-collapsed': navCollapsed }">
        <!--
          二级导航：桌面（≥768px）是左栏竖排，窄屏回落为顶部横向滚动条。
          全局导航由外层 App.vue 提供，这里不重复渲染。
        -->
        <nav class="reference-tabs" aria-label="参考图库页签">
          <!-- 折叠按钮：rail 顶部右缘（展开态）/ 居中（折叠态）；<768 隐藏 -->
          <div class="reference-tabs__head">
            <button
              type="button"
              class="reference-tabs__toggle"
              data-testid="studio-rail-toggle"
              :aria-expanded="!navCollapsed"
              :aria-label="navCollapsed ? '展开参考图库导航' : '折叠参考图库导航'"
              :title="navCollapsed ? '展开导航' : '折叠导航'"
              @click="toggleNavCollapsed"
            >
              <svg viewBox="0 0 16 16" aria-hidden="true">
                <path
                  :d="navCollapsed ? 'M6 3.5 10.5 8 6 12.5' : 'M10 3.5 5.5 8 10 12.5'"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.3"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </button>
          </div>

          <div class="reference-tabs__list" role="tablist">
            <button
              v-for="tab in TABS"
              :id="`reference-tab-${tab.key}`"
              :key="tab.key"
              type="button"
              class="reference-tab"
              :class="{ 'is-active': tab.key === activeTab }"
              role="tab"
              aria-controls="reference-tab-panel"
              :aria-selected="tab.key === activeTab"
              :title="navCollapsed ? tab.label : undefined"
              @click="selectTab(tab.key)"
            >
              <span class="reference-tab__icon" aria-hidden="true">
                <svg viewBox="0 0 16 16">
                  <path
                    v-for="(d, index) in TAB_ICONS[tab.key]"
                    :key="index"
                    :d="d"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.3"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
              </span>
              <span class="reference-tab__label">{{ tab.label }}</span>
            </button>
          </div>
        </nav>

        <section
          id="reference-tab-panel"
          class="reference-panel"
          role="tabpanel"
          :aria-labelledby="`reference-tab-${activeTab}`"
        >
          <!--
            KeepAlive：切页签只停用/激活组件，不卸载重建。
            库数据、筛选条件与组件内部状态随实例保留，切回时不重新请求四个库。
            不给每个页签传不同 key，否则同一组件也会被强制重建、缓存失效。
          -->
          <KeepAlive :max="TABS.length">
            <component :is="activeComponent" />
          </KeepAlive>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 页面自身滚动：外层 `main.content` 是 overflow: hidden，视图必须自管滚动。 */
.reference-page {
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  background: var(--bg);
}

/* 外层负责 §5 的 main 内边距：≥768px = 左右 32px / 上 16px / 下 40px。 */
.reference-page__main {
  /* 合成台吸底操作条用：fixed 的左右偏移必须与页面留白对齐。 */
  --page-gutter: 32px;
  padding: 16px var(--page-gutter) 40px;
}

/*
 * 页面采用「左栏二级导航 + 右栏内容」两栏布局。
 * 宽度不设 max-width，避免 1920 视口下两侧大留白；左右留白只由外层
 * `.reference-page__main` 的内边距提供。
 *
 * 左栏宽度走 `--rail-w`（展开 180）/ `--rail-w-collapsed`（折叠 64）：
 * 折叠后内容区多出 116px，槽位卡与库卡片网格同步变宽。
 *
 * `minmax(0, 1fr)` 是关键：右栏内容（卡片网格/长英文标签）默认按
 * min-content 撑宽，会把左栏压扁并产生横向滚动。
 */
.reference-page__inner {
  /* 合成台吸底操作条用：折叠时左偏移同步收窄（26px gap: 24 + 2 边框余量）。 */
  --rail-effective-w: var(--rail-w);
  display: grid;
  grid-template-columns: var(--rail-w) minmax(0, 1fr);
  gap: 24px;
  align-items: start;
  width: 100%;
  min-width: 0;
}

.reference-page__inner.is-rail-collapsed {
  --rail-effective-w: var(--rail-w-collapsed);
  grid-template-columns: var(--rail-w-collapsed) minmax(0, 1fr);
}

/*
 * 左栏导航：竖排、贴顶、可滚动。
 *
 * `top: 0` 相对页面自身滚动容器 `.reference-page`；`max-height` 扣掉全局顶栏
 * 52px 与页面顶部内边距 16px，保证导航在视口内完整可见且内容过长时自己滚动。
 * 六个页签远小于该高度，`overflow-y: auto` 只是兜底。
 */
.reference-tabs {
  position: sticky;
  top: 0;
  align-self: start;
  max-height: calc(100vh - 68px);
  padding-right: 12px;
  border-right: 1px solid var(--border);
  overflow-x: hidden;
  overflow-y: auto;
  scrollbar-width: thin;
  overscroll-behavior: contain;
}

.reference-tabs__list {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 4px;
  width: 100%;
  padding: 2px 0;
}

/* 折叠按钮：36×36 点击区，展开态贴 nav 右缘 */
.reference-tabs__head {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 6px;
}

.reference-tabs__toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: var(--rail-hit);
  height: var(--rail-hit);
  padding: 0;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition:
    background-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.reference-tabs__toggle:hover {
  background: var(--surface-card-hover);
  color: var(--text-strong);
}

.reference-tabs__toggle:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

.reference-tabs__toggle svg {
  width: var(--rail-icon);
  height: var(--rail-icon);
}

/*
 * 导航项：整行可点、左对齐。
 * 非选中态用 `--text-muted`（深/浅两套主题均 ≥7:1），
 * 选中态用主色浅底 + 主色左侧色条 + `--text-strong` 文字，避免「主色字压在
 * 主色浅底上」只有 3.7:1 的低对比问题。
 */
.reference-tab {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  width: 100%;
  height: 36px;
  padding: 0 14px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  font-size: 14px;
  font-weight: 500;
  line-height: 1;
  text-align: left;
  white-space: nowrap;
  transition:
    background-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.reference-tab:hover {
  background: var(--surface-card-hover);
  color: var(--text-strong);
}

.reference-tab.is-active {
  background: var(--primary-soft);
  box-shadow: inset 3px 0 0 var(--primary);
  color: var(--text-strong);
  font-weight: 600;
}

.reference-tab:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

/* 页签图标：16×16、stroke 1.3（折叠态唯一身份标识） */
.reference-tab__icon {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: var(--rail-icon);
  height: var(--rail-icon);
}

.reference-tab__icon svg {
  width: 100%;
  height: 100%;
}

/*
 * 折叠态：nav 只剩图标。
 * 标签文字只用 `display: none` 隐藏，**不删 DOM 节点** —— 读屏、title
 * 提示与既有 `.reference-tab` 文本断言都依赖它仍然存在。
 */
.is-rail-collapsed .reference-tabs {
  padding-right: 0;
}

.is-rail-collapsed .reference-tabs__head {
  justify-content: center;
}

.is-rail-collapsed .reference-tabs__list {
  align-items: center;
}

.is-rail-collapsed .reference-tab {
  justify-content: center;
  width: var(--rail-hit);
  padding: 0;
  margin: 0 auto;
}

.is-rail-collapsed .reference-tab__label {
  display: none;
}

.reference-panel {
  min-width: 0;
  min-height: 0;
}

/*
 * 平板（768–1023px）：强制折叠为图标 rail。
 *
 * 该区间展开态 180px + 24px gap 会把内容区压到不可用宽度；JS 侧
 * `forceCollapsed` 负责 aria 状态，这里用 CSS 兜底首帧并隐藏折叠按钮。
 */
@media (min-width: 768px) and (max-width: 1023px) {
  .reference-page__inner {
    grid-template-columns: var(--rail-w-collapsed) minmax(0, 1fr);
  }

  .reference-tabs {
    padding-right: 0;
  }

  .reference-tabs__head {
    display: none;
  }

  .reference-tabs__list {
    align-items: center;
  }

  .reference-tab {
    justify-content: center;
    width: var(--rail-hit);
    padding: 0;
    margin: 0 auto;
  }

  .reference-tab__label {
    display: none;
  }
}

/*
 * 窄屏（<768px）：两栏回落为单栏，导航复用原来的顶部横向滚动条。
 *
 * 这里显式恢复横向 flex + `overflow-x: auto`：既保持既有 390px 实测
 * 「页签条可横向滚动」的契约，也让超宽的页签条自身消化溢出，而不是撑破页面。
 */
@media (max-width: 767px) {
  .reference-page__main {
    --page-gutter: 24px;
    padding-left: var(--page-gutter);
    padding-right: var(--page-gutter);
  }

  .reference-page__inner {
    display: block;
  }

  .reference-tabs {
    position: static;
    display: flex;
    align-items: center;
    min-height: 56px;
    max-height: none;
    margin-bottom: 16px;
    padding-right: 0;
    border-right: 0;
    border-bottom: 1px solid var(--border);
    overflow-x: auto;
    overflow-y: hidden;
    scrollbar-width: none;
  }

  .reference-tabs::-webkit-scrollbar {
    display: none;
  }

  .reference-tabs__list {
    flex-direction: row;
    align-items: center;
    flex: none;
    gap: 8px;
    width: auto;
    padding: 0;
  }

  /* 药丸尺寸与双态配色对齐 §5「标签」行：32px 高、全圆、6px 14px。 */
  .reference-tab {
    flex: none;
    width: auto;
    height: 32px;
    padding: 6px 14px;
    border-radius: var(--radius-pill);
    background: var(--surface-inset);
  }

  .reference-tab.is-active {
    background: var(--btn-inverse-bg);
    box-shadow: none;
    color: var(--on-inverse);
  }

  /* 窄屏回退药丸条：只显示文字，折叠态 class 在本区间不生效 */
  .reference-tabs__head {
    display: none;
  }

  .reference-tab__icon {
    display: none;
  }

  .reference-page__inner.is-rail-collapsed .reference-tab {
    width: auto;
    padding: 6px 14px;
    margin: 0;
  }

  .reference-page__inner.is-rail-collapsed .reference-tab__label {
    display: inline;
  }
}

/* §5：640–767px 左右 24px。 */
@media (max-width: 639px) {
  .reference-page__main {
    padding-left: 16px;
    padding-right: 16px;
  }
}
</style>