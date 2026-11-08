<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import type { CostumeItem } from '../../api/reference'
import { useReferenceCostumes } from '../../composables/useReferenceLibrary'
import { useReferenceRecipeDraft } from '../../composables/useReferenceRecipeDraft'
import { useReferenceSafeMode } from '../../composables/useReferenceSafeMode'
import { useToast } from '../../composables/useToast'
import { readReferenceSelection, withReferenceTab } from './referenceDeepLink'

import ReferenceAgeGate from './components/ReferenceAgeGate.vue'
import ReferenceCard from './components/ReferenceCard.vue'
import ReferenceGrid from './components/ReferenceGrid.vue'
import ReferenceLightbox from './components/ReferenceLightbox.vue'
import {
  COSTUME_ALL_TAGS,
  COSTUME_KINDS,
  COSTUME_SEARCH_PLACEHOLDER,
  clampPage,
  costumeAuthorSiteUrl,
  costumeBaseItems,
  costumeCategorySummaries,
  costumeCounter,
  costumeDownloadName,
  costumeHiddenNsfwCount,
  costumeLightboxMeta,
  costumePreviewUrl,
  costumeSourceLabel,
  costumeTagOptions,
  costumeTagPreview,
  costumeThumbnailUrl,
  filterCostumes,
  isRemoteCostume,
  loadReferencePageSize,
  pageCount,
  pageSlice,
  resolveActiveCategory,
  resolveActiveTag,
  saveReferencePageSize,
  stepCostumeIndex,
} from './components/costumeView'
import type { CostumeKind } from './components/costumeView'

/**
 * 服装库（阶段 2.2）。
 *
 * 功能逐条对齐 §7 的 6 行服装特性 + 全局 18+ 安全模式：
 * - `costume`（现实）与 `costume-anime`（二次元）**并行**拉取，合并顺序现实在前
 *   （由 `useReferenceCostumes` 保证，本文件不重复实现数据层）；
 * - 一级分类按钮组（全部 / 现实 / 二次元，`aria-pressed` 语义）；
 * - 分类药丸（含 ` · 18+` 文本后缀，不是独立角标）与标签下拉 `allTags`；
 * - 卡片前 5 个标签、灯箱展示全量标签；
 * - 外链来源标注（来源 / 二次元素材 · 仅作参考 / 原作者站点 / 英文关键词复制）；
 * - 下载分流：CharaDB 外链条目只有「前往来源原图」「原作者站点」、**不提供下载**；
 *   现实条目可「下载高清原图」；
 * - 搜索 + 重置 + 分页（Pager + 每页条数，替代旧加载更多）、灯箱（左右翻页 / 键盘 / 缩放拖动 / 复制英文 prompt）。
 *
 * 共享灯箱 `ReferenceLightbox` 底部固定是「下载 / 新窗口原图」两个链接，没有
 * slot 可分流，而本任务禁止改共享组件。这里用 `body[data-ref-tab='costume']`
 * 守卫的一段非 scoped 样式隐藏那段通用操作区，改由页面层 Teleport 的
 * `.costume-actions` 操作条接管（外链无 `download`、现实有 `download`）。
 * 该守卫只在服装页挂载期间生效，不影响姿势 / 人像灯箱。
 */

// ---------------------------------------------------------------------------
// 数据层
// ---------------------------------------------------------------------------

const { items, loading, error, load, retry } = useReferenceCostumes()

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
  costume: costumeItems,
  toggleCostume,
  isCostumeSelected,
  extraCostume,
  setPersonBCostumeLibrary,
  clearPersonBCostume,
} = useReferenceRecipeDraft()

const toast = useToast()

const route = useRoute()
const router = useRouter()

/** 本次是否在为人物B挑选服装（第 5 槽）。 */
const personBCostumeTarget = computed(
  () => readReferenceSelection(route.query) === 'person_b_costume',
)

function backToStudio(): void {
  void router.replace({
    path: route.path,
    query: withReferenceTab(route.query, 'studio'),
    hash: route.hash,
  })
}

