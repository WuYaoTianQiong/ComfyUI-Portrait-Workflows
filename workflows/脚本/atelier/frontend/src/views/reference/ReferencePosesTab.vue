<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { isNsfwPoseItem } from '../../api/reference'
import type { PoseGroup, PoseItem } from '../../api/reference'
import { useReferencePoses } from '../../composables/useReferenceLibrary'
import { useReferenceRecipeDraft } from '../../composables/useReferenceRecipeDraft'
import { useReferenceSafeMode } from '../../composables/useReferenceSafeMode'
import { useToast } from '../../composables/useToast'

import ReferenceAgeGate from './components/ReferenceAgeGate.vue'
import ReferenceCard from './components/ReferenceCard.vue'
import ReferenceGrid from './components/ReferenceGrid.vue'
import ReferenceLightbox from './components/ReferenceLightbox.vue'
import {
  ANGLES,
  activeGroupItem,
  clampPage,
  compositionSummaries as buildCompositionSummaries,
  filterPoseGroups,
  filterPoseSingles,
  groupAngleItem,
  groupIndexOfItem,
  hiddenNsfwGroupCount,
  loadReferencePageSize,
  pageCount,
  pageSlice,
  poseDepthMode,
  posePreviewUrl,
  poseStyleOf,
  poseThumbnailUrl,
  poseTypeOf,
  poseTypeOptions,
  saveReferencePageSize,
  setPoseDepthMode,
  stepGroupItem,
  styleOptions,
} from './components/poseView'
import type { PoseFilters } from './components/poseView'

/**
 * 姿势库（阶段 2.1）。
 *
 * 功能逐条对齐 §7 的 8 行姿势特性 + 全局安全模式：
 * 体系药丸（含 ` · 18+` 文本后缀）、按「体系|姿势编号」分组、组内 5 角度切换、
 * 白模 / 深度图（顶栏与灯箱共享）、搜索 + 动作分类下拉 + 视角胶囊 + 重置、
 * 分组 / 单张视图（5 列 / 6 列）、分页（Pager + 每页条数，替代旧加载更多）、
 * 卡片加入配方、灯箱（缩放拖动、←/→ 组内、↑/↓ 跨组、复制 ID、下载 / 新窗口、加入配方）。
 *
 * 数据来自阶段 1.2 的 `useReferencePoses`（分页并发 ≤6、按 id 去重保序），
 * 本文件只做展示状态与筛选，不重复实现数据层算法。
 */

const {
  items,
  groups,
  loading,
  error,
  load,
  retry,
} = useReferencePoses()

/** 卡片右下角逐行信息：类型 · 风格 · 不可用标记（v1.5 D046 降权）。 */
function poseMetaOf(item: PoseItem | null | undefined): string {
  if (!item) return ''
  return [
    poseTypeOf(item),
    poseStyleOf(item),
    item.usable === false ? '不可用' : '',
  ]
    .filter(Boolean)
    .join(' · ')
}

const {
  safeMode,
  ageGateOpen,
  nsfwAvailable,
  canUnlock,
  loadBackendGate,
  requestUnlock,
  confirmUnlock,
  cancelUnlock,
  toggleSafeMode,
} = useReferenceSafeMode()

const {
  pose: poseItems,
  togglePose,
  isPoseSelected,
} = useReferenceRecipeDraft()

const toast = useToast()

// ---------------------------------------------------------------------------
// 筛选 / 视图状态
// ---------------------------------------------------------------------------

/** 构图筛选；空串 = 全部。 */
const composition = ref('')
/** 来源筛选；空串 = 全部。 */
const source = ref('')
/** 分级筛选；空串 = 全部。安全模式下由 ratingSelect/filters 强制为 general。 */
const rating = ref('')
/** 姿势类型；'all' = 全部。 */
const poseType = ref('all')
/** 风格；'all' = 全部。 */
const style = ref('all')
/** 视角胶囊；空串 = 全部视角 */
const angle = ref('')
/** 搜索词 */
const query = ref('')
const viewMode = ref<'group' | 'single'>('group')
/** 当前页码（从 1 开始）；筛选 / 视图 / 每页条数变化一律回第 1 页。 */
const page = ref(1)
/** 每页条数；三库共用 `pb.reference_page_size_v1`（默认 60）。 */
const pageSize = ref(loadReferencePageSize())
/** 每个分组卡片当前悬停 / 点击的角度（key = group.key） */
const hoverAngles = ref<Record<string, string>>({})

