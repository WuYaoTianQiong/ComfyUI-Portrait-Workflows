<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import type { PortraitItem } from '../../api/reference'
import { useReferencePortraits } from '../../composables/useReferenceLibrary'
import { useReferenceRecipeDraft } from '../../composables/useReferenceRecipeDraft'
import { useToast } from '../../composables/useToast'
import { readReferenceSearch, readReferenceSelection, withReferenceTab } from './referenceDeepLink'

import ReferenceCard from './components/ReferenceCard.vue'
import ReferenceGrid from './components/ReferenceGrid.vue'
import ReferenceLightbox from './components/ReferenceLightbox.vue'
import {
  ALL_STYLES,
  activePortraitStyle,
  clampPage,
  filterPortraits,
  formatPortraitSize,
  loadReferencePageSize,
  pageCount,
  pageSlice,
  portraitHairCounts,
  portraitPreviewUrl,
  portraitSectionCounts,
  portraitStyleOptions,
  portraitThumbnailUrl,
  saveReferencePageSize,
  stepPortraitIndex,
  togglePortraitHair,
  togglePortraitSection,
} from './components/portraitView'

/**
 * 人像库（阶段 2.3a）。
 *
 * 逐条对齐 §7 人像 4 行（已冻结）：
 * - 分区 / 发长药丸：全部 / 正脸参考 / 造型氛围 / 短发 / 中发 / 中长发 / 长发，
 *   **再次点击同一项取消**；数量按全库统计；
 * - 发型细分下拉：按当前分区 + 发长联动收窄；
 * - 搜索 + 重置 + 分页（Pager + 每页条数，替代旧加载更多）；
 * - 灯箱：CC0 授权说明、原图尺寸、ID 复制、下载（另含新窗口原图）；
 * - 卡片缩略图 4:5 / `object-cover`（§5）。
 *
 * **不做精选 / 热门**：§7 已冻结「不迁移」，React `portraits.tsx` 也没有渲染。
 * 数据来自阶段 1.2 的 `useReferencePortraits`，本文件只做展示状态与筛选。
 */

const { items, loading, error, load, retry } = useReferencePortraits()
const {
  portrait: portraitItems,
  togglePortrait,
  isPortraitSelected,
  extra,
  setPersonBIdentityLibrary,
  clearPersonBIdentity,
  personBPortrait,
  togglePersonBPortrait,
} = useReferenceRecipeDraft()
const toast = useToast()

const route = useRoute()
const router = useRouter()

/** 本次是否在为人物B挑选身份图（第 4 槽，旧五图语义）。 */
const personBIdentityTarget = computed(
  () => readReferenceSelection(route.query) === 'person_b_identity',
)
/** 本次是否在为人物B 全量角色组挑选人像。 */
const personBGroupPortraitTarget = computed(
  () => readReferenceSelection(route.query) === 'person_b_group_portrait',
)
/** 任意人物B人像选择态。 */
const personBPortraitTarget = computed(
  () => personBIdentityTarget.value || personBGroupPortraitTarget.value,
)

function isPersonBGroupPortrait(item: PortraitItem): boolean {
  return personBPortrait.value.some((entry) => entry.id === item.id)
}

function backToStudio(): void {
  void router.replace({
    path: route.path,
    query: withReferenceTab(route.query, 'studio'),
    hash: route.hash,
  })
}

/** 当前条目是否就是人物B身份图（第 4 槽 = 人像库单图）。 */
function isPersonBIdentity(item: PortraitItem): boolean {
  return (
    extra.value.source === 'library' &&
    extra.value.library === 'portrait' &&
    extra.value.id === item.id
  )
}

// ---------------------------------------------------------------------------
// 筛选 / 展示状态
// ---------------------------------------------------------------------------