/** 当前条目是否就是人物B服装（第 5 槽 = 服装库单图）。 */
function isPersonBCostume(item: CostumeItem): boolean {
  const library = item.library === 'costume-anime' ? 'costume-anime' : 'costume'
  return (
    extraCostume.value.source === 'library' &&
    extraCostume.value.library === library &&
    extraCostume.value.id === item.id
  )
}

/** 卡片选中态：B 选图模式下读第 5 槽，否则读 A 服装槽。 */
function isSelectedCostume(item: CostumeItem): boolean {
  return personBCostumeTarget.value
    ? isPersonBCostume(item)
    : isCostumeSelected(item.id)
}

// ---------------------------------------------------------------------------
// 筛选 / 视图状态
// ---------------------------------------------------------------------------

/** 一级分类；「全部」不限。 */
const kind = ref<CostumeKind>('全部')
/** 分类；空串 = 全部分类。 */
const category = ref('')
/** 标签；`all` = 全部单品与颜色标签（与 React 一致，用字符串哨兵）。 */
const tag = ref<string>(COSTUME_ALL_TAGS)
/** 搜索词 */
const query = ref('')
/** 当前页码（从 1 开始）；筛选 / 每页条数变化一律回第 1 页。 */
const page = ref(1)
/** 每页条数；三库共用 `pb.reference_page_size_v1`（默认 60）。 */
const pageSize = ref(loadReferencePageSize())
/** 灯箱当前下标（指向 `filtered`，与 React 的 `viewerIndex` 一致） */
const viewerIndex = ref<number | null>(null)

// ---------------------------------------------------------------------------
// 派生状态
// ---------------------------------------------------------------------------

/** 首屏加载且无数据：先不渲染筛选条，避免「全部 (0)」闪烁。 */
const initialLoading = computed(() => loading.value && items.value.length === 0)

/** 一级分类 + 安全模式过滤后的条目（React `baseCostumes`）。 */
const baseItems = computed(() =>
  costumeBaseItems(items.value, kind.value, safeMode.value),
)

/** 当前一级分类下被安全模式隐藏的 18+ 数量（解锁药丸文案）。 */
const hiddenTotal = computed(() => costumeHiddenNsfwCount(items.value, kind.value))

/** 实际生效的分类（安全模式下含 18+ 的分类自动落回全部）。 */
const activeCategory = computed(() =>
  resolveActiveCategory(category.value, safeMode.value, items.value),
)

const categorySummaries = computed(() =>
  costumeCategorySummaries(baseItems.value, items.value),
)

const allTags = computed(() => costumeTagOptions(baseItems.value, activeCategory.value))

/** 实际生效的标签（选中标签消失时落回全部）。 */
const activeTag = computed(() =>
  resolveActiveTag(tag.value, baseItems.value, activeCategory.value),
)

const filters = computed(() => ({
  category: activeCategory.value,
  tag: activeTag.value,
  query: query.value,
}))

const filtered = computed(() => filterCostumes(baseItems.value, filters.value))
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

// ---------------------------------------------------------------------------
// 交互：筛选
// ---------------------------------------------------------------------------

function setKind(next: CostumeKind): void {
  if (kind.value === next) return
  kind.value = next
  category.value = ''
  tag.value = COSTUME_ALL_TAGS
  page.value = 1
  viewerIndex.value = null
}

function selectCategory(next: string): void {
  category.value = next
  tag.value = COSTUME_ALL_TAGS
  page.value = 1
}

function onTagChange(event: Event): void {
  tag.value = (event.target as HTMLSelectElement).value
  page.value = 1
}

function onQueryInput(): void {
  page.value = 1
}

function resetFilters(): void {
  kind.value = '全部'
  category.value = ''
  tag.value = COSTUME_ALL_TAGS
  query.value = ''
  page.value = 1
  viewerIndex.value = null
}

/** 切换每页条数：写本地记忆并回到第 1 页（三库共用同一个键）。 */
function onPageSizeChange(next: number): void {
  pageSize.value = next
  page.value = 1
  saveReferencePageSize(next)
}

// ---------------------------------------------------------------------------
// 配方
// ---------------------------------------------------------------------------