/** 灯箱状态：当前分组下标 + 当前条目 */
const viewer = ref<{ groupIndex: number; item: PoseItem } | null>(null)

const angleOptions = computed(() => [
  { value: '', label: '全部视角' },
  ...ANGLES.map((value) => ({ value, label: value })),
])

// ---------------------------------------------------------------------------
// 安全模式过滤（客户端；与 React 一致）
// ---------------------------------------------------------------------------

const baseItems = computed(() =>
  safeMode.value ? items.value.filter((item) => !isNsfwPoseItem(item)) : items.value,
)
const baseGroups = computed(() =>
  safeMode.value ? groups.value.filter((group) => !isNsfwPoseItem(group)) : groups.value,
)
/** 安全模式固定全年龄；完整模式按用户选择。 */
const effectiveRating = computed(() => (safeMode.value ? 'general' : rating.value))
const ratingSelect = computed({
  get: () => effectiveRating.value,
  set: (value: string) => {
    rating.value = value
    poseType.value = 'all'
    style.value = 'all'
    page.value = 1
  },
})
/** 构图胶囊：count 是姿势组数；来源/分级会改变计数。 */
const compositionSummary = computed(() =>
  buildCompositionSummaries(baseGroups.value, {
    source: source.value,
    rating: effectiveRating.value,
  }),
)
const hiddenTotal = computed(() => hiddenNsfwGroupCount(groups.value))

// ---------------------------------------------------------------------------
// 派生列表
// ---------------------------------------------------------------------------

const filters = computed<PoseFilters>(() => ({
  composition: composition.value,
  source: source.value,
  rating: effectiveRating.value,
  poseType: poseType.value,
  style: style.value,
  angle: angle.value,
  query: query.value,
}))

const poseTypes = computed(() => poseTypeOptions(baseItems.value, filters.value))
const styles = computed(() => styleOptions(baseItems.value, filters.value))
const filteredGroups = computed(() => filterPoseGroups(baseGroups.value, filters.value))
const filteredSingles = computed(() => filterPoseSingles(baseItems.value, filters.value))

const totalCount = computed(() =>
  viewMode.value === 'group' ? filteredGroups.value.length : filteredSingles.value.length,
)
const totalPages = computed(() => pageCount(totalCount.value, pageSize.value))
/** 当前页在完整筛选结果中的起始下标（灯箱按下标定位时使用）。 */
const pageOffset = computed(() => (page.value - 1) * pageSize.value)
const visibleGroups = computed(() =>
  pageSlice(filteredGroups.value, page.value, pageSize.value),
)
const visibleSingles = computed(() =>
  pageSlice(filteredSingles.value, page.value, pageSize.value),
)

/**
 * 页码越界保护：筛选结果或每页条数变化后总页数可能变少，
 * 把当前页夹到最后一个合法页（每页条数变化本身已回第 1 页）。
 */
watch([totalCount, pageSize], () => {
  page.value = clampPage(page.value, totalCount.value, pageSize.value)
})

interface AngleCell {
  angle: string
  item?: PoseItem
  url: string | null
}

interface GroupCard {
  group: PoseGroup
  index: number
  item?: PoseItem
  angles: AngleCell[]
}

/** 分组卡片：把当前角度与 5 格缩略条提前算好，避免模板里重复调函数。 */
const groupCards = computed<GroupCard[]>(() =>
  visibleGroups.value.map((group, index) => {
    // 单角度分组（如 pose-studio-lite）只渲染实际角度，避免 4 个空占位；
    // 2–5 个角度仍保持原有 5 格布局，不影响上游既有观感。
    const angleNames =
      group.order.length === 1 && group.order[0].角度
        ? [group.order[0].角度]
        : ANGLES
    return {
      group,
      // 灯箱按 `filteredGroups` 的下标定位，分页后需要补上当前页的起始偏移
      index: pageOffset.value + index,
      item: activeGroupItem(group, hoverAngles.value, angle.value),
      angles: angleNames.map((value) => {
        const angleItem = groupAngleItem(group, value)
        return {
          angle: value,
          item: angleItem,
          url: angleItem ? poseThumbnailUrl(angleItem, poseDepthMode.value) : null,
        }
      }),
    }
  }),
)

interface SingleCard {
  item: PoseItem
  src: string | null
  selected: boolean
}

const singleCards = computed<SingleCard[]>(() =>
  visibleSingles.value.map((item) => ({
    item,
    src: poseThumbnailUrl(item, poseDepthMode.value),
    selected: isPoseSelected(item.id),
  })),
)