/** 分区；空串 = 全部（React 的 `section`）。 */
const section = ref('')
/** 发长；空串 = 全部（React 的 `hair`）。 */
const hair = ref('')
/** 发型细分；`ALL_STYLES` = 全部（React 的 `styleName` 默认 `'all'`）。 */
const styleName = ref<string>(ALL_STYLES)
const query = ref(readReferenceSearch(route.query))
/** 当前页码（从 1 开始）；筛选 / 每页条数变化一律回第 1 页。 */
const page = ref(1)
/** 每页条数；三库共用 `pb.reference_page_size_v1`（默认 60）。 */
const pageSize = ref(loadReferencePageSize())
/** 灯箱当前下标；null = 关闭。下标相对**筛选结果**，与 React 一致。 */
const viewerIndex = ref<number | null>(null)

const sectionCounts = computed(() => portraitSectionCounts(items.value))
const hairCounts = computed(() => portraitHairCounts(items.value))
const styleOptions = computed(() => portraitStyleOptions(items.value, section.value, hair.value))

/** 分区 / 发长变化后，原发型选项可能已不在收窄结果里 → 回落「全部」。 */
const effectiveStyle = computed(() => activePortraitStyle(styleName.value, styleOptions.value))

const filtered = computed(() =>
  filterPortraits(items.value, {
    section: section.value,
    hair: hair.value,
    styleName: effectiveStyle.value,
    query: query.value,
  }),
)

const totalCount = computed(() => filtered.value.length)
const totalPages = computed(() => pageCount(totalCount.value, pageSize.value))
/** 当前页在完整筛选结果中的起始下标（灯箱按下标定位时使用）。 */
const pageOffset = computed(() => (page.value - 1) * pageSize.value)
const visibleItems = computed(() => pageSlice(filtered.value, page.value, pageSize.value))

/**
 * 页码越界保护：筛选结果或每页条数变化后总页数可能变少，
 * 把当前页夹到最后一个合法页（每页条数变化本身已回第 1 页）。
 */
watch([totalCount, pageSize], () => {
  page.value = clampPage(page.value, totalCount.value, pageSize.value)
})

interface PortraitCard {
  item: PortraitItem
  src: string | null
  selected: boolean
}

const cards = computed<PortraitCard[]>(() =>
  visibleItems.value.map((item) => ({
    item,
    src: portraitThumbnailUrl(item),
    selected: personBGroupPortraitTarget.value
      ? isPersonBGroupPortrait(item)
      : personBIdentityTarget.value
        ? isPersonBIdentity(item)
        : isPortraitSelected(item.id),
  })),
)

/** 首屏加载且尚无数据：不渲染药丸 / 筛选，避免「全部人像 (0)」闪烁。 */
const initialLoading = computed(() => loading.value && items.value.length === 0)

// ---------------------------------------------------------------------------
// 交互
// ---------------------------------------------------------------------------

/** 「全部人像」：清分区 / 发长 / 发型并回到首屏（不清搜索词，与 React 一致）。 */
function selectAll(): void {
  section.value = ''
  hair.value = ''
  styleName.value = ALL_STYLES
  page.value = 1
}

/** 分区药丸：再次点击同一项取消（`togglePortraitSection`）。 */
function selectSection(next: string): void {
  section.value = togglePortraitSection(section.value, next)
  styleName.value = ALL_STYLES
  page.value = 1
}

/** 发长药丸：再次点击同一项取消（`togglePortraitHair`）。 */
function selectHair(next: string): void {
  hair.value = togglePortraitHair(hair.value, next)
  styleName.value = ALL_STYLES
  page.value = 1
}

function onQueryInput(): void {
  page.value = 1
}

function onStyleChange(): void {
  page.value = 1
}

/** 重置：分区 / 发长 / 发型 / 搜索全部清空（React 的「重置」语义）。 */
function resetFilters(): void {
  section.value = ''
  hair.value = ''
  styleName.value = ALL_STYLES
  query.value = ''
  page.value = 1
}

/** 切换每页条数：写本地记忆并回到第 1 页（三库共用同一个键）。 */
function onPageSizeChange(next: number): void {
  pageSize.value = next
  page.value = 1
  saveReferencePageSize(next)
}