/** 卡片「加入配方 / 已选」：多选 toggle，同一 id 再点即移除。 */
function onToggleCostume(item: CostumeItem): void {
  if (personBCostumeTarget.value) {
    if (isPersonBCostume(item)) {
      clearPersonBCostume()
      toast.info(`已清除当前B变体的服装「${item.服装名称}」`)
    } else {
      const library = item.library === 'costume-anime' ? 'costume-anime' : 'costume'
      setPersonBCostumeLibrary(library, item.id, item.服装名称)
      toast.success(`已设为当前B变体的服装「${item.服装名称}」`)
    }
    return
  }
  const added = toggleCostume(item)
  toast.success(
    added
      ? `已加入${item.服装名称}（服装槽共 ${costumeItems.value.length} 张）`
      : `已移除${item.服装名称}（服装槽共 ${costumeItems.value.length} 张）`,
  )
}

// ---------------------------------------------------------------------------
// 18+ 安全模式
// ---------------------------------------------------------------------------

function backendBlockedToast(): void {
  toast.error('后端未开启 18+ 总闸（ATELIER_REFERENCE_ALLOW_NSFW），无法解锁')
}

function onToggleSafeMode(): void {
  if (!safeMode.value) {
    toggleSafeMode()
    toast.success('已开启安全模式（已隐藏 18+ 敏感服装分类）')
    return
  }
  const accepted = requestUnlock(() => toast.success('已解锁 18+ 完整图库模式'))
  if (!accepted) backendBlockedToast()
}

function onUnlockPill(): void {
  const accepted = requestUnlock(() => {
    category.value = ''
    tag.value = COSTUME_ALL_TAGS
    page.value = 1
    toast.success('已解锁 18+ 敏感服装分类')
  })
  if (!accepted) backendBlockedToast()
}

function onConfirmAgeGate(): void {
  confirmUnlock()
  toast.success('已解锁 18+ 完整图库模式')
}

// ---------------------------------------------------------------------------
// 灯箱
// ---------------------------------------------------------------------------

const viewerItem = computed<CostumeItem | null>(() => {
  const index = viewerIndex.value
  if (index === null) return null
  return filtered.value[index] ?? null
})

const viewerImageUrl = computed(() =>
  viewerItem.value ? costumePreviewUrl(viewerItem.value) : null,
)

/** 外链条目：操作按钮改为「前往来源原图 / 原作者站点」，不提供下载。 */
const viewerRemote = computed(() =>
  viewerItem.value ? isRemoteCostume(viewerItem.value) : false,
)

const viewerAuthorUrl = computed(() =>
  viewerItem.value
    ? costumeAuthorSiteUrl(viewerItem.value, viewerImageUrl.value)
    : null,
)

const viewerMeta = computed(() =>
  viewerItem.value ? costumeLightboxMeta(viewerItem.value) : [],
)

const viewerCounter = computed(() =>
  viewerItem.value ? costumeCounter(viewerIndex.value ?? 0, filtered.value.length) : '',
)

const viewerSelected = computed(() =>
  viewerItem.value ? isSelectedCostume(viewerItem.value) : false,
)

const viewerDownloadName = computed(() =>
  viewerItem.value ? costumeDownloadName(viewerItem.value) : '',
)

/**
 * 外链条目「不提供下载」的双保险。
 *
 * 共享灯箱在 `imageUrl` 存在时会恒定渲染 `<a :download>`，它的操作区已由
 * 守卫样式隐藏（见文件头），但 DOM 属性仍在。外链素材不允许下载入口，
 * 因此这里在渲染后移除 `download` 属性 —— 只操作 DOM，不改共享组件源码。
 */
async function stripRemoteDownload(): Promise<void> {
  if (!viewerRemote.value) return
  await nextTick()
  for (const link of document.querySelectorAll<HTMLAnchorElement>(
    '.ref-lightbox__action-grid a[download]',
  )) {
    link.removeAttribute('download')
  }
}

watch([viewerImageUrl, viewerRemote], () => void stripRemoteDownload())

function openViewer(index: number): void {
  viewerIndex.value = index
}

function closeViewer(): void {
  viewerIndex.value = null
}

/** 左右翻页：循环，与 React `(i ± 1 + len) % len` 一致。 */
function stepViewer(direction: number): void {
  if (viewerIndex.value === null || filtered.value.length === 0) return
  viewerIndex.value = stepCostumeIndex(viewerIndex.value, filtered.value.length, direction)
}