// ---------------------------------------------------------------------------
// 交互
// ---------------------------------------------------------------------------

function selectComposition(next: string): void {
  composition.value = next
  poseType.value = 'all'
  style.value = 'all'
  page.value = 1
}

function selectSource(event: Event): void {
  source.value = (event.target as HTMLSelectElement).value
  poseType.value = 'all'
  style.value = 'all'
  page.value = 1
}

function selectPoseType(event: Event): void {
  poseType.value = (event.target as HTMLSelectElement).value
  style.value = 'all'
  page.value = 1
}

function selectStyle(event: Event): void {
  style.value = (event.target as HTMLSelectElement).value
  page.value = 1
}

function selectAngle(next: string): void {
  angle.value = next
  page.value = 1
}

function onQueryInput(): void {
  page.value = 1
}

function resetFilters(): void {
  composition.value = ''
  source.value = ''
  rating.value = ''
  poseType.value = 'all'
  style.value = 'all'
  angle.value = ''
  query.value = ''
  page.value = 1
}

function setViewMode(mode: 'group' | 'single'): void {
  if (viewMode.value === mode) return
  viewMode.value = mode
  page.value = 1
}

/** 切换每页条数：写本地记忆并回到第 1 页（三库共用同一个键）。 */
function onPageSizeChange(next: number): void {
  pageSize.value = next
  page.value = 1
  saveReferencePageSize(next)
}

function setHoverAngle(group: PoseGroup, next: string): void {
  hoverAngles.value = { ...hoverAngles.value, [group.key]: next }
}

/** 卡片「加入配方 / 已选」：多选 toggle，模式参与移除判定（同 id 同模式才算移除）。 */
function onTogglePose(item: PoseItem): void {
  const added = togglePose(item, poseDepthMode.value)
  const mode = poseDepthMode.value ? ' · 深度图' : ''
  if (added) {
    toast.success(
      `已加入姿势：${item.姿势名称}（${item.角度}${mode}，姿势槽共 ${poseItems.value.length} 张）`,
    )
  } else {
    toast.success(`已移除姿势：${item.姿势名称}（姿势槽共 ${poseItems.value.length} 张）`)
  }
}

// ---------------------------------------------------------------------------
// 安全模式
// ---------------------------------------------------------------------------

function backendBlockedToast(): void {
  toast.error('后端未开启 18+ 总闸（ATELIER_REFERENCE_ALLOW_NSFW），无法解锁')
}

function onToggleSafeMode(): void {
  if (!safeMode.value) {
    // 完整模式 → 安全模式：只切显示，确认标记保留
    toggleSafeMode()
    rating.value = 'general'
    poseType.value = 'all'
    style.value = 'all'
    page.value = 1
    toast.success('已开启安全模式（已隐藏 18+ 敏感分类）')
    return
  }
  const accepted = requestUnlock(() => {
    rating.value = ''
    poseType.value = 'all'
    style.value = 'all'
    page.value = 1
    toast.success('已解锁 18+ 完整图库模式')
  })
  if (!accepted) backendBlockedToast()
}

function onUnlockPill(): void {
  const accepted = requestUnlock(() => {
    rating.value = ''
    poseType.value = 'all'
    style.value = 'all'
    page.value = 1
    toast.success('已解锁 18+ 内容')
  })
  if (!accepted) backendBlockedToast()
}

function onConfirmAgeGate(): void {
  confirmUnlock()
  rating.value = ''
  poseType.value = 'all'
  style.value = 'all'
  page.value = 1
  toast.success('已解锁 18+ 完整图库模式')
}

function onCancelAgeGate(): void {
  cancelUnlock()
}

// ---------------------------------------------------------------------------
// 灯箱
// ---------------------------------------------------------------------------

const viewerGroup = computed<PoseGroup | undefined>(() => {
  const current = viewer.value
  if (!current) return undefined
  return filteredGroups.value[current.groupIndex]
})

const viewerItem = computed(() => viewer.value?.item ?? null)
const viewerGroupIndex = computed(() => viewer.value?.groupIndex ?? 0)

const viewerImageUrl = computed(() =>
  viewerItem.value ? posePreviewUrl(viewerItem.value, poseDepthMode.value) : null,
)

const viewerThumbs = computed(() => {
  const group = filteredGroups.value[viewerGroupIndex.value]
  if (!group) return []
  const thumbs: Array<{ key: string; label: string; url: string | null }> = []
  for (const value of ANGLES) {
    const angleItem = groupAngleItem(group, value)
    if (!angleItem) continue
    thumbs.push({
      key: value,
      label: value,
      url: poseThumbnailUrl(angleItem, poseDepthMode.value),
    })
  }
  return thumbs
})

