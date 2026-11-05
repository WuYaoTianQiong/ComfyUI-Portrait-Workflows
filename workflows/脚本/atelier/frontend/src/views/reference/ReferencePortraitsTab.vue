<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { PortraitItem } from '../../api/reference'
import { useReferencePortraits } from '../../composables/useReferenceLibrary'
import { useReferenceRecipeDraft } from '../../composables/useReferenceRecipeDraft'
import { useToast } from '../../composables/useToast'

import ReferenceCard from './components/ReferenceCard.vue'
import ReferenceGrid from './components/ReferenceGrid.vue'
import ReferenceLightbox from './components/ReferenceLightbox.vue'
import {
  ALL_STYLES,
  INITIAL_PORTRAIT_COUNT,
  activePortraitStyle,
  filterPortraits,
  formatPortraitSize,
  nextPortraitShown,
  portraitHairCounts,
  portraitLoadMoreState,
  portraitPreviewUrl,
  portraitSectionCounts,
  portraitStyleOptions,
  portraitThumbnailUrl,
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
 * - 搜索 + 重置 + 加载更多（+60，不是分页）；
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
} = useReferenceRecipeDraft()
const toast = useToast()

// ---------------------------------------------------------------------------
// 筛选 / 展示状态
// ---------------------------------------------------------------------------

/** 分区；空串 = 全部（React 的 `section`）。 */
const section = ref('')
/** 发长；空串 = 全部（React 的 `hair`）。 */
const hair = ref('')
/** 发型细分；`ALL_STYLES` = 全部（React 的 `styleName` 默认 `'all'`）。 */
const styleName = ref<string>(ALL_STYLES)
const query = ref('')
/** 已展示张数：首屏 60，每次 +60（§7 冻结）。 */
const shown = ref(INITIAL_PORTRAIT_COUNT)
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

const visibleItems = computed(() => filtered.value.slice(0, shown.value))
const more = computed(() => portraitLoadMoreState(shown.value, filtered.value.length))

interface PortraitCard {
  item: PortraitItem
  src: string | null
  selected: boolean
}

const cards = computed<PortraitCard[]>(() =>
  visibleItems.value.map((item) => ({
    item,
    src: portraitThumbnailUrl(item),
    selected: isPortraitSelected(item.id),
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
  shown.value = INITIAL_PORTRAIT_COUNT
}

/** 分区药丸：再次点击同一项取消（`togglePortraitSection`）。 */
function selectSection(next: string): void {
  section.value = togglePortraitSection(section.value, next)
  styleName.value = ALL_STYLES
  shown.value = INITIAL_PORTRAIT_COUNT
}

/** 发长药丸：再次点击同一项取消（`togglePortraitHair`）。 */
function selectHair(next: string): void {
  hair.value = togglePortraitHair(hair.value, next)
  styleName.value = ALL_STYLES
  shown.value = INITIAL_PORTRAIT_COUNT
}

function onQueryInput(): void {
  shown.value = INITIAL_PORTRAIT_COUNT
}

function onStyleChange(): void {
  shown.value = INITIAL_PORTRAIT_COUNT
}

/** 重置：分区 / 发长 / 发型 / 搜索全部清空（React 的「重置」语义）。 */
function resetFilters(): void {
  section.value = ''
  hair.value = ''
  styleName.value = ALL_STYLES
  query.value = ''
  shown.value = INITIAL_PORTRAIT_COUNT
}

function loadMore(): void {
  shown.value = nextPortraitShown(shown.value, filtered.value.length)
}

/** 卡片「加入配方 / 已选」：多选 toggle，同一 id 再点即移除。 */
function onTogglePortrait(item: PortraitItem): void {
  const added = togglePortrait(item)
  const label = item.发型名称 || item.标题
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
const viewerSelected = computed(() =>
  currentItem.value ? isPortraitSelected(currentItem.value.id) : false,
)
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
      :has-more="more.hasMore"
      :remaining="more.remaining"
      unit="张"
      empty-title="没有找到匹配的人像参考"
      empty-hint="试试更换发型关键词或重置筛选"
      :skeleton-count="10"
      skeleton-aspect="4/5"
      @retry="retry"
      @load-more="loadMore"
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
        @open="openViewer(index)"
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
  color: #fafafa;
  font-size: 20px;
  font-weight: 600;
  line-height: 1.3;
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
  border-radius: 9999px;
  background: #262626;
  color: #a1a1a1;
  font-size: 14px;
  font-weight: 500;
  line-height: 1;
  white-space: nowrap;
  transition:
    background-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.portrait-pill:hover {
  background: #303030;
  color: #fafafa;
}

.portrait-pill.is-active {
  background: #e5e5e5;
  color: #171717;
}

/* 筛选面板：圆角 22 / 内边距 16 / gap 12 / 底 #262626（§5 补充实测项） */
.portrait-filters {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 260px auto;
  align-items: center;
  gap: 12px;
  margin: 12px 0 16px;
  padding: 16px;
  border-radius: 22px;
  background: #262626;
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
  background: #0a0a0a;
  color: #fafafa;
  font-size: 14px;
}

.portrait-search input::placeholder {
  color: #737373;
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
  color: #a1a1a1;
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
  background: #0a0a0a;
  color: #fafafa;
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
  color: #a1a1a1;
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
}

.portrait-reset svg {
  width: 14px;
  height: 14px;
}

.portrait-reset:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #fafafa;
}

/*
 * §5：人像卡片标题最小高 34px（姿势 / 服装为 36px）。
 * 共享 ReferenceCard 默认 36px，这里只在人像页局部收敛，不改共享组件。
 */
.portrait-tab :deep(.ref-card__title) {
  min-height: 34px;
}

/* §5：辅助文字统一 11px / 400 / #a1a1a1（人像 ID 行 10px 由 meta-mono 提供） */
.portrait-tab :deep(.ref-card__meta-right) {
  color: #a1a1a1;
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