/** 卡片「加入配方 / 已选」：多选 toggle，同一 id 再点即移除。 */
function onTogglePortrait(item: PortraitItem): void {
  const label = item.发型名称 || item.标题
  if (personBGroupPortraitTarget.value) {
    const added = togglePersonBPortrait(item)
    toast.success(
      added
        ? `已加入人物B人像「${label}」（B 人像槽共 ${personBPortrait.value.length} 张）`
        : `已移除人物B人像「${label}」（B 人像槽共 ${personBPortrait.value.length} 张）`,
    )
    return
  }
  if (personBIdentityTarget.value) {
    if (isPersonBIdentity(item)) {
      clearPersonBIdentity()
      toast.info(`已清除当前B变体的身份图「${label}」`)
    } else {
      setPersonBIdentityLibrary(item.id, item.标题)
      toast.success(`已设为当前B变体的身份图「${label}」`)
    }
    return
  }
  const added = togglePortrait(item)
  toast.success(
    added
      ? `已加入${label}（人像槽共 ${portraitItems.value.length} 张）`
      : `已移除${label}（人像槽共 ${portraitItems.value.length} 张）`,
  )
}

// ---------------------------------------------------------------------------
// 灯箱
// ---------------------------------------------------------------------------

const currentItem = computed<PortraitItem | null>(() => {
  const index = viewerIndex.value
  if (index === null) return null
  return filtered.value[index] ?? null
})

/** 下标越界（筛选结果变少）时自动关闭，避免打开一个空弹窗。 */
watch(
  () => filtered.value.length,
  (length) => {
    const index = viewerIndex.value
    if (index === null) return
    if (length === 0) viewerIndex.value = null
    else if (index >= length) viewerIndex.value = length - 1
  },
)

const viewerOpen = computed(() => currentItem.value !== null)
const viewerImageUrl = computed(() =>
  currentItem.value ? portraitPreviewUrl(currentItem.value) : null,
)
const viewerCounter = computed(() => {
  const index = viewerIndex.value
  if (index === null) return ''
  return `${index + 1} / ${filtered.value.length}`
})
const viewerSelected = computed(() => {
  const item = currentItem.value
  if (!item) return false
  if (personBGroupPortraitTarget.value) return isPersonBGroupPortrait(item)
  return personBIdentityTarget.value
    ? isPersonBIdentity(item)
    : isPortraitSelected(item.id)
})
const viewerDownloadName = computed(() =>
  currentItem.value ? `${currentItem.value.id}.webp` : '',
)

/**
 * 原图尺寸实测。
 *
 * 后端 DTO 不下发宽高（适配层回填 0），React 灯箱因此显示 `0 × 0`。
 * 这里用 `Image` 预加载原图、读 `naturalWidth / naturalHeight`，缓存后按
 * 真实尺寸展示；加载中显示「读取中…」、失败显示「—」，绝不显示 0 × 0。
 */
type SizeState = 'idle' | 'loading' | 'ready' | 'error'

const naturalSize = ref<{ width: number; height: number } | null>(null)
const sizeState = ref<SizeState>('idle')
const sizeCache = new Map<string, { width: number; height: number }>()
/** 递增令牌：切换条目后旧请求的回调不得覆盖新状态。 */
let sizeToken = 0

watch(
  viewerImageUrl,
  (url) => {
    const token = ++sizeToken
    naturalSize.value = null
    if (!url) {
      sizeState.value = 'idle'
      return
    }
    const cached = sizeCache.get(url)
    if (cached) {
      naturalSize.value = cached
      sizeState.value = 'ready'
      return
    }
    sizeState.value = 'loading'
    const probe = new Image()
    probe.onload = () => {
      if (token !== sizeToken) return
      const size = { width: probe.naturalWidth, height: probe.naturalHeight }
      if (size.width > 0 && size.height > 0) sizeCache.set(url, size)
      naturalSize.value = size
      sizeState.value = 'ready'
    }
    probe.onerror = () => {
      if (token === sizeToken) sizeState.value = 'error'
    }
    probe.src = url
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  // 卸载后回调直接作废（组件已不存在，避免对已丢弃的 ref 写入）。
  sizeToken += 1
})