const viewerMeta = computed(() => {
  const item = viewerItem.value
  if (!item) return []
  return [
    { label: '所属体系', value: item.体系 || '—' },
    { label: '动作分类', value: item.分类 || '—' },
    {
      label: '当前模式',
      value: poseDepthMode.value ? '深度图 (Depth Map)' : '3D 素体白模',
    },
    { label: '原图尺寸', value: `900 × 1200 ${poseDepthMode.value ? 'WebP' : 'PNG'}` },
  ]
})

const viewerCounter = computed(() => {
  if (!viewer.value) return ''
  return `${viewer.value.groupIndex + 1} / ${filteredGroups.value.length}`
})

const viewerSelected = computed(() =>
  viewerItem.value ? isPoseSelected(viewerItem.value.id, poseDepthMode.value) : false,
)

const lightboxSelectLabel = computed(
  () => `加入角色配方（${poseDepthMode.value ? '深度图' : '白模'}）`,
)

const viewerDownloadName = computed(() => {
  const item = viewerItem.value
  if (!item) return ''
  return `${item.id}${poseDepthMode.value ? '_depth.webp' : '.png'}`
})

function openGroup(group: PoseGroup, index: number): void {
  const item = activeGroupItem(group, hoverAngles.value, angle.value)
  if (item) viewer.value = { groupIndex: index, item }
}

function openSingle(item: PoseItem): void {
  viewer.value = {
    groupIndex: groupIndexOfItem(filteredGroups.value, item.id),
    item,
  }
}

/** 组内角度翻页（← / →），循环。 */
function stepViewerAngle(direction: number): void {
  const group = filteredGroups.value[viewerGroupIndex.value]
  const item = viewerItem.value
  if (!group || !item) return
  const next = stepGroupItem(group, item.id, direction)
  if (next) viewer.value = { groupIndex: viewerGroupIndex.value, item: next }
}

/** 跨组翻页（↑ / ↓）：优先保持同一角度。 */
function stepViewerGroup(direction: number): void {
  const current = viewer.value
  if (!current) return
  const nextIndex = current.groupIndex + direction
  if (nextIndex < 0 || nextIndex >= filteredGroups.value.length) return
  const nextGroup = filteredGroups.value[nextIndex]
  const nextItem = nextGroup.angles[current.item.角度] || nextGroup.order[0]
  if (nextItem) viewer.value = { groupIndex: nextIndex, item: nextItem }
}

/** 灯箱内点 5 角度缩略图。 */
function selectViewerAngle(key: string): void {
  const group = filteredGroups.value[viewerGroupIndex.value]
  const next = group ? groupAngleItem(group, key) : undefined
  if (next) viewer.value = { groupIndex: viewerGroupIndex.value, item: next }
}

function toggleViewerSelection(): void {
  const item = viewerItem.value
  if (item) onTogglePose(item)
}

/** 首屏加载且尚无数据：不渲染药丸 / 筛选，避免「全部 (0)」闪烁。 */
const initialLoading = computed(() => loading.value && items.value.length === 0)

onMounted(() => {
  // 总闸探测与数据加载并行，互不阻塞
  void loadBackendGate()
  void load()
})
</script>

