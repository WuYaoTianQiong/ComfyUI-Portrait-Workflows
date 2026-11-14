<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import type { HairItem } from '../../api/reference'
import { useReferenceHairs } from '../../composables/useReferenceLibrary'
import { useReferenceRecipeDraft } from '../../composables/useReferenceRecipeDraft'
import { useToast } from '../../composables/useToast'
import { readReferenceSearch } from './referenceDeepLink'
import {
  clampPage,
  loadReferencePageSize,
  pageCount,
  pageSlice,
  saveReferencePageSize,
} from './components/portraitView'

import ReferenceCard from './components/ReferenceCard.vue'
import ReferenceGrid from './components/ReferenceGrid.vue'
import ReferenceLightbox from './components/ReferenceLightbox.vue'

const { items, loading, error, load, retry } = useReferenceHairs()
const draft = useReferenceRecipeDraft()
const toast = useToast()

const view = ref('')
const group = ref('')
const route = useRoute()
const query = ref(readReferenceSearch(route.query))
const page = ref(1)
const pageSize = ref(loadReferencePageSize())
const viewerIndex = ref<number | null>(null)

const viewOptions = computed(() => {
  const counts = new Map<string, number>()
  for (const item of items.value) {
    if (!item.视图) continue
    counts.set(item.视图, (counts.get(item.视图) ?? 0) + 1)
  }
  return [...counts.entries()].map(([value, count]) => ({ value, count }))
})