const viewerSizeText = computed(() => {
  if (sizeState.value === 'loading') return '读取中…'
  if (sizeState.value === 'ready' && naturalSize.value) {
    return formatPortraitSize(naturalSize.value.width, naturalSize.value.height)
  }
  return '—'
})

const viewerMeta = computed(() => {
  const item = currentItem.value
  if (!item) return []
  return [
    { label: '发型款式', value: item.发型名称 || '—' },
    { label: '原图尺寸', value: viewerSizeText.value },
    { label: '授权协议', value: 'CC0 1.0 公共领域（可商用）' },
  ]
})

function openViewer(index: number): void {
  viewerIndex.value = index
}

function closeViewer(): void {
  viewerIndex.value = null
}

/** ← / → 在筛选结果内循环翻页。 */
function stepViewer(direction: number): void {
  const index = viewerIndex.value
  if (index === null) return
  viewerIndex.value = stepPortraitIndex(index, direction, filtered.value.length)
}

function toggleViewerSelection(): void {
  const item = currentItem.value
  if (item) onTogglePortrait(item)
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="portrait-tab">
    <header class="portrait-head">
      <!--
        `tab-placeholder__title` 是 ReferenceView 骨架期冻结的页签标题契约
        （`ReferenceView.spec.ts` 用它断言 `?tab=` 直达渲染的页面），真实页签沿用。
      -->
      <h1 class="portrait-head__title tab-placeholder__title">人像库</h1>
    </header>

    <!-- 人物B身份图选择态：与 A 槽一样留在库页签里自由筛选，单图替换 -->
    <div
      v-if="personBPortraitTarget"
      class="person-b-select-banner"
      data-testid="portrait-person-b-banner"
    >
      <span class="person-b-select-banner__text">
        <template v-if="personBGroupPortraitTarget">
          正在为人物B选择人像（可多选，选完手动返回合成台）
        </template>
        <template v-else>
          正在为人物B选择身份图（单选，点击卡片即替换；再点已选卡片可清除）
        </template>
      </span>
      <button
        type="button"
        class="person-b-select-banner__back"
        data-testid="portrait-person-b-back"
        @click="backToStudio"
      >
        返回合成台
      </button>
    </div>

    <template v-if="!initialLoading">
      <!-- 分区 / 发长药丸：§5 标签尺寸；再次点击同一项取消 -->
      <div class="portrait-pills" data-testid="portrait-pills" role="group" aria-label="人像分区与发长筛选">
        <button
          type="button"
          class="portrait-pill"
          :class="{ 'is-active': section === '' && hair === '' }"
          :aria-pressed="section === '' && hair === ''"
          data-testid="portrait-pill-all"
          @click="selectAll"
        >
          全部人像 ({{ items.length }})
        </button>
        <button
          v-for="entry in sectionCounts"
          :key="entry.value"
          type="button"
          class="portrait-pill"
          :class="{ 'is-active': section === entry.value }"
          :aria-pressed="section === entry.value"
          :data-section="entry.value"
          @click="selectSection(entry.value)"
        >
          {{ entry.value }} ({{ entry.count }})
        </button>
        <button
          v-for="entry in hairCounts"
          :key="entry.value"
          type="button"
          class="portrait-pill"
          :class="{ 'is-active': hair === entry.value }"
          :aria-pressed="hair === entry.value"
          :data-hair="entry.value"
          @click="selectHair(entry.value)"
        >
          {{ entry.value }} ({{ entry.count }})
        </button>
      </div>

      <!-- 搜索 + 发型细分下拉 + 重置：§5 补充实测项筛选面板 1280 × 68 / 圆角 22 / 内边距 16 -->
      <div class="portrait-filters">
        <label class="portrait-search">
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <circle cx="7" cy="7" r="4.2" fill="none" stroke="currentColor" stroke-width="1.3" />
            <path
              d="m10.2 10.2 3 3"
              fill="none"
              stroke="currentColor"
              stroke-width="1.3"
              stroke-linecap="round"
            />
          </svg>
          <input
            v-model="query"
            type="search"
            data-testid="portrait-search"
            placeholder="搜索发型款式、发色或 ID（如：波波头、狼尾、空气刘海、挑染、韩式）…"
            aria-label="搜索人像"
            @input="onQueryInput"
          />
        </label>

        <select
          v-model="styleName"
          class="portrait-select"
          data-testid="portrait-style"
          aria-label="发型细分"
          @change="onStyleChange"
        >
          <option :value="ALL_STYLES">全部 {{ styleOptions.length }} 款日系发型</option>
          <option v-for="style in styleOptions" :key="style" :value="style">{{ style }}</option>
        </select>

        <button type="button" class="portrait-reset" data-testid="portrait-reset" @click="resetFilters">
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path
              d="M3.2 6.2A5 5 0 1 1 3 9.4"
              fill="none"
              stroke="currentColor"
              stroke-width="1.3"
              stroke-linecap="round"
            />
            <path
              d="M2.6 2.6v3.8h3.8"
              fill="none"
              stroke="currentColor"
              stroke-width="1.3"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
          重置
        </button>
      </div>
    </template>

    <ReferenceGrid
      mode="group"
      :loading="loading"
      :error="error"
      :total="initialLoading ? 0 : filtered.length"
      :page="page"
      :total-pages="totalPages"
      :page-size="pageSize"
      empty-title="没有找到匹配的人像参考"
      empty-hint="试试更换发型关键词或重置筛选"
      :skeleton-count="10"
      skeleton-aspect="4/5"
      @retry="retry"
      @update:page="page = $event"
      @update:page-size="onPageSizeChange"
    >
      <!-- 卡片：缩略图 4:5 / object-cover（§5）；标题两行截断，最小高 34px（人像） -->
      <ReferenceCard
        v-for="(card, index) in cards"
        :key="card.item.id"
        data-testid="portrait-card"
        :src="card.src"
        :title="card.item.发型名称 || card.item.标题"
        :alt="card.item.标题"
        :badge="card.item.分区"
        :angle="card.item.发长"
        aspect="4/5"
        fit="cover"
        meta-mono
        :meta-left="card.item.id"
        meta-right="CC0"
        selectable
        :selected="card.selected"
        @open="openViewer(pageOffset + index)"
        @toggle-select="onTogglePortrait(card.item)"
      />
    </ReferenceGrid>

    <!-- 人像灯箱：CC0 授权 / 原图尺寸 / ID 复制 / 下载（另含新窗口原图） -->
    <ReferenceLightbox
      :open="viewerOpen"
      :title="currentItem?.标题 ?? ''"
      :image-url="viewerImageUrl"
      :alt="currentItem ? `${currentItem.标题} · ${currentItem.发型名称}` : ''"
      :badge="currentItem?.分区"
      :angle="currentItem?.发长"
      :counter="viewerCounter"
      :meta-rows="viewerMeta"
      :selected="viewerSelected"
      :download-name="viewerDownloadName"
      :copy-value="currentItem?.id ?? ''"
      copy-toast="已复制人像 ID"
      :can-prev="filtered.length > 1"
      :can-next="filtered.length > 1"
      @close="closeViewer"
      @prev="stepViewer(-1)"
      @next="stepViewer(1)"
      @toggle-select="toggleViewerSelection"
    />

    <!-- 供自动化断言：当前配方已选人像（多选，逗号分隔） -->
    <span class="portrait-sr-only" data-testid="portrait-selected-id">
      {{ portraitItems.map((item) => item.id).join(',') }}
    </span>
    <span class="portrait-sr-only" data-testid="portrait-selected-count">
      {{ portraitItems.length }}
    </span>
    <span class="portrait-sr-only" data-testid="portrait-recipe-count">
      {{ portraitItems.length ? 1 : 0 }}/3
    </span>
  </div>
</template>

<style scoped>
.portrait-tab {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.portrait-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.portrait-head__title {
  margin: 0;
  color: var(--text-strong);
  font-size: 20px;
  font-weight: 600;
  line-height: 1.3;
}

/* 人物B身份图选择横幅 */
.person-b-select-banner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  padding: 8px 12px;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-sm);
  background: var(--surface-inset);
  color: var(--text-body);
  font-size: 12px;
  line-height: 1.5;
}