<template>
  <div class="pose-tab">
    <header class="pose-head">
      <!--
        `tab-placeholder__title` 是 ReferenceView 骨架期就冻结的「页签面板标题」
        契约（ReferenceView.spec.ts 用它断言 `?tab=` 直达渲染的页面），
        真实页签沿用同一 class，避免骨架测试随实现替换而失效。
      -->
      <h1 class="pose-head__title tab-placeholder__title">姿势库</h1>
      <div class="pose-head__actions">
        <!-- 素体白模 / 深度图：与灯箱共享 poseDepthMode -->
        <div class="pose-segment" data-testid="pose-depth-toggle" role="group" aria-label="白模与深度图切换">
          <button
            type="button"
            data-depth="white"
            :class="{ 'is-active': !poseDepthMode }"
            :aria-pressed="!poseDepthMode"
            @click="setPoseDepthMode(false)"
          >
            素体白模
          </button>
          <button
            type="button"
            data-depth="depth"
            :class="{ 'is-active': poseDepthMode }"
            :aria-pressed="poseDepthMode"
            @click="setPoseDepthMode(true)"
          >
            深度图 (Depth)
          </button>
        </div>

        <div class="pose-view-mode" role="group" aria-label="视图模式">
          <button
            type="button"
            data-testid="pose-view-group"
            :class="{ 'is-active': viewMode === 'group' }"
            :aria-pressed="viewMode === 'group'"
            @click="setViewMode('group')"
          >
            分组
          </button>
          <button
            type="button"
            data-testid="pose-view-single"
            :class="{ 'is-active': viewMode === 'single' }"
            :aria-pressed="viewMode === 'single'"
            @click="setViewMode('single')"
          >
            单张
          </button>
        </div>

        <!-- 安全模式：SFW 态 / 18+ 态配色按 §5；后端总闸关闭时置灰 -->
        <button
          type="button"
          class="pose-safe"
          :class="safeMode ? 'is-safe' : 'is-full'"
          data-testid="pose-safe-toggle"
          :data-safe="safeMode ? '1' : '0'"
          :data-gate="nsfwAvailable ? 'open' : 'closed'"
          :disabled="safeMode && !nsfwAvailable"
          :aria-pressed="!safeMode"
          :title="
            safeMode
              ? nsfwAvailable
                ? '当前已开启安全模式（已隐藏 18+ 敏感内容），点击可解锁完整图库'
                : '后端总闸已关闭（ATELIER_REFERENCE_ALLOW_NSFW=0），无法解锁 18+'
              : '当前已显示 18+ 完整图库，点击可切回安全模式'
          "
          @click="onToggleSafeMode"
        >
          <svg class="pose-safe__icon" viewBox="0 0 16 16" aria-hidden="true">
            <path
              d="M8 1.8 13 4v4.1c0 3-2.1 5.1-5 6.1-2.9-1-5-3.1-5-6.1V4l5-2.2Z"
              fill="none"
              stroke="currentColor"
              stroke-width="1.3"
              stroke-linejoin="round"
            />
            <path
              d="M5.8 7.8 7.4 9.4l3-3.2"
              fill="none"
              stroke="currentColor"
              stroke-width="1.3"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
          {{ safeMode ? '安全模式 (SFW)' : '18+ 完整模式' }}
        </button>
      </div>
    </header>

    <template v-if="!initialLoading">
      <!-- 构图横向药丸；计数单位是姿势组数，不是图片数 -->
      <div class="pose-pills" data-testid="pose-composition-pills" role="group" aria-label="姿势构图筛选">
        <button
          v-for="summary in compositionSummary"
          :key="summary.key || 'all'"
          type="button"
          class="pose-pill"
          :class="{ 'is-active': composition === summary.key }"
          :aria-pressed="composition === summary.key"
          :data-composition="summary.key"
          :title="`${summary.count} 组 / ${summary.images} 张`"
          @click="selectComposition(summary.key)"
        >
          {{ summary.label }} ({{ summary.count }})
        </button>

        <button
          v-if="safeMode && hiddenTotal > 0"
          type="button"
          class="pose-pill is-unlock"
          data-testid="pose-unlock-nsfw"
          :disabled="!nsfwAvailable"
          :title="nsfwAvailable ? '解锁后显示 18+ 内容' : '后端总闸已关闭，无法解锁'"
          @click="onUnlockPill"
        >
          解锁 18+ 内容 ({{ hiddenTotal }})
        </button>
      </div>

      <!-- 第一行：搜索 + 来源/分级/类型/风格；第二行：视角 + 重置 -->
      <div class="pose-filters">
        <div class="pose-filter-row">
        <label class="pose-search">
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <circle cx="7" cy="7" r="4.2" fill="none" stroke="currentColor" stroke-width="1.3" />
            <path d="m10.2 10.2 3 3" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" />
          </svg>
          <input
            v-model="query"
            type="search"
            data-testid="pose-search"
            placeholder="搜索姿势名称、编号 (如 P001)、分类或 ID…"
            aria-label="搜索姿势"
            @input="onQueryInput"
          />
        </label>

        <div class="pose-selects">
        <select
          v-model="source"
          class="pose-select"
          data-testid="pose-source"
          aria-label="来源"
          @change="selectSource"
        >
          <option value="">全部来源</option>
          <option value="upstream">原图库</option>
          <option value="pose-studio-lite">pose-studio-lite</option>
        </select>

        <select
          v-model="ratingSelect"
          class="pose-select"
          data-testid="pose-rating"
          aria-label="分级"
          :disabled="safeMode"
          :title="safeMode ? '安全模式下固定全年龄' : '选择全年龄 / 18+'"
        >
          <option value="">全部分级</option>
          <option value="general">全年龄</option>
          <option value="nsfw" :disabled="safeMode">18+</option>
        </select>

        <select
          v-model="poseType"
          class="pose-select"
          data-testid="pose-category"
          aria-label="姿势类型"
          @change="selectPoseType"
        >
          <option value="all">全部姿势类型</option>
          <option v-for="item in poseTypes" :key="item" :value="item">{{ item }}</option>
        </select>

        <select
          v-model="style"
          class="pose-select"
          data-testid="pose-style"
          aria-label="风格"
          @change="selectStyle"
        >
          <option value="all">全部风格</option>
          <option v-for="item in styles" :key="item" :value="item">{{ item }}</option>
        </select>
        </div>
        </div>

        <div class="pose-filter-row pose-filter-row--secondary">
        <div class="pose-angles" data-testid="pose-angles" role="group" aria-label="视角筛选">
          <button
            v-for="option in angleOptions"
            :key="option.value || 'all'"
            type="button"
            :class="{ 'is-active': angle === option.value }"
            :aria-pressed="angle === option.value"
            :data-angle="option.value"
            @click="selectAngle(option.value)"
          >
            {{ option.label }}
          </button>
        </div>

        <button type="button" class="pose-reset" data-testid="pose-reset" @click="resetFilters">
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path
              d="M3.2 6.2A5 5 0 1 1 3 9.4"
              fill="none"
              stroke="currentColor"
              stroke-width="1.3"
              stroke-linecap="round"
            />
            <path d="M2.6 2.6v3.8h3.8" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          重置
        </button>
        </div>
      </div>
    </template>

    <ReferenceGrid
      :mode="viewMode"
      :loading="loading"
      :error="error"
      :total="initialLoading ? 0 : totalCount"
      :page="page"
      :total-pages="totalPages"
      :page-size="pageSize"
      empty-title="没有找到匹配的姿势"
      empty-hint="试试更换搜索词或重置筛选条件"
      :skeleton-count="viewMode === 'single' ? 12 : 10"
      @retry="retry"
      @update:page="page = $event"
      @update:page-size="onPageSizeChange"
    >
      <!-- 分组视图：5 列，按当前页切片 -->
      <template v-if="viewMode === 'group'">
        <ReferenceCard
          v-for="card in groupCards"
          v-show="card.item"
          :key="card.group.key"
          data-testid="pose-card"
          :src="card.item ? poseThumbnailUrl(card.item, poseDepthMode) : null"
          :title="card.group.name"
          :alt="card.item ? `${card.group.name} · ${card.item.角度}` : card.group.name"
          :badge="card.group.number"
          :angle="card.item?.角度"
          :meta-left="card.group.system"
          :meta-right="poseMetaOf(card.item)"
          :selectable="Boolean(card.item)"
          :selected="card.item ? isPoseSelected(card.item.id) : false"
          @open="openGroup(card.group, card.index)"
          @toggle-select="card.item && onTogglePose(card.item)"
        >
          <div class="angle-strip">
            <template v-for="cell in card.angles" :key="cell.angle">
              <button
                v-if="cell.item"
                type="button"
                class="angle-cell"
                :class="{ 'is-active': card.item && cell.item.id === card.item.id }"
                :title="`预览${cell.angle}`"
                :aria-label="`切换到${cell.angle}`"
                :data-angle="cell.angle"
                @mouseenter="setHoverAngle(card.group, cell.angle)"
                @focus="setHoverAngle(card.group, cell.angle)"
                @click="setHoverAngle(card.group, cell.angle)"
              >
                <img v-if="cell.url" :src="cell.url" :alt="cell.angle" loading="lazy" />
                <span v-else class="angle-cell__empty" />
                <span class="angle-cell__label">{{ cell.angle }}</span>
              </button>
              <span v-else class="angle-cell is-empty" aria-hidden="true" />
            </template>
          </div>
        </ReferenceCard>
      </template>

      <!-- 单张视图：6 列，按当前页切片 -->
      <template v-else>
        <ReferenceCard
          v-for="card in singleCards"
          :key="card.item.id"
          data-testid="pose-card-single"
          :src="card.src"
          :title="card.item.姿势名称"
          :alt="card.item.姿势名称"
          :badge="card.item.姿势编号"
          :angle="card.item.角度"
          meta-mono
          :meta-left="card.item.id"
          :meta-right="poseMetaOf(card.item)"
          selectable
          :selected="card.selected"
          @open="openSingle(card.item)"
          @toggle-select="onTogglePose(card.item)"
        />
      </template>
    </ReferenceGrid>

    <ReferenceLightbox
      :open="Boolean(viewer)"
      :title="viewerItem?.姿势名称 ?? ''"
      :image-url="viewerImageUrl"
      :alt="viewerItem ? `${viewerItem.姿势名称} · ${viewerItem.角度}` : ''"
      :badge="viewerItem?.姿势编号"
      :angle="viewerItem?.角度"
      :counter="viewerCounter"
      :meta-rows="viewerMeta"
      :thumbnails="viewerThumbs"
      :active-thumb-key="viewerItem?.角度 ?? null"
      :depth-mode="poseDepthMode"
      :selected="viewerSelected"
      :select-label="lightboxSelectLabel"
      selected-label="已在角色配方中（点击移除）"
      :download-name="viewerDownloadName"
      :copy-value="viewerItem?.id ?? ''"
      copy-toast="已复制姿势 ID"
      :can-prev="Boolean(viewerGroup && viewerGroup.order.length > 1)"
      :can-next="Boolean(viewerGroup && viewerGroup.order.length > 1)"
      :can-prev-group="viewerGroupIndex > 0"
      :can-next-group="viewerGroupIndex < filteredGroups.length - 1"
      @close="viewer = null"
      @prev="stepViewerAngle(-1)"
      @next="stepViewerAngle(1)"
      @prev-group="stepViewerGroup(-1)"
      @next-group="stepViewerGroup(1)"
      @select-thumb="selectViewerAngle"
      @update:depth-mode="setPoseDepthMode"
      @toggle-select="toggleViewerSelection"
    />

    <ReferenceAgeGate
      :open="ageGateOpen"
      @confirm="onConfirmAgeGate"
      @cancel="onCancelAgeGate"
    />

    <!-- 供自动化断言：当前配方已选姿势（多选，逗号分隔，深度图带 |depth） -->
    <span class="pose-sr-only" data-testid="pose-selected-id">
      {{ poseItems.map((entry) => `${entry.item.id}${entry.useDepth ? '|depth' : ''}`).join(',') }}
    </span>
    <span class="pose-sr-only" data-testid="pose-selected-count">{{ poseItems.length }}</span>
    <span class="pose-sr-only" data-testid="pose-recipe-count">{{ poseItems.length ? 1 : 0 }}/3</span>
    <span class="pose-sr-only" data-testid="pose-can-unlock">{{ canUnlock ? '1' : '0' }}</span>
  </div>