function toggleViewerSelection(): void {
  if (viewerItem.value) onToggleCostume(viewerItem.value)
}

// ---------------------------------------------------------------------------
// 生命周期
// ---------------------------------------------------------------------------

onMounted(() => {
  // 共享灯箱操作区在服装页由页面层接管，用 body 标记作为样式守卫（见文件头注释）。
  document.body.dataset.refTab = 'costume'
  void loadBackendGate()
  void load()
})

onBeforeUnmount(() => {
  delete document.body.dataset.refTab
})
</script>

<template>
  <div class="costume-tab">
    <header class="costume-head">
      <!--
        `tab-placeholder__title` 是 ReferenceView 骨架期冻结的「页签面板标题」契约，
        真实页签沿用同一 class，避免 ReferenceView.spec.ts 的 `?tab=` 直达断言失效。
      -->
      <h1 class="costume-head__title tab-placeholder__title">服装库</h1>
      <div class="costume-head__actions">
        <!-- 安全模式：SFW / 18+ 双态配色对齐 §5；后端总闸关闭时置灰 -->
        <button
          type="button"
          class="costume-safe"
          :class="safeMode ? 'is-safe' : 'is-full'"
          data-testid="costume-safe-toggle"
          :data-safe="safeMode ? '1' : '0'"
          :data-gate="nsfwAvailable ? 'open' : 'closed'"
          :disabled="safeMode && !nsfwAvailable"
          :aria-pressed="!safeMode"
          :title="
            safeMode
              ? nsfwAvailable
                ? '当前已开启安全模式（已隐藏 18+ 敏感服装），点击可解锁完整图库'
                : '后端总闸已关闭（ATELIER_REFERENCE_ALLOW_NSFW=0），无法解锁 18+'
              : '当前已显示 18+ 完整图库，点击可切回安全模式'
          "
          @click="onToggleSafeMode"
        >
          {{ safeMode ? '安全模式 (SFW)' : '18+ 完整模式' }}
        </button>
      </div>
    </header>

    <!-- 人物B服装选择态：与 A 槽一样留在库页签里自由筛选，单图替换 -->
    <div
      v-if="personBCostumeTarget"
      class="person-b-select-banner"
      data-testid="costume-person-b-banner"
    >
      <span class="person-b-select-banner__text">
        正在为人物B选择服装（单选，点击卡片即替换；再点已选卡片可清除）
      </span>
      <button
        type="button"
        class="person-b-select-banner__back"
        data-testid="costume-person-b-back"
        @click="backToStudio"
      >
        返回合成台
      </button>
    </div>

    <template v-if="!initialLoading">
      <!-- 一级分类按钮组：`aria-pressed` 语义（不是药丸） -->
      <div class="costume-kinds" role="group" aria-label="服装一级分类" data-testid="costume-kinds">
        <button
          v-for="value in COSTUME_KINDS"
          :key="value"
          type="button"
          class="costume-kind"
          :class="{ 'is-active': kind === value }"
          :aria-pressed="kind === value"
          :data-kind="value"
          @click="setKind(value)"
        >
          {{ value }}
        </button>
      </div>

      <!-- 分类药丸：18+ 是文本后缀，不是独立角标 -->
      <div
        class="costume-pills"
        role="group"
        aria-label="服装分类筛选"
        data-testid="costume-category-pills"
      >
        <button
          type="button"
          class="costume-pill"
          :class="{ 'is-active': activeCategory === '' }"
          :aria-pressed="activeCategory === ''"
          data-category=""
          @click="selectCategory('')"
        >
          全部穿搭 ({{ baseItems.length }})
        </button>
        <button
          v-for="summary in categorySummaries"
          :key="summary.name"
          type="button"
          class="costume-pill"
          :class="{ 'is-active': activeCategory === summary.name }"
          :aria-pressed="activeCategory === summary.name"
          :data-category="summary.name"
          :data-nsfw="summary.nsfw ? '1' : '0'"
          @click="selectCategory(summary.name)"
        >
          {{ summary.name }} ({{ summary.count }})<template v-if="summary.nsfw"> · 18+</template>
        </button>

        <button
          v-if="safeMode && hiddenTotal > 0"
          type="button"
          class="costume-pill is-unlock"
          data-testid="costume-unlock-nsfw"
          :disabled="!nsfwAvailable"
          :title="nsfwAvailable ? '解锁后显示 18+ 敏感服装' : '后端总闸已关闭，无法解锁'"
          @click="onUnlockPill"
        >
          解锁 18+ 敏感服装 ({{ hiddenTotal }})
        </button>
      </div>

      <!-- 搜索 + 标签下拉 + 重置 -->
      <div class="costume-filters">
        <label class="costume-search">
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <circle cx="7" cy="7" r="4.2" fill="none" stroke="currentColor" stroke-width="1.3" />
            <path d="m10.2 10.2 3 3" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" />
          </svg>
          <input
            v-model="query"
            type="search"
            data-testid="costume-search"
            :placeholder="COSTUME_SEARCH_PLACEHOLDER"
            aria-label="搜索服装"
            @input="onQueryInput"
          />
        </label>

        <select
          class="costume-select"
          data-testid="costume-tag"
          aria-label="单品与颜色标签"
          :value="activeTag"
          @change="onTagChange"
        >
          <option :value="COSTUME_ALL_TAGS">全部单品与颜色标签</option>
          <option v-for="value in allTags" :key="value" :value="value">{{ value }}</option>
        </select>

        <button type="button" class="costume-reset" data-testid="costume-reset" @click="resetFilters">
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
    </template>

    <ReferenceGrid
      :loading="loading"
      :error="error"
      :total="initialLoading ? 0 : filtered.length"
      :page="page"
      :total-pages="totalPages"
      :page-size="pageSize"
      empty-title="没有找到匹配的服装穿搭"
      empty-hint="试试更换搜索词或切换分类"
      :skeleton-count="10"
      skeleton-aspect="2/3"
      @retry="retry"
      @update:page="page = $event"
      @update:page-size="onPageSizeChange"
    >
      <ReferenceCard
        v-for="(item, index) in visibleItems"
        :key="item.id"
        data-testid="costume-card"
        :data-id="item.id"
        :data-library="item.library ?? 'costume'"
        :data-remote="isRemoteCostume(item) ? '1' : '0'"
        :src="costumeThumbnailUrl(item)"
        :title="item.服装名称"
        :alt="item.服装名称"
        :badge="item.id"
        :angle="item.分类"
        :meta-left="costumeSourceLabel(item)"
        aspect="2/3"
        fit="contain"
        selectable
        :selected="isSelectedCostume(item)"
        @open="openViewer(pageOffset + index)"
        @toggle-select="onToggleCostume(item)"
      >
        <!-- 卡片只展示前 5 个标签；灯箱里展示全量（见 viewerMeta） -->
        <div class="costume-card">
          <div class="costume-card__tags">
            <span v-for="value in costumeTagPreview(item)" :key="value" class="costume-card__tag">
              {{ value }}
            </span>
          </div>
          <div class="costume-card__keywords" :title="item.关键词">{{ item.关键词 }}</div>
        </div>
      </ReferenceCard>
    </ReferenceGrid>

    <ReferenceLightbox
      :open="viewerItem !== null"
      :title="viewerItem?.服装名称 ?? ''"
      :image-url="viewerImageUrl"
      :alt="viewerItem?.服装名称 ?? ''"
      :badge="viewerItem?.id"
      :angle="viewerItem?.分类"
      :counter="viewerCounter"
      :meta-rows="viewerMeta"
      :selected="viewerSelected"
      select-label="加入角色配方"
      selected-label="已在角色配方中（点击移除）"
      :download-name="viewerDownloadName"
      :copy-value="viewerItem?.关键词 ?? ''"
      copy-toast="已复制英文服装 Prompt"
      :can-prev="filtered.length > 1"
      :can-next="filtered.length > 1"
      :can-prev-group="filtered.length > 1"
      :can-next-group="filtered.length > 1"
      @close="closeViewer"
      @prev="stepViewer(-1)"
      @next="stepViewer(1)"
      @prev-group="stepViewer(-1)"
      @next-group="stepViewer(1)"
      @toggle-select="toggleViewerSelection"
    />

    <!--
      灯箱操作条（页面层接管共享灯箱的操作区）：
      - 外链（CharaDB）：只有「前往来源原图」「原作者站点」，均无 download；
      - 现实条目：「下载高清原图」（带 download）与「新窗口原图」。
    -->
    <Teleport to="body">
      <div v-if="viewerItem" class="costume-actions" data-testid="costume-actions">
        <span v-if="viewerRemote" class="costume-actions__note">二次元素材 · 仅作参考</span>

        <template v-if="viewerRemote">
          <a
            v-if="viewerImageUrl"
            class="costume-actions__btn"
            data-testid="costume-source-image"
            :href="viewerImageUrl"
            target="_blank"
            rel="noopener noreferrer"
          >
            前往来源原图
          </a>
          <a
            v-if="viewerAuthorUrl"
            class="costume-actions__btn"
            data-testid="costume-author-site"
            :href="viewerAuthorUrl"
            target="_blank"
            rel="noopener noreferrer"
          >
            原作者站点
          </a>
        </template>

        <template v-else>
          <a
            v-if="viewerImageUrl"
            class="costume-actions__btn is-primary"
            data-testid="costume-download"
            :href="viewerImageUrl"
            :download="viewerDownloadName"
          >
            下载高清原图
          </a>
          <a
            v-if="viewerImageUrl"
            class="costume-actions__btn"
            data-testid="costume-new-window"
            :href="viewerImageUrl"
            target="_blank"
            rel="noopener noreferrer"
          >
            新窗口原图
          </a>
        </template>
      </div>
    </Teleport>

    <ReferenceAgeGate
      :open="ageGateOpen"
      @confirm="onConfirmAgeGate"
      @cancel="cancelUnlock"
    />

    <!-- 供自动化断言：不渲染可见文案（多选，逗号分隔） -->
    <span class="costume-sr-only" data-testid="costume-selected-id">
      {{ costumeItems.map((item) => item.id).join(',') }}
    </span>
    <span class="costume-sr-only" data-testid="costume-selected-count">
      {{ costumeItems.length }}
    </span>
    <span class="costume-sr-only" data-testid="costume-recipe-count">
      {{ costumeItems.length ? 1 : 0 }}/3
    </span>
    <span class="costume-sr-only" data-testid="costume-filtered-total">
      {{ initialLoading ? 0 : filtered.length }}
    </span>
    <span class="costume-sr-only" data-testid="costume-visible-count">
      {{ visibleItems.length }}
    </span>
    <span class="costume-sr-only" data-testid="costume-can-unlock">{{ canUnlock ? '1' : '0' }}</span>
  </div>