.person-b-select-banner__text {
  flex: 1 1 220px;
  min-width: 0;
}

.person-b-select-banner__back {
  flex: none;
  padding: 3px 10px;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-body);
  font-size: 12px;
  cursor: pointer;
}

/* 药丸：§5 标签行 —— 32px 高 / 全圆 / 内边距 6px 14px / 14px 500 / 同组 gap 8px */
.portrait-pills {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 4px;
  scrollbar-width: none;
}

.portrait-pills::-webkit-scrollbar {
  display: none;
}

@media (min-width: 640px) {
  .portrait-pills {
    flex-wrap: wrap;
    padding-bottom: 0;
  }
}

.portrait-pill {
  flex: none;
  box-sizing: border-box;
  height: 32px;
  padding: 6px 14px;
  border: 1px solid transparent;
  border-radius: var(--radius-pill);
  background: var(--surface-panel);
  color: var(--text-muted);
  font-size: 14px;
  font-weight: 500;
  line-height: 1;
  white-space: nowrap;
  transition:
    background-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.portrait-pill:hover {
  background: var(--surface-card-hover);
  color: var(--text-strong);
}

.portrait-pill.is-active {
  background: var(--btn-inverse-bg);
  color: var(--on-inverse);
}

/* 筛选面板：圆角 22 / 内边距 16 / gap 12 / 底 var(--surface-panel)（§5 补充实测项） */
.portrait-filters {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 260px auto;
  align-items: center;
  gap: 12px;
  margin: 12px 0 16px;
  padding: 16px;
  border-radius: 22px;
  background: var(--surface-panel);
}

@media (max-width: 1023px) {
  .portrait-filters {
    grid-template-columns: minmax(0, 1fr) 240px;
  }
}

@media (max-width: 639px) {
  .portrait-filters {
    grid-template-columns: minmax(0, 1fr);
  }
}

.portrait-search {
  position: relative;
  display: block;
  min-width: 0;
}

.portrait-search input {
  box-sizing: border-box;
  width: 100%;
  height: 36px;
  padding: 0 12px 0 36px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-deep);
  color: var(--text-strong);
  font-size: 14px;
}