</template>

<style scoped>
.pose-tab {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.pose-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.pose-head__title {
  margin: 0;
  color: var(--text-strong);
  font-size: 20px;
  font-weight: 600;
  line-height: 1.3;
}

.pose-head__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

/* 顶栏分段按钮（白模 / 深度图） */
.pose-segment {
  display: inline-flex;
  align-items: center;
  padding: 2px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-inset);
}

.pose-segment button {
  padding: 4px 10px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 500;
  line-height: 16px;
  white-space: nowrap;
}

.pose-segment button:hover {
  color: var(--text-strong);
}

.pose-segment button.is-active {
  background: var(--surface-deep);
  color: var(--text-strong);
  box-shadow: var(--shadow-1);
}

/* 分组 / 单张 */
.pose-view-mode {
  display: inline-flex;
  gap: 6px;
}

.pose-view-mode button {
  min-height: 32px;
  padding: 0 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: transparent;
  color: var(--text-strong);
  font-size: 12px;
  font-weight: 500;
}

.pose-view-mode button:hover {
  background: var(--fill-subtle);
}

.pose-view-mode button.is-active {
  border-color: transparent;
  background: var(--btn-inverse-bg);
  color: var(--on-inverse);
}

/* 安全模式按钮：§5 SFW 态 / 18+ 态 */
.pose-safe {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  box-sizing: border-box;
  height: 32px;
  padding: 0 10px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
  line-height: 1;
  white-space: nowrap;
}