const groupOptions = computed(() => {
  const counts = new Map<string, number>()
  for (const item of items.value) {
    if (!item.分区) continue
    counts.set(item.分区, (counts.get(item.分区) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => b.count - a.count || a.value.localeCompare(b.value))
})

const filtered = computed(() => {
  const needle = query.value.trim().toLowerCase()
  return items.value.filter((item) => {
    if (view.value && item.视图 !== view.value) return false
    if (group.value && item.分区 !== group.value) return false
    if (needle && !item.检索.toLowerCase().includes(needle)) return false
    return true
  })
})

const totalCount = computed(() => filtered.value.length)
const totalPages = computed(() => pageCount(totalCount.value, pageSize.value))
const pageOffset = computed(() => (page.value - 1) * pageSize.value)
const visibleItems = computed(() => pageSlice(filtered.value, page.value, pageSize.value))
const initialLoading = computed(() => loading.value && items.value.length === 0)

watch([totalCount, pageSize], () => {
  page.value = clampPage(page.value, totalCount.value, pageSize.value)
})

const cards = computed(() =>
  visibleItems.value.map((item) => ({ item, src: item.缩略图 || null })),
)

const currentItem = computed<HairItem | null>(() => {
  const index = viewerIndex.value
  if (index === null) return null
  return filtered.value[index] ?? null
})

/** 当前灯箱条目是否就是第 4 槽已选发型（只按库 + id 匹配）。 */
const isExtraSelected = computed(() => {
  const item = currentItem.value
  const extra = draft.extra.value
  return Boolean(
    item && extra.source === 'library' && extra.library === 'hair' && extra.id === item.id,
  )
})

/** 灯箱主按钮文案：不可用于发型槽的条目明确说明原因。 */
const extraSelectLabel = computed(() =>
  currentItem.value?.可用于发型槽 === false ? '仅正面 · 不可加入第 4 槽' : '加入第 4 槽',
)

/**
 * 灯箱「加入第 4 槽」：与合成台共用同一份草稿；再点已选条目即移除。
 * 不可用于发型槽的条目（只有正面）直接拒绝，不写进草稿。
 */
function toggleExtraFromHair(): void {
  const item = currentItem.value
  if (!item) return
  if (!item.可用于发型槽) {
    toast.error(
      '无法加入第 4 槽。原因：该发型只有正面图，没有背面无脸图。下一步：选择标有「背面可用」的发型，或到合成台上传本地图。',
    )
    return
  }
  if (draft.extra.value.source === 'library' && draft.extra.value.id === item.id) {
    draft.clearExtra()
    toast.success('已从第 4 槽移除该发型')
    return
  }
  draft.setExtraLibrary('hair', item.id, item.标题)
  toast.success(`已将「${item.标题}」加入第 4 槽，提交时使用背面无脸图`)
}

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
  currentItem.value
    ? currentItem.value.原图 || currentItem.value.缩略图 || null
    : null,
)
const viewerCounter = computed(() => {
  const index = viewerIndex.value
  if (index === null) return ''
  return `${index + 1} / ${filtered.value.length}`
})
const viewerMeta = computed(() => {
  const item = currentItem.value
  if (!item) return []
  return [
    { label: '视图', value: item.视图 || '—' },
    { label: '分区', value: item.分区 || '—' },
    {
      label: '可用于第 4 槽',
      value: item.可用于发型槽 ? '是 · 使用背面无脸图' : '否 · 仅正面，仅浏览',
    },
    { label: '来源', value: '角色创作库 @62656456' },
  ]
})
const viewerDownloadName = computed(() =>
  currentItem.value ? `${currentItem.value.id}.webp` : '',
)

function onQueryInput(): void {
  page.value = 1
}

function onViewChange(): void {
  page.value = 1
}

function onGroupChange(): void {
  page.value = 1
}

function resetFilters(): void {
  view.value = ''
  group.value = ''
  query.value = ''
  page.value = 1
}

function onPageSizeChange(next: number): void {
  pageSize.value = next
  page.value = 1
  saveReferencePageSize(next)
}

function openViewer(index: number): void {
  viewerIndex.value = index
}

function closeViewer(): void {
  viewerIndex.value = null
}

function stepViewer(direction: number): void {
  const index = viewerIndex.value
  if (index === null || !filtered.value.length) return
  const length = filtered.value.length
  viewerIndex.value = (index + direction + length) % length
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="hair-tab">
    <header class="hair-head">
      <h1 class="hair-head__title tab-placeholder__title">发型库</h1>
      <p class="hair-head__hint">
        全量 489 款 · 正背双视图 311 款可拆出背面无脸图用于第 4 槽；点灯箱「加入第 4 槽」即可与合成台共用
      </p>
    </header>

    <template v-if="!initialLoading">
      <div class="hair-pills" role="group" aria-label="发型视图筛选">
        <button
          type="button"
          class="hair-pill"
          :class="{ 'is-active': view === '' }"
          :aria-pressed="view === ''"
          data-testid="hair-pill-all"
          @click="view = ''; onViewChange()"
        >
          全部发型 ({{ items.length }})
        </button>
        <button
          v-for="entry in viewOptions"
          :key="entry.value"
          type="button"
          class="hair-pill"
          :class="{ 'is-active': view === entry.value }"
          :aria-pressed="view === entry.value"
          :data-view="entry.value"
          @click="view = view === entry.value ? '' : entry.value; onViewChange()"
        >
          {{ entry.value }} ({{ entry.count }})
        </button>
      </div>

      <div class="hair-filters">
        <label class="hair-search">
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
            data-testid="hair-search"
            placeholder="搜索发型名称、分区或 ID（如：双团髻、法式辫、古风）…"
            aria-label="搜索发型"
            @input="onQueryInput"
          />
        </label>

        <select
          v-model="group"
          class="hair-select"
          data-testid="hair-group"
          aria-label="发型分区"
          @change="onGroupChange"
        >
          <option value="">全部分区（{{ groupOptions.length }}）</option>
          <option v-for="entry in groupOptions" :key="entry.value" :value="entry.value">
            {{ entry.value }} ({{ entry.count }})
          </option>
        </select>

        <button type="button" class="hair-reset" data-testid="hair-reset" @click="resetFilters">
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
      empty-title="没有找到匹配的发型参考"
      empty-hint="试试更换关键词或重置筛选"
      :skeleton-count="10"
      skeleton-aspect="3/4"
      @retry="retry"
      @update:page="page = $event"
      @update:page-size="onPageSizeChange"
    >
      <ReferenceCard
        v-for="(card, index) in cards"
        :key="card.item.id"
        data-testid="hair-card"
        :src="card.src"
        :title="card.item.标题"
        :alt="card.item.标题"
        :badge="card.item.分区"
        :angle="card.item.视图"
        aspect="3/4"
        fit="cover"
        meta-mono
        :meta-left="card.item.可用于发型槽 ? '背面可用' : '仅正面'"
        meta-right="角色创作库"
        @open="openViewer(pageOffset + index)"
      />
    </ReferenceGrid>

    <ReferenceLightbox
      :open="viewerOpen"
      :title="currentItem?.标题 ?? ''"
      :image-url="viewerImageUrl"
      :alt="currentItem ? `${currentItem.标题} · ${currentItem.视图}` : ''"
      :badge="currentItem?.分区"
      :angle="currentItem?.视图"
      :counter="viewerCounter"
      :meta-rows="viewerMeta"
      :download-name="viewerDownloadName"
      :copy-value="currentItem?.id ?? ''"
      copy-toast="已复制发型 ID"
      :selected="isExtraSelected"
      :select-label="extraSelectLabel"
      selected-label="已加入第 4 槽（点击移除）"
      :can-prev="filtered.length > 1"
      :can-next="filtered.length > 1"
      @toggle-select="toggleExtraFromHair"
      @close="closeViewer"
      @prev="stepViewer(-1)"
      @next="stepViewer(1)"
    />
  </div>
</template>

<style scoped>
.hair-tab {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.hair-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 16px;
}

.hair-head__title {
  margin: 0;
  color: var(--text-strong);
  font-size: 20px;
  font-weight: 600;
  line-height: 1.3;
}

.hair-head__hint {
  margin: 0;
  color: var(--text-muted);
  font-size: 13px;
}

.hair-pills {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 4px;
  scrollbar-width: none;
}

.hair-pills::-webkit-scrollbar {
  display: none;
}

@media (min-width: 640px) {
  .hair-pills {
    flex-wrap: wrap;
    padding-bottom: 0;
  }
}

.hair-pill {
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
  cursor: pointer;
}

.hair-pill.is-active {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
}

.hair-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin: 12px 0 16px;
}

.hair-search {
  display: flex;
  flex: 1 1 280px;
  align-items: center;
  gap: 8px;
  min-width: 220px;
  height: 40px;
  padding: 0 14px;
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  background: var(--surface-panel);
  color: var(--text-muted);
}

.hair-search svg {
  width: 16px;
  height: 16px;
  flex: none;
}

.hair-search input {
  width: 100%;
  border: 0;
  background: transparent;
  color: var(--text-strong);
  font-size: 14px;
  outline: none;
}

.hair-select {
  height: 40px;
  padding: 0 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  background: var(--surface-panel);
  color: var(--text-strong);
  font-size: 14px;
}

.hair-reset {
  height: 40px;
  padding: 0 16px;
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  background: var(--surface-panel);
  color: var(--text-muted);
  font-size: 14px;
  cursor: pointer;
}

.hair-reset:hover {
  color: var(--text-strong);
}
</style>