.portrait-search input::placeholder {
  color: var(--text-faint);
}

.portrait-search input:focus {
  border-color: var(--primary);
  outline: none;
}

.portrait-search svg {
  position: absolute;
  top: 50%;
  left: 12px;
  width: 16px;
  height: 16px;
  color: var(--text-muted);
  transform: translateY(-50%);
  pointer-events: none;
}

.portrait-select {
  box-sizing: border-box;
  width: 100%;
  height: 36px;
  padding: 0 8px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-deep);
  color: var(--text-strong);
  font-size: 14px;
}

.portrait-reset {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 36px;
  padding: 0 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
}

.portrait-reset svg {
  width: 14px;
  height: 14px;
}

.portrait-reset:hover {
  background: var(--fill-subtle);
  color: var(--text-strong);
}

/*
 * §5：人像卡片标题最小高 34px（姿势 / 服装为 36px）。
 * 共享 ReferenceCard 默认 36px，这里只在人像页局部收敛，不改共享组件。
 */
.portrait-tab :deep(.ref-card__title) {
  min-height: 34px;
}

/* §5：辅助文字统一 11px / 400 / var(--text-muted)（人像 ID 行 10px 由 meta-mono 提供） */
.portrait-tab :deep(.ref-card__meta-right) {
  color: var(--text-muted);
  font-weight: 400;
}

/* 仅供自动化读取的状态行 */
.portrait-sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}
</style>