.pose-safe.is-safe {
  border: 1px solid var(--accent-green-border);
  background: var(--fill-faint);
  color: var(--accent-green-text);
}

.pose-safe.is-full {
  border: 1px solid var(--accent-red-border);
  background: var(--accent-red-soft);
  color: var(--accent-red-text);
}

.pose-safe:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.pose-safe__icon {
  width: 14px;
  height: 14px;
  flex: none;
}

/* 体系药丸：32px / 全圆 / 内边距 6px 14px / 14px 500 / gap 8px */
.pose-pills {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 4px;
  scrollbar-width: none;
}

.pose-pills::-webkit-scrollbar {
  display: none;
}

@media (min-width: 640px) {
  .pose-pills {
    flex-wrap: wrap;
    padding-bottom: 0;
  }
}

.pose-pill {
  flex: none;
  box-sizing: border-box;
  height: 32px;
  padding: 6px 14px;
  border: 1px solid transparent;
  border-radius: 9999px;
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

.pose-pill:hover {
  background: var(--surface-card-hover);
  color: var(--text-strong);
}

.pose-pill.is-active {
  background: var(--btn-inverse-bg);
  color: var(--on-inverse);
}

.pose-pill.is-unlock {
  border: 1px dashed var(--accent-red-border-strong);
  background: var(--accent-red-soft-faint);
  color: var(--accent-red-text);
}

.pose-pill:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* 筛选面板：第一行搜索 + 四个下拉；第二行视角 + 重置 */
.pose-filters {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 12px 0 16px;
  padding: 16px;
  border-radius: 22px;
  background: var(--surface-panel);
}

.pose-filter-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  min-width: 0;
}