</template>

<style scoped>
.costume-tab {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.costume-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.costume-head__title {
  margin: 0;
  color: var(--text-strong);
  font-size: 20px;
  font-weight: 600;
  line-height: 1.3;
}

/* 人物B服装选择横幅 */
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

.costume-head__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

/* 安全模式按钮：§5 SFW 态 / 18+ 态配色 */
.costume-safe {
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

.costume-safe.is-safe {
  border: 1px solid var(--accent-green-border);
  background: var(--fill-faint);
  color: var(--accent-green-text);
}

.costume-safe.is-full {
  border: 1px solid var(--accent-red-border);
  background: var(--accent-red-soft);
  color: var(--accent-red-text);
}

.costume-safe:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* 一级分类按钮组：32px 高、圆角 8px（React Button 口径） */
.costume-kinds {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.costume-kind {
  box-sizing: border-box;
  min-height: 32px;
  padding: 0 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: transparent;
  color: var(--text-strong);
  font-size: 12px;
  font-weight: 500;
  line-height: 1;
  white-space: nowrap;
  transition:
    background-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease);
}

.costume-kind:hover {
  background: var(--fill-subtle);
}

.costume-kind.is-active {
  border-color: transparent;
  background: var(--btn-inverse-bg);
  color: var(--on-inverse);
}

/* 分类药丸：32px / 全圆 / 内边距 6px 14px / 14px 500 / gap 8px */
.costume-pills {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 4px;
  scrollbar-width: none;
}

.costume-pills::-webkit-scrollbar {
  display: none;
}

@media (min-width: 640px) {
  .costume-pills {
    flex-wrap: wrap;
    padding-bottom: 0;
  }
}

.costume-pill {
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

.costume-pill:hover {
  background: var(--surface-card-hover);
  color: var(--text-strong);
}

.costume-pill.is-active {
  background: var(--btn-inverse-bg);
  color: var(--on-inverse);
}

.costume-pill.is-unlock {
  border: 1px dashed var(--accent-red-border-strong);
  background: var(--accent-red-soft-faint);
  color: var(--accent-red-text);
}

.costume-pill:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* 筛选面板：1280 × 68 / 圆角 22 / 内边距 16 / gap 12 / 深色底 */
.costume-filters {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 220px auto;
  align-items: center;
  gap: 12px;
  margin: 12px 0 16px;
  padding: 16px;
  border-radius: 22px;
  background: var(--surface-panel);
}

@media (max-width: 1023px) {
  .costume-filters {
    grid-template-columns: minmax(0, 1fr) 200px;
  }
}

@media (max-width: 639px) {
  .costume-filters {
    grid-template-columns: minmax(0, 1fr);
  }
}

.costume-search {
  position: relative;
  display: block;
  min-width: 0;
}

.costume-search input {
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

.costume-search input::placeholder {
  color: var(--text-faint);
}

.costume-search input:focus {
  border-color: var(--primary);
  outline: none;
}

.costume-search svg {
  position: absolute;
  top: 50%;
  left: 12px;
  width: 16px;
  height: 16px;
  color: var(--text-muted);
  transform: translateY(-50%);
  pointer-events: none;
}

.costume-select {
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

.costume-reset {
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

.costume-reset svg {
  width: 14px;
  height: 14px;
}

.costume-reset:hover {
  background: var(--fill-subtle);
  color: var(--text-strong);
}

/* 卡片底部：标签（前 5 个）+ 英文关键词 */
.costume-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 0 6px 2px;
}

.costume-card__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.costume-card__tag {
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--surface-inset);
  color: var(--text-muted);
  font-size: 10px;
  line-height: 16px;
}

.costume-card__keywords {
  overflow: hidden;
  color: var(--text-muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 10px;
  line-height: 1.5;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 灯箱操作条：固定底部居中，层级高于共享灯箱 */
.costume-actions {
  position: fixed;
  bottom: 24px;
  left: 50%;
  z-index: calc(var(--z-lightbox) + 1);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 8px;
  box-sizing: border-box;
  max-width: min(96vw, 560px);
  padding: 8px;
  border: 1px solid var(--border-soft);
  border-radius: 12px;
  background: var(--surface-overlay);
  box-shadow: var(--shadow-3);
  color: var(--text-strong);
  transform: translateX(-50%);
}

.costume-actions__note {
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.4;
}

.costume-actions__btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 32px;
  padding: 0 12px;
  border: 1px solid var(--border-medium);
  border-radius: 8px;
  background: transparent;
  color: var(--text-strong);
  font-size: 12px;
  font-weight: 500;
  text-decoration: none;
  white-space: nowrap;
}

.costume-actions__btn:hover {
  background: var(--fill-subtle);
}

.costume-actions__btn.is-primary {
  border-color: transparent;
  background: var(--btn-inverse-bg);
  color: var(--on-inverse);
}

.costume-actions__btn.is-primary:hover {
  background: var(--btn-inverse-bg-hover);
}

@media (max-width: 639px) {
  .costume-actions {
    right: 12px;
    bottom: 12px;
    left: 12px;
    max-width: none;
    transform: none;
  }
}

/* 仅供自动化读取的状态行 */
.costume-sr-only {
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

<style>
/*
 * 服装页专用适配（非 scoped，但由 body 标记守卫）：
 * 共享灯箱 `ReferenceLightbox` 底部固定渲染「下载 / 新窗口原图」，没有 slot
 * 可做来源分流；本任务禁止改共享组件，因此服装页挂载期间隐藏这段通用操作区，
 * 由页面层 `.costume-actions` 接管（CharaDB 不提供下载）。
 * 标记只在 ReferenceCostumesTab 挂载期间存在，姿势 / 人像灯箱不受影响。
 */
body[data-ref-tab='costume'] .ref-lightbox__action-grid {
  display: none;
}
</style>