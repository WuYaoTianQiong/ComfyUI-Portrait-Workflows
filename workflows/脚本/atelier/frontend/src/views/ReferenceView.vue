<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { withReferenceTab } from './reference/referenceDeepLink'

import ReferenceCostumesTab from './reference/ReferenceCostumesTab.vue'
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
const TAB_KEYS = ['home', 'pose', 'costume', 'portrait', 'studio', 'settings'] as const

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
  { key: 'studio', label: '合成台' },
  { key: 'settings', label: '设置' },
]

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

/** 实际生效页签。 */
const activeTab = computed<ReferenceTabKey>(() => queryTab.value ?? DEFAULT_TAB)


const TAB_COMPONENTS = {
  home: ReferenceHomeTab,
  pose: ReferencePosesTab,
  costume: ReferenceCostumesTab,
  portrait: ReferencePortraitsTab,
  studio: ReferenceStudioTab,
  settings: ReferenceSettingsTab,
} as const

const activeComponent = computed(() => TAB_COMPONENTS[activeTab.value])

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
</script>

<template>
  <div class="reference-page">
    <div class="reference-page__main">
      <div class="reference-page__inner">
        <!-- 二级导航：只在内容区顶部，全局导航由外层 App.vue 提供。 -->
        <nav class="reference-tabs" aria-label="参考图库页签">
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
              @click="selectTab(tab.key)"
            >
              {{ tab.label }}
            </button>
          </div>
        </nav>

        <section
          id="reference-tab-panel"
          class="reference-panel"
          role="tabpanel"
          :aria-labelledby="`reference-tab-${activeTab}`"
        >
          <component :is="activeComponent" />
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
  padding: 16px 32px 40px;
}

/*
 * 与主站 `.content` 同宽：不设 max-width，避免 1920 视口下两侧大留白。
 * 左右留白只由外层 `.reference-page__main` 的内边距提供。
 */
.reference-page__inner {
  width: 100%;
  min-width: 0;
}

/*
 * 页签条：高度参照 §5 补充实测项的内层工具条 56px；
 * 仅内容区顶部的一条二级导航，不复制全局导航。
 */
.reference-tabs {
  display: flex;
  align-items: center;
  min-height: 56px;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--border);
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: none;
}

.reference-tabs::-webkit-scrollbar {
  display: none;
}

.reference-tabs__list {
  display: flex;
  align-items: center;
  flex: none;
  gap: 8px;
}

/* 药丸尺寸与双态配色对齐 §5「标签」行：32px 高、全圆、6px 14px、14px / 500。 */
.reference-tab {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  height: 32px;
  padding: 6px 14px;
  border: 1px solid transparent;
  border-radius: 9999px;
  background: var(--surface-inset);
  color: var(--text-muted);
  font-size: 14px;
  font-weight: 500;
  line-height: 1;
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
  background: var(--btn-inverse-bg);
  color: var(--on-inverse);
}

.reference-tab:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

.reference-panel {
  min-height: 0;
}

/* §5：640–767px 左右 24px。 */
@media (max-width: 767px) {
  .reference-page__main {
    padding-left: 24px;
    padding-right: 24px;
  }
}

/* §5：<640px 左右 16px。 */
@media (max-width: 639px) {
  .reference-page__main {
    padding-left: 16px;
    padding-right: 16px;
  }
}
</style>