.pose-filter-row--secondary {
  gap: 8px;
}

.pose-selects {
  display: flex;
  align-items: center;
  flex: 0 0 auto;
  flex-wrap: wrap;
  gap: 8px;
}

.pose-search {
  position: relative;
  display: block;
  flex: 1 1 280px;
  min-width: 0;
}

.pose-search input {
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

.pose-search input::placeholder {
  color: var(--text-faint);
}

.pose-search input:focus {
  border-color: var(--primary);
  outline: none;
}

.pose-search svg {
  position: absolute;
  top: 50%;
  left: 12px;
  width: 16px;
  height: 16px;
  color: var(--text-muted);
  transform: translateY(-50%);
  pointer-events: none;
}

.pose-select {
  box-sizing: border-box;
  flex: 0 0 140px;
  width: 140px;
  height: 36px;
  padding: 0 8px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-deep);
  color: var(--text-strong);
  font-size: 14px;
}

@media (max-width: 639px) {
  .pose-filter-row {
    align-items: stretch;
  }

  .pose-search {
    flex-basis: 100%;
  }

  .pose-selects {
    width: 100%;
  }

  .pose-select {
    flex: 1 1 calc(50% - 4px);
    width: auto;
  }
}

.pose-angles {
  display: flex;
  align-items: center;
  flex: 1 1 auto;
  gap: 4px;
  min-width: 0;
  padding: 4px;
  overflow-x: auto;
  border-radius: 8px;
  background: var(--surface-deep);
  scrollbar-width: none;
}

.pose-angles::-webkit-scrollbar {
  display: none;
}

.pose-angles button {
  flex: none;
  padding: 4px 10px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 500;
  line-height: 16px;
  white-space: nowrap;
}

.pose-angles button:hover {
  color: var(--text-strong);
}

.pose-angles button.is-active {
  background: var(--btn-inverse-bg);
  color: var(--on-inverse);
}

.pose-reset {
  display: inline-flex;
  align-items: center;
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

.pose-reset svg {
  width: 14px;
  height: 14px;
}

.pose-reset:hover {
  background: var(--fill-subtle);
  color: var(--text-strong);
}

/* 5 格角度缩略条：列宽 42.23 / 单格 42.23 × 57.73 / gap 4 / 圆角 10 / 内边距 2 / 边框 1 */
.angle-strip {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 4px;
}

.angle-cell {
  box-sizing: border-box;
  height: 57.73px;
  padding: 2px;
  overflow: hidden;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: var(--text-muted);
}

.angle-cell.is-active {
  border-color: var(--border-active);
  background: var(--surface-deep);
}

.angle-cell:hover {
  border-color: var(--border-hover);
}

.angle-cell img {
  display: block;
  width: 100%;
  aspect-ratio: 1 / 1;
  border-radius: 8px;
  object-fit: cover;
}

.angle-cell__empty {
  display: block;
  width: 100%;
  aspect-ratio: 1 / 1;
  border-radius: 8px;
  background: var(--surface-raised);
}

.angle-cell__label {
  display: block;
  margin-top: 2px;
  font-size: 9px;
  line-height: 13.5px;
  text-align: center;
}

.angle-cell.is-empty {
  pointer-events: none;
}

/* 仅供自动化读取的状态行 */
.pose-sr-only {
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