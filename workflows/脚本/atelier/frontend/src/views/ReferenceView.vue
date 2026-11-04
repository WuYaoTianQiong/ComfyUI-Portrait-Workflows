<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useQuery } from '@tanstack/vue-query'

import JustifiedGrid from '../components/JustifiedGrid.vue'
import Pager from '../components/Pager.vue'
import QueryState from '../components/QueryState.vue'
import RefLightbox from '../components/RefLightbox.vue'
import {
  listReferenceItems,
  listReferenceLibraries,
  poseCodeOf,
  type ReferenceFacetValue,
  type ReferenceItem,
  type ReferenceItemPage,
  type ReferenceLibraryStats,
} from '../api/reference'
import { confirmDialog } from '../utils/naive'

/**
 * AI 参考图库 · 只读浏览（M1）。
 *
 * 三 Tab：姿势库 / 服装库 / 人像库；服装库下再分「本地 / 外链」
 * （440 条 CharaDB 外链服装只能热链展示，不能参与出图）。
 *
 * 设计取舍：
 * - facet 药丸直接用 `/reference/libraries` 返回的 `groups/facets/angles`，
 *   不在前端硬编码分类名（上游分类会变，后端才是唯一口径）；
 * - DTO 没有宽高，网格先按 3:4 兜底，图片 load 后回填真实比例重排一次，
 *   这样 JustifiedGrid 的「不裁切」在参考库上也成立；
 * - 同一姿势的多角度按 `(体系, 姿势编号)` 聚合：当前页只有部分角度，
 *   点箭头时用 `search=姿势编号` 拉全组并缓存，之后前端只换 id；
 * - 18+ 默认关闭。后端总闸没开时（`visible < total` 说明有敏感条目被过滤），
 *   开关置灰，避免前端出现一套后端不认的状态。
 */

interface TabDef {
  key: string
  label: string
  libraries: Array<{ key: string; label: string }>
}

const TABS: TabDef[] = [
  { key: 'pose', label: '姿势库', libraries: [{ key: 'pose', label: '姿势库' }] },
  {
    key: 'costume',
    label: '服装库',
    libraries: [
      { key: 'costume', label: '本地服装' },
      { key: 'costume-anime', label: '外链服装' },
    ],
  },
  { key: 'portrait', label: '人像库', libraries: [{ key: 'portrait', label: '人像库' }] },
]

const FACET_LABELS: Record<string, { group: string; facet: string | null }> = {
  pose: { group: '体系', facet: '分类' },
  costume: { group: '分类', facet: null },
  portrait: { group: '分区', facet: '发长' },
  'costume-anime': { group: '一级分类', facet: '分类' },
}

const ANGLE_ORDER = ['正面', '侧面', '斜侧', '仰视', '俯视']

const PAGE_SIZE = 60

const activeTab = ref('pose')
const activeLibrary = ref('pose')
const activeTabDef = computed<TabDef>(() => TABS.find((tab) => tab.key === activeTab.value) ?? TABS[0])

// ---------------------------------------------------------------------------
// 库统计 / facet
// ---------------------------------------------------------------------------

const {
  data: librariesData,
  isError: librariesError,
  error: librariesErrorValue,
  refetch: refetchLibraries,
} = useQuery({
  queryKey: ['reference', 'libraries'],
  queryFn: listReferenceLibraries,
  staleTime: 60_000,
})

const libraries = computed<ReferenceLibraryStats[]>(
  () => librariesData.value?.libraries ?? [],
)

const statsByLib = computed<Record<string, ReferenceLibraryStats | undefined>>(() => {
  const map: Record<string, ReferenceLibraryStats | undefined> = {}
  for (const lib of libraries.value) map[lib.library] = lib
  return map
})

const currentStats = computed(() => statsByLib.value[activeLibrary.value])

/**
 * 后端总闸是否打开：`ALLOW_NSFW=0` 时 `visible < total`（敏感条目被过滤），
 * `ALLOW_NSFW=1` 时两者相等。没有单独的配置端点，这里用这个差值判断；
 * 如果部署时把 NSFW 名单配成空，会误判为已开启（属于配置边界）。
 */
const nsfwAllowed = computed(
  () => libraries.value.length > 0 && !libraries.value.some((lib) => lib.visible < lib.total),
)

const nsfwTitle = computed(() =>
  nsfwAllowed.value
    ? '开启后显示敏感分类（默认关闭）'
    : '后端未开启 ATELIER_REFERENCE_ALLOW_NSFW，敏感内容不可用',
)

function tabVisibleCount(key: string) {
  const tab = TABS.find((item) => item.key === key)
  if (!tab) return 0
  return tab.libraries.reduce(
    (sum, lib) => sum + (statsByLib.value[lib.key]?.visible ?? 0),
    0,
  )
}

function tabTotalCount(key: string) {
  const tab = TABS.find((item) => item.key === key)
  if (!tab) return 0
  return tab.libraries.reduce(
    (sum, lib) => sum + (statsByLib.value[lib.key]?.total ?? 0),
    0,
  )
}

interface FacetGroup {
  key: 'group' | 'facet' | 'angle'
  label: string
  values: ReferenceFacetValue[]
}

const facetGroups = computed<FacetGroup[]>(() => {
  const stats = currentStats.value
  if (!stats) return []
  const labels = FACET_LABELS[activeLibrary.value] ?? { group: '分类', facet: null }
  const groups: FacetGroup[] = []
  if (stats.groups.length) {
    groups.push({ key: 'group', label: labels.group, values: stats.groups })
  }
  if (stats.facets.length) {
    groups.push({ key: 'facet', label: labels.facet ?? '细分', values: stats.facets })
  }
  if (stats.angles.length) {
    groups.push({ key: 'angle', label: '角度', values: stats.angles })
  }
  return groups
})

// ---------------------------------------------------------------------------
// 查询条件
// ---------------------------------------------------------------------------

const searchInput = ref('')
const search = ref('')
const group = ref('')
const facet = ref('')
const angle = ref('')
const page = ref(1)
const showNsfw = ref(false)

let debounceTimer: ReturnType<typeof setTimeout> | null = null

watch(searchInput, (value) => {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    const next = value.trim()
    if (next === search.value) return
    search.value = next
    page.value = 1
  }, 250)
})

onBeforeUnmount(() => {
  if (debounceTimer) clearTimeout(debounceTimer)
})

function clearSearch() {
  if (debounceTimer) clearTimeout(debounceTimer)
  searchInput.value = ''
  search.value = ''
  page.value = 1
}

const hasFilters = computed(
  () => !!group.value || !!facet.value || !!angle.value || !!search.value,
)

function facetValue(key: FacetGroup['key']): string {
  if (key === 'group') return group.value
  if (key === 'facet') return facet.value
  return angle.value
}

function toggleFacet(key: FacetGroup['key'], value: string) {
  const next = facetValue(key) === value ? '' : value
  if (key === 'group') {
    group.value = next
    // 上层维度变了，下层的分类/角度可能不属于新体系，顺带清掉
    facet.value = ''
    angle.value = ''
  } else if (key === 'facet') {
    facet.value = next
  } else {
    angle.value = next
  }
  page.value = 1
}

function clearFacets() {
  group.value = ''
  facet.value = ''
  angle.value = ''
  page.value = 1
}

/**
 * `nsfw` 在端点里的语义是「只看敏感 / 只看非敏感 / 全部」，
 * 不是「是否包含敏感」：
 * - 总闸关闭：后端已经过滤，不传参数；
 * - 总闸打开 + 开关关闭：传 false，只看非敏感；
 * - 总闸打开 + 开关打开：不传，全部。
 */
const nsfwParam = computed<boolean | null>(() => {
  if (!nsfwAllowed.value) return null
  return showNsfw.value ? null : false
})

const queryKey = computed(() => [
  'reference',
  'items',
  activeLibrary.value,
  search.value,
  group.value,
  facet.value,
  angle.value,
  nsfwParam.value,
  page.value,
])

const {
  data: itemsData,
  isFetching,
  isError,
  error,
  refetch,
} = useQuery<ReferenceItemPage>({
  queryKey,
  queryFn: () =>
    listReferenceItems({
      library: activeLibrary.value,
      search: search.value,
      group: group.value,
      facet: facet.value,
      angle: angle.value,
      nsfw: nsfwParam.value,
      page: page.value,
      page_size: PAGE_SIZE,
    }),
  placeholderData: (prev) => prev,
})

const items = computed<ReferenceItem[]>(() => itemsData.value?.items ?? [])
const total = computed(() => itemsData.value?.total ?? 0)
const totalPages = computed(() =>
  Math.max(1, Math.ceil(total.value / (itemsData.value?.page_size || PAGE_SIZE))),
)

function scrollGridTop() {
  nextTick(() => {
    gridEl.value?.scrollTo({ top: 0 })
  })
}

// ---------------------------------------------------------------------------
// 切换 Tab / 子库 / 18+
// ---------------------------------------------------------------------------

function selectTab(key: string) {
  if (key === activeTab.value) return
  const tab = TABS.find((item) => item.key === key)
  if (!tab) return
  activeTab.value = key
  activeLibrary.value = tab.libraries[0].key
  group.value = ''
  facet.value = ''
  angle.value = ''
  clearSearch()
  page.value = 1
  resetAngleCache()
  scrollGridTop()
}

function selectLibrary(key: string) {
  if (key === activeLibrary.value) return
  activeLibrary.value = key
  group.value = ''
  facet.value = ''
  angle.value = ''
  page.value = 1
  resetAngleCache()
  scrollGridTop()
}

async function onNsfwChange(event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.checked) {
    showNsfw.value = false
    page.value = 1
    return
  }
  const ok = await confirmDialog({
    title: '查看 18+ 内容',
    content: '开启后会显示敏感参考（性感姿势、内衣・睡衣、性感穿搭等）。仅限个人使用。',
    positiveText: '开启',
    negativeText: '取消',
    type: 'warning',
  })
  if (ok) {
    showNsfw.value = true
    page.value = 1
    resetAngleCache()
  } else {
    input.checked = false
  }
}

watch(nsfwParam, () => {
  resetAngleCache()
  page.value = 1
})

watch(page, scrollGridTop)

// ---------------------------------------------------------------------------
// 同姿势多角度聚合
// ---------------------------------------------------------------------------

const angleCache = ref<Record<string, ReferenceItem[]>>({})

function resetAngleCache() {
  angleCache.value = {}
  cardItems.value = {}
}

function poseGroupKey(item: ReferenceItem): string {
  const code = poseCodeOf(item)
  return code ? `${item.group}|${code}` : ''
}

async function loadAngles(item: ReferenceItem): Promise<ReferenceItem[]> {
  const key = poseGroupKey(item)
  if (!key) return [item]
  const cached = angleCache.value[key]
  if (cached) return cached

  const code = poseCodeOf(item)
  try {
    const res = await listReferenceItems({
      library: 'pose',
      search: code,
      group: item.group,
      nsfw: nsfwParam.value,
      page: 1,
      page_size: 200,
    })
    const siblings = res.items
      .filter((candidate) => poseCodeOf(candidate) === code && candidate.group === item.group)
      .sort((a, b) => angleRank(a.angle) - angleRank(b.angle))
    const groupItems = siblings.length ? siblings : [item]
    angleCache.value = { ...angleCache.value, [key]: groupItems }
    return groupItems
  } catch {
    return [item]
  }
}

function angleRank(value: string): number {
  const index = ANGLE_ORDER.indexOf(value)
  return index === -1 ? ANGLE_ORDER.length : index
}

/** 卡片上当前显示的条目（多角度切换后不一定是列表里的那一条）。 */
const cardItems = ref<Record<string, ReferenceItem>>({})

function displayItem(item: ReferenceItem): ReferenceItem {
  return cardItems.value[item.id] ?? item
}

async function cycleAngle(item: ReferenceItem, delta: number) {
  const groupItems = await loadAngles(displayItem(item))
  if (groupItems.length <= 1) return
  const current = displayItem(item)
  const index = groupItems.findIndex((candidate) => candidate.id === current.id)
  const nextIndex = (index + delta + groupItems.length) % groupItems.length
  cardItems.value = { ...cardItems.value, [item.id]: groupItems[nextIndex] }
}

// ---------------------------------------------------------------------------
// 灯箱
// ---------------------------------------------------------------------------

const lightboxItems = ref<ReferenceItem[]>([])
const lightboxIndex = ref(0)
const lightboxOpen = computed(() => lightboxItems.value.length > 0)

async function openLightbox(item: ReferenceItem) {
  const current = displayItem(item)
  const groupItems = await loadAngles(current)
  const index = groupItems.findIndex((candidate) => candidate.id === current.id)
  lightboxItems.value = groupItems
  lightboxIndex.value = index >= 0 ? index : 0
}

function closeLightbox() {
  lightboxItems.value = []
}

// ---------------------------------------------------------------------------
// 卡片：白模 / 深度、比例、失败占位
// ---------------------------------------------------------------------------

const depthCards = ref<Set<string>>(new Set())
const failedThumbs = ref<Set<string>>(new Set())
const ratios = ref<Record<string, number>>({})

function isDepth(item: ReferenceItem): boolean {
  return depthCards.value.has(item.id)
}

function setCardMode(item: ReferenceItem, depth: boolean) {
  const next = new Set(depthCards.value)
  if (depth) next.add(item.id)
  else next.delete(item.id)
  depthCards.value = next
}

function cardSrc(item: ReferenceItem): string {
  const current = displayItem(item)
  if (isDepth(item) && current.depth_url) return current.depth_url
  return current.thumb_url
}

function thumbKey(item: ReferenceItem): string {
  const current = displayItem(item)
  return `${current.id}:${isDepth(item) ? 'depth' : 'thumb'}`
}

function thumbFailed(item: ReferenceItem): boolean {
  return failedThumbs.value.has(thumbKey(item))
}

function markThumbFailed(item: ReferenceItem) {
  const next = new Set(failedThumbs.value)
  next.add(thumbKey(item))
  failedThumbs.value = next
}

function retryThumb(item: ReferenceItem) {
  const next = new Set(failedThumbs.value)
  next.delete(thumbKey(item))
  failedThumbs.value = next
}

function onThumbLoad(item: ReferenceItem, event: Event) {
  const img = event.target as HTMLImageElement
  if (!img.naturalWidth || !img.naturalHeight) return
  const current = displayItem(item)
  const ratio = img.naturalWidth / img.naturalHeight
  const previous = ratios.value[current.id]
  if (previous && Math.abs(previous - ratio) < 0.001) return
  ratios.value = { ...ratios.value, [current.id]: ratio }
}

function ratioOf(item: ReferenceItem): number {
  return ratios.value[displayItem(item).id] ?? 0.75
}

function itemKey(item: ReferenceItem): string {
  return item.id
}

function captionMeta(item: ReferenceItem): string {
  return [item.subtitle, item.group, item.facet].filter(Boolean).join(' · ')
}

// ---------------------------------------------------------------------------
// 滚动容器
// ---------------------------------------------------------------------------

const gridEl = ref<HTMLElement | null>(null)
</script>

<template>
  <section class="reference-page">
    <header class="head">
      <div class="tab-row">
        <button
          v-for="tab in TABS"
          :key="tab.key"
          class="tab"
          :class="{ active: activeTab === tab.key }"
          :title="`全库 ${tabTotalCount(tab.key)} 条`"
          @click="selectTab(tab.key)"
        >
          <span>{{ tab.label }}</span>
          <span v-if="tabVisibleCount(tab.key)" class="tab-count">
            {{ tabVisibleCount(tab.key) }}
          </span>
        </button>
      </div>

      <div class="head-tools">
        <div class="search-box">
          <input
            v-model="searchInput"
            type="search"
            placeholder="搜索名称 / 编号 / 分类 / 关键词"
            aria-label="搜索参考图库"
            @keydown.esc="clearSearch"
          />
          <button v-if="searchInput" class="search-clear" @click="clearSearch">清除</button>
        </div>

        <label class="nsfw-toggle" :class="{ disabled: !nsfwAllowed }" :title="nsfwTitle">
          <input
            type="checkbox"
            :checked="showNsfw"
            :disabled="!nsfwAllowed"
            @change="onNsfwChange"
          />
          <span>18+</span>
        </label>
      </div>
    </header>

    <div v-if="librariesError" class="banner error">
      参考库统计加载失败：{{ librariesErrorValue?.message ?? '未知错误' }}
      <button class="btn btn-sm" @click="refetchLibraries()">重试</button>
    </div>

    <div v-else-if="currentStats && !currentStats.available" class="banner warn">
      参考库文件不可用（{{ currentStats.label }}）：请检查 ATELIER_REFERENCE_ROOT 与
      ai-pose-gallery-zh 目录。
    </div>

    <div v-if="activeTabDef.libraries.length > 1" class="library-row">
      <span class="row-label">来源</span>
      <button
        v-for="lib in activeTabDef.libraries"
        :key="lib.key"
        class="pill"
        :class="{ active: activeLibrary === lib.key }"
        @click="selectLibrary(lib.key)"
      >
        <span>{{ lib.label }}</span>
        <span v-if="statsByLib[lib.key]?.visible" class="pill-count">
          {{ statsByLib[lib.key]?.visible }}
        </span>
      </button>
      <span v-if="activeLibrary === 'costume-anime'" class="row-hint">
        外链素材只做热链展示，不能参与本地出图
      </span>
    </div>

    <div class="facet-area">
      <div v-for="fg in facetGroups" :key="fg.key" class="facet-row">
        <span class="facet-label">{{ fg.label }}</span>
        <div class="pills">
          <button
            v-for="value in fg.values"
            :key="value.value"
            class="pill"
            :class="{ active: facetValue(fg.key) === value.value }"
            @click="toggleFacet(fg.key, value.value)"
          >
            <span>{{ value.value }}</span>
            <span class="pill-count">{{ value.count }}</span>
          </button>
        </div>
      </div>

      <div class="result-row">
        <span class="result-count">
          当前 <b>{{ total }}</b> 条
          <template v-if="currentStats">
            · 可见 {{ currentStats.visible }} / 全库 {{ currentStats.total }}
          </template>
        </span>
        <button v-if="hasFilters" class="btn btn-sm" @click="clearFacets">清除筛选</button>
        <span class="spacer" />
        <span v-if="isFetching" class="fetching">加载中…</span>
      </div>
    </div>

    <div ref="gridEl" class="grid-scroll">
      <QueryState
        :loading="isFetching && !items.length"
        :error="isError ? error : null"
        :empty="!items.length && !isFetching"
        loading-text="正在读取参考库…"
        empty-text="没有符合条件的参考图"
        @retry="refetch()"
      >
        <JustifiedGrid
          v-if="items.length"
          :items="items"
          :ratio="ratioOf"
          :key-of="itemKey"
          :target-row-height="250"
          :gap="10"
        >
          <template #default="{ item, height }">
            <article
              class="card"
              :title="
                displayItem(item).remote
                  ? `${displayItem(item).name}（外链素材，不能作为出图参考）`
                  : displayItem(item).name
              "
              @click="openLightbox(item)"
            >
              <div class="thumb" :style="{ height: `${height}px` }">
                <img
                  v-if="!thumbFailed(item)"
                  :src="cardSrc(item)"
                  :alt="displayItem(item).name || displayItem(item).id"
                  loading="lazy"
                  @load="onThumbLoad(item, $event)"
                  @error="markThumbFailed(item)"
                />

                <div v-else class="thumb-fallback" @click.stop>
                  <span>{{ displayItem(item).remote ? '外链加载失败' : '图片加载失败' }}</span>
                  <button class="btn btn-sm" @click="retryThumb(item)">重试</button>
                </div>

                <div class="marks">
                  <span v-if="displayItem(item).remote" class="mark remote">外链</span>
                  <span v-if="displayItem(item).hot" class="mark hot">热门</span>
                  <span v-if="displayItem(item).featured" class="mark featured">精选</span>
                </div>

                <div v-if="item.library === 'pose'" class="thumb-mode" @click.stop>
                  <button
                    class="mini"
                    :class="{ active: !isDepth(item) }"
                    title="白模图"
                    @click="setCardMode(item, false)"
                  >
                    白模
                  </button>
                  <button
                    class="mini"
                    :class="{ active: isDepth(item) }"
                    :disabled="!displayItem(item).depth_url"
                    title="深度图"
                    @click="setCardMode(item, true)"
                  >
                    深度
                  </button>
                </div>

                <div v-if="item.library === 'pose'" class="angle-switch" @click.stop>
                  <button class="mini arrow" title="上一角度" @click="cycleAngle(item, -1)">
                    ‹
                  </button>
                  <span class="angle-label">{{ displayItem(item).angle || '—' }}</span>
                  <button class="mini arrow" title="下一角度" @click="cycleAngle(item, 1)">
                    ›
                  </button>
                </div>
              </div>

              <div class="caption">
                <span class="name">
                  {{ displayItem(item).name || displayItem(item).id }}
                </span>
                <span class="meta">{{ captionMeta(displayItem(item)) }}</span>
              </div>
            </article>
          </template>
        </JustifiedGrid>
      </QueryState>
    </div>

    <footer class="foot">
      <span class="disclaimer">素材版权归原作者，仅限个人学习与创作。</span>
      <Pager :page="page" :total-pages="totalPages" @update:page="page = $event" />
    </footer>

    <RefLightbox
      v-if="lightboxOpen"
      :items="lightboxItems"
      :index="lightboxIndex"
      @update:index="lightboxIndex = $event"
      @close="closeLightbox"
    />
  </section>
</template>

<style scoped>
.reference-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--bg);
  color: var(--text);
}

.head {
  display: flex;
  align-items: center;
  gap: var(--gap-lg);
  padding: var(--gap-sm) var(--gap-lg);
  border-bottom: 1px solid var(--border);
  background: var(--panel);
}

.tab-row {
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
}

.tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text);
  padding: 6px 12px;
  font-size: var(--fs);
  font-weight: 600;
}

.tab:hover {
  background: var(--panel-2);
}

.tab.active {
  border-color: var(--primary);
  background: var(--primary-soft);
  color: var(--primary);
}

.tab-count {
  font-size: var(--fs-xs);
  font-weight: 400;
  opacity: 0.72;
}

.head-tools {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  margin-left: auto;
  min-width: 0;
}

.search-box {
  position: relative;
  display: flex;
  align-items: center;
}

.search-box input {
  width: 300px;
  padding-right: 52px;
}

.search-clear {
  position: absolute;
  right: 4px;
  border: none;
  background: transparent;
  color: var(--text);
  font-size: var(--fs-xs);
  opacity: 0.7;
  padding: 2px 4px;
}

.search-clear:hover {
  opacity: 1;
}

.nsfw-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: var(--fs-sm);
  cursor: pointer;
  user-select: none;
}

.nsfw-toggle input {
  padding: 0;
  margin: 0;
}

.nsfw-toggle.disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.banner {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: 8px var(--gap-lg);
  font-size: var(--fs-sm);
  border-bottom: 1px solid var(--border);
}

.banner.error {
  color: var(--danger);
  background: var(--danger-soft);
}

.banner.warn {
  color: var(--warn);
  background: var(--panel-2);
}

.library-row {
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
  flex-wrap: wrap;
  padding: 6px var(--gap-lg);
  border-bottom: 1px solid var(--border);
  background: var(--panel-2);
}

.row-label,
.facet-label {
  flex: none;
  width: 72px;
  font-size: var(--fs-xs);
  color: var(--text);
  opacity: 0.72;
}

.row-hint {
  margin-left: var(--gap-sm);
  font-size: var(--fs-xs);
  color: var(--warn);
}

.pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 9px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--panel-2);
  color: var(--text);
  font-size: var(--fs-xs);
  white-space: nowrap;
}

.pill:hover {
  border-color: var(--border-strong);
}

.pill.active {
  border-color: var(--primary);
  background: var(--primary-soft);
  color: var(--primary);
}

.pill-count {
  opacity: 0.62;
}

.facet-area {
  padding: 6px var(--gap-lg);
  border-bottom: 1px solid var(--border);
  background: var(--panel);
}

.facet-row {
  display: flex;
  align-items: flex-start;
  gap: var(--gap-sm);
  padding: 3px 0;
}

.facet-row .facet-label {
  padding-top: 3px;
}

.pills {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  min-width: 0;
}

.result-row {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding-top: 6px;
  font-size: var(--fs-xs);
}

.result-count {
  color: var(--text);
  opacity: 0.82;
}

.result-count b {
  color: var(--text);
  opacity: 1;
  font-weight: 700;
}

.spacer {
  flex: 1;
}

.fetching {
  color: var(--text);
  opacity: 0.6;
}

.grid-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: var(--gap) var(--gap-lg) var(--gap-lg);
}

.card {
  cursor: zoom-in;
}

.thumb {
  position: relative;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
}

.thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.thumb-fallback {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--gap-sm);
  width: 100%;
  height: 100%;
  padding: var(--gap-sm);
  color: var(--text);
  font-size: var(--fs-sm);
  text-align: center;
  background: repeating-linear-gradient(
    45deg,
    var(--panel-2),
    var(--panel-2) 8px,
    var(--panel-3) 8px,
    var(--panel-3) 16px
  );
}

.marks {
  position: absolute;
  left: 6px;
  top: 6px;
  display: flex;
  gap: 4px;
  pointer-events: none;
}

.mark {
  padding: 1px 6px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 600;
  line-height: 1.6;
  color: #fff;
}

.mark.remote {
  background: #b45309;
}

.mark.hot {
  background: #be123c;
}

.mark.featured {
  background: #6d28d9;
}

.thumb-mode {
  position: absolute;
  right: 6px;
  top: 6px;
  display: flex;
  gap: 3px;
}

.mini {
  border: 1px solid var(--border-strong);
  border-radius: 4px;
  background: rgba(13, 17, 23, 0.78);
  color: var(--text);
  font-size: var(--fs-xs);
  line-height: 1.6;
  padding: 1px 6px;
}

.mini:hover:not(:disabled) {
  background: rgba(13, 17, 23, 0.95);
  border-color: var(--primary);
}

.mini:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.mini.active {
  border-color: var(--primary);
  color: var(--primary);
}

.angle-switch {
  position: absolute;
  left: 6px;
  bottom: 6px;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 1px 4px;
  border-radius: 4px;
  background: rgba(13, 17, 23, 0.78);
}

.angle-label {
  font-size: var(--fs-xs);
  color: var(--text);
  min-width: 28px;
  text-align: center;
}

.mini.arrow {
  padding: 0 5px;
}

.caption {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 5px 2px 0;
}

.caption .name {
  font-size: var(--fs-sm);
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.caption .meta {
  font-size: var(--fs-xs);
  color: var(--text);
  opacity: 0.66;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.foot {
  display: flex;
  align-items: center;
  gap: var(--gap);
  padding: var(--gap-sm) var(--gap-lg);
  border-top: 1px solid var(--border);
  background: var(--panel);
}

.disclaimer {
  font-size: var(--fs-xs);
  color: var(--text);
  opacity: 0.6;
}

.foot :deep(.pager) {
  margin-left: auto;
}

@media (max-width: 900px) {
  .head {
    flex-direction: column;
    align-items: stretch;
    gap: var(--gap-sm);
  }

  .head-tools {
    margin-left: 0;
  }

  .search-box input {
    width: 100%;
  }

  .search-box {
    flex: 1;
  }

  .row-label,
  .facet-label {
    width: 56px;
  }
}
</style>