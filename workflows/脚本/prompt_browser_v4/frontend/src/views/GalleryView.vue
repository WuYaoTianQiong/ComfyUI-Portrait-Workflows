<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'

import Lightbox from '../components/Lightbox.vue'
import CompareModal from '../components/CompareModal.vue'
import TagCloud from '../components/TagCloud.vue'
import { apiGet, apiPost, thumbnailUrl } from '../api/client'
import EmptyState from '../components/EmptyState.vue'
import { useToast } from '../composables/useToast'
import { useWorkflows } from '../composables/useWorkflows'
import type { HistoryItem, HistoryPage, TagRow } from '../api/types'
import { formatSize, resolution } from '../utils/format'

const pageSize = 60
const page = ref(1)
const search = ref('')
const selectedTags = ref<number[]>([])
const tagMatch = ref<'all' | 'any'>('all')
const onlyMissing = ref(false)

// 分面筛选（来源 / 年月 / 模型 / 方向）—— 每个维度单选，再点一次取消
const source = ref('')
const dateFacet = ref('')
const model = ref('')
const orientation = ref('')

const queryClient = useQueryClient()

/**
 * 列表状态全部收敛成"一个缓存键"。
 *
 * 旧前端把分页/筛选/排序拆在十几个 `window._galleryXxx` 裸变量里，
 * 任何一处漏同步就是"筛选筛了、全选选到范围外"。这里键变了就重查，
 * 键没变就用缓存，不存在两边不同步的可能。
 */
const historyKey = computed(() => [
  'history',
  page.value,
  pageSize,
  selectedTags.value.slice().sort((a, b) => a - b).join(','),
  tagMatch.value,
  onlyMissing.value,
  search.value.trim(),
  source.value,
  dateFacet.value,
  model.value,
  orientation.value,
])

/** 列表与「全选全部」共用的筛选参数（后者不需要分页参数）。 */
function historyFilterParams() {
  return {
    page: page.value,
    page_size: pageSize,
    tag_ids: selectedTags.value.join(','),
    tag_match: tagMatch.value,
    missing: onlyMissing.value ? 1 : undefined,
    search: search.value.trim(),
    source: source.value,
    date: dateFacet.value,
    model: model.value,
    orientation: orientation.value,
  }
}
/** 列表与分面共用的筛选参数（不含分面维度自身 —— 后端就是按这个口径算的）。 */
const facetScope = computed(() => ({
  search: search.value.trim(),
  tag_ids: selectedTags.value.join(','),
  tag_match: tagMatch.value,
  missing: onlyMissing.value ? 1 : undefined,
}))

const {
  data: history,
  isFetching,
  isError,
  error,
} = useQuery<HistoryPage>({
  queryKey: historyKey,
  queryFn: () => apiGet<HistoryPage>('/api/history', historyFilterParams()),
  // 翻页时保留上一页内容，避免整页闪烁
  placeholderData: (prev) => prev,
})

interface Facets {
  source: Record<string, number>
  date: Record<string, number>
  model: Record<string, number>
  orientation: Record<string, number>
}

/** 分面计数：后端按「当前筛选（不含分面维度自身）」算，避免「数出来的和筛出来的对不上」。 */
const { data: facets } = useQuery<Facets>({
  queryKey: computed(() => ['facets', facetScope.value]),
  queryFn: () => apiGet('/api/history/facets', facetScope.value),
  placeholderData: (prev) => prev,
  staleTime: 15_000,
})

const { data: tagData } = useQuery<{ tags: TagRow[] }>({
  queryKey: ['tags', 'image'],
  queryFn: () => apiGet<{ tags: TagRow[] }>('/api/tags', { count_scope: 'image' }),
})

const items = computed<HistoryItem[]>(() => history.value?.items ?? [])
const total = computed(() => history.value?.total ?? 0)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

// ---------------- 选择与批量操作 ----------------

const selected = ref<Set<number>>(new Set())
const selectingAll = ref(false)
const selectedCount = computed(() => selected.value.size)

function toggleSelect(id: number) {
  if (selected.value.has(id)) selected.value.delete(id)
  else selected.value.add(id)
  // 触发响应式：Set 的增删不会自动让 size 计算属性更新
  selected.value = new Set(selected.value)
}

/**
 * 全选全部：跨页把当前筛选下的所有记录都选上。
 *
 * 后端 `/api/history/ids` 不分页，返回当前筛选下的全部 id —— 旧前端的"全选全部"
 * 就是这个语义，新前端之前只支持"全选本页"，批量删除时得翻页累加。
 */
async function selectAllMatching() {
  selectingAll.value = true
  try {
    const data = await apiGet<{ ids: number[]; total: number }>(
      '/api/history/ids',
      historyFilterParams(),
    )
    selected.value = new Set(data.ids)
    if (!data.ids.length) toast.info('当前筛选下没有可选的图片')
  } catch (e) {
    toast.error(`全选失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    selectingAll.value = false
  }
}
function selectAllOnPage() {
  selected.value = new Set(items.value.map((it) => it.id))
}

function clearSelection() {
  selected.value = new Set()
}

const deleteMutation = useMutation({
  mutationFn: (ids: number[]) =>
    apiPost<{ success: boolean; deleted: number }>('/api/history/batch_delete', { ids }),
  onSuccess: () => {
    clearSelection()
    queryClient.invalidateQueries({ queryKey: ['history'] })
  },
})

const favoriteMutation = useMutation({
  mutationFn: (id: number) => apiPost<{ success: boolean; favorite: boolean }>(`/api/history/${id}/favorite`),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ['history'] }),
})

function batchDelete() {
  const ids = Array.from(selected.value)
  if (!ids.length) return
  if (!confirm(`确定删除选中的 ${ids.length} 张图片记录吗？（只标记删除，不动磁盘文件）`)) return
  deleteMutation.mutate(ids)
}

function batchDownload() {
  const targets = items.value.filter((it) => selected.value.has(it.id))
  if (!targets.length) return
  // 浏览器对并发下载有限制，逐个触发并留间隔
  targets.forEach((item, i) => {
    setTimeout(() => window.open(`/api/history/${item.id}/download`, '_blank'), i * 400)
  })
}

// ---------------- 灯箱 ----------------


/**
 * 多图对比：选中 2~4 张后打开对比弹层。
 *
 * 上限 4 张是旧版沿用的限制 —— 再多就没法看了，用户也不需要。
 */
const compareOpen = ref(false)

const compareItems = computed<HistoryItem[]>(() =>
  items.value.filter((it) => selected.value.has(it.id)),
)

function openCompare() {
  if (selected.value.size < 2) {
    toast.info('至少选择 2 张图片才能对比')
    return
  }
  if (selected.value.size > 4) {
    toast.error('对比最多只能选择 4 张图片，请取消部分选择')
    return
  }
  compareOpen.value = true
}
const lightboxIndex = ref<number | null>(null)

/** 灯箱里要能直接选工作流（投喂给工作流处理）。 */
const { workflows } = useWorkflows()
const lightboxOpen = computed(() => lightboxIndex.value !== null)

function openLightbox(index: number) {
  lightboxIndex.value = index
}

// ---------------- 筛选 ----------------

function toggleTag(id: number) {
  const idx = selectedTags.value.indexOf(id)
  if (idx >= 0) selectedTags.value.splice(idx, 1)
  else selectedTags.value.push(id)
  page.value = 1
}

function setTagMatch(mode: 'all' | 'any') {
  if (tagMatch.value === mode) return
  tagMatch.value = mode
  page.value = 1
}

function toggleMissing() {
  onlyMissing.value = !onlyMissing.value
  page.value = 1
}

// ---------------- 清理失效 ----------------

const toast = useToast()
const cleaning = ref(false)

interface CleanupPreview {
  success: boolean
  dry_run: boolean
  total: number
  will_clean: number
  samples: Array<{ id: number; filename: string; subfolder: string; img_type: string }>
  guarded: boolean
  message: string
}

/**
 * 清理范围 = 当前筛选，但**刻意不传 missing**。
 *
 * 「只看文件缺失」是"看待清理的清单"，不是"清理范围"；带上它预览恒为 0，
 * 用户会以为功能坏了。
 */
function cleanupScope() {
  return {
    search: search.value.trim(),
    tag_ids: selectedTags.value.join(','),
    tag_match: tagMatch.value,
  }
}

/**
 * 两段式：先预览再执行。
 *
 * 后端默认 dry_run，只返回"将清理多少条 + 样本"，不写库；执行要显式带
 * dry_run=false&confirm=true。缺失占比过半时后端会熔断拒绝（路径解析异常时
 * 一键清空整库是历史事故的根源）。
 */
async function cleanupMissing() {
  if (cleaning.value) return
  cleaning.value = true
  try {
    const preview = await apiPost<CleanupPreview>(
      '/api/history/cleanup_missing',
      undefined,
      { ...cleanupScope(), dry_run: true },
    )

    if (preview.guarded) {
      toast.error(preview.message || '疑似路径异常，已阻止清理')
      return
    }
    if (!preview.will_clean) {
      toast.info(`扫描 ${preview.total} 条记录，文件均存在，无需清理`)
      return
    }

    const samples = preview.samples
      .map((s) => `  · ${s.subfolder ? s.subfolder + '/' : ''}${s.filename}`)
      .join('\n')
    const more = preview.will_clean > 10 ? `\n  … 另有 ${preview.will_clean - 10} 条` : ''
    const allMissing = preview.total > 0 && preview.will_clean === preview.total
    const warn = allMissing
      ? '\n\n⚠ 当前筛选下的记录会【全部】失效，请先确认 ComfyUI output 目录可正常访问。'
      : ''

    const ok = confirm(
      `扫描 ${preview.total} 条记录，其中 ${preview.will_clean} 条的文件已不存在：\n\n` +
        `${samples}${more}${warn}` +
        '\n\n这一步只把记录标记为已删除，不动磁盘文件。确认继续？',
    )
    if (!ok) return

    const data = await apiPost<CleanupPreview & { cleaned: number }>(
      '/api/history/cleanup_missing',
      undefined,
      { ...cleanupScope(), dry_run: false, confirm: true },
    )
    if (!data.success) {
      toast.error(data.message || '清理未执行')
      return
    }
    toast.success(`已清理 ${data.cleaned} 条失效记录（共扫描 ${data.total} 条）`)
    queryClient.invalidateQueries({ queryKey: ['history'] })
  } catch (e) {
    toast.error(`清理失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    cleaning.value = false
  }
}

/** 分面维度定义（每个维度单选，再点一次取消）。 */
const facetDimDefs = [
  { key: 'source' as const, label: '来源' },
  { key: 'date' as const, label: '年月' },
  { key: 'model' as const, label: '模型' },
  { key: 'orientation' as const, label: '方向' },
]

/** 分面值可能很长（模型名是一整个 safetensors 文件名），截断显示但保留完整 title。 */
function facetLabel(name: string): string {
  return name.length > 20 ? name.slice(0, 19) + '…' : name
}
function facetValue(key: 'source' | 'date' | 'model' | 'orientation'): string {
  return {
    source: source.value,
    date: dateFacet.value,
    model: model.value,
    orientation: orientation.value,
  }[key]
}

function toggleFacet(key: 'source' | 'date' | 'model' | 'orientation', value: string) {
  const targets = { source, date: dateFacet, model, orientation }
  const target = targets[key]
  target.value = target.value === value ? '' : value
  page.value = 1
}
function clearFilters() {
  selectedTags.value = []
  tagMatch.value = 'all'
  onlyMissing.value = false
  search.value = ''
  page.value = 1
}
</script>

<template>
  <div class="gallery">
    <aside class="sidebar">
      <section class="group">
        <div class="group-head">
          <span>标签</span>
          <button
            v-if="selectedTags.length"
            class="btn btn-sm clear"
            @click="selectedTags = []; page = 1"
          >
            清空 ({{ selectedTags.length }})
          </button>
        </div>

        <TagCloud
          :tags="tagData?.tags ?? []"
          :selected="selectedTags"
          :match="tagMatch"
          empty-text="暂无带图片的标签"
          @toggle="toggleTag"
          @update:match="setTagMatch"
        />
      </section>

      <section v-for="dim in facetDimDefs" :key="dim.key" class="group">
        <div class="group-head"><span>{{ dim.label }}</span></div>
        <div class="chips">
          <button
            v-for="(count, name) in facets?.[dim.key] ?? {}"
            :key="name"
            class="chip" :title="String(name)"
            :class="{ active: facetValue(dim.key) === name }"
            @click="toggleFacet(dim.key, String(name))"
          >
            {{ facetLabel(String(name)) }}<i>{{ count }}</i>
          </button>
          <EmptyState v-if="!Object.keys(facets?.[dim.key] ?? {}).length" text="无" />
        </div>
      </section>
      <section class="group">
        <div class="group-head"><span>状态</span></div>
        <label class="check">
          <input type="checkbox" :checked="onlyMissing" @change="toggleMissing" />
          <span>只看文件缺失</span>
        </label>
        <button class="btn btn-sm full" @click="clearFilters">清除全部筛选</button>
      </section>
    </aside>

    <section class="main">
      <div class="toolbar">
        <input
          v-model="search"
          class="search"
          type="search"
          placeholder="搜索文件名 / 提示词名称…"
          @input="page = 1"
        />
        <span class="count">
          共 <b>{{ total }}</b> 张
          <span v-if="isFetching" class="fetching">加载中…</span>
        </span>
        <span class="spacer" />
        <button
          class="btn btn-sm"
          :disabled="selectingAll"
          title="选中当前筛选下的全部图片（跨页）"
          @click="selectAllMatching"
        >
          全选全部 {{ total }} 张
        </button>
        <button
          class="btn btn-sm"
          :disabled="cleaning"
          title="扫描当前筛选下的记录，先预览再确认；只标记不动磁盘文件"
          @click="cleanupMissing"
        >
          🧹 清理失效
        </button>
        <div class="pager">
          <button class="btn btn-sm" :disabled="page <= 1" @click="page--">上一页</button>
          <span class="page-num">{{ page }} / {{ totalPages }}</span>
          <button class="btn btn-sm" :disabled="page >= totalPages" @click="page++">
            下一页
          </button>
        </div>
      </div>

      <div v-if="selectedCount" class="bulk">
        <span class="bulk-count">已选 <b>{{ selectedCount }}</b> 张</span>
        <button class="btn btn-sm" @click="selectAllOnPage">全选本页</button>
        <button class="btn btn-sm" @click="clearSelection">取消选择</button>
        <span class="spacer" />
        <button class="btn btn-sm" @click="openCompare">对比</button>
        <button class="btn btn-sm" @click="batchDownload">下载选中</button>
        <button class="btn btn-sm danger" :disabled="deleteMutation.isPending.value" @click="batchDelete">
          {{ deleteMutation.isPending.value ? '删除中…' : '删除选中' }}
        </button>
      </div>

      <div v-if="isError" class="error">加载失败：{{ error?.message }}</div>

      <div v-else class="grid">
        <article
          v-for="(item, idx) in items"
          :key="item.id"
          class="card"
          :class="{ missing: item.missing, picked: selected.has(item.id) }"
          :title="item.missing ? '磁盘上找不到这个文件（勾选「只看文件缺失」可批量清理记录）' : item.filename"
          @click="openLightbox(idx)"
        >
          <img :src="thumbnailUrl(item)" :alt="item.filename" loading="lazy" />

          <button
            class="pick"
            :class="{ on: selected.has(item.id) }"
            :title="selected.has(item.id) ? '取消选择' : '选择'"
            @click.stop="toggleSelect(item.id)"
          >
            ✓
          </button>

          <button
            class="fav"
            :class="{ on: item.favorite }"
            title="收藏"
            @click.stop="favoriteMutation.mutate(item.id)"
          >
            {{ item.favorite ? '★' : '☆' }}
          </button>

          <span v-if="item.missing" class="badge-missing">🚫 文件缺失</span>

          <div class="meta">
            <span>{{ resolution(item) }}</span>
            <span>{{ formatSize(item.file_size) }}</span>
          </div>
          <div class="filename">{{ item.filename }}</div>
        </article>

        <EmptyState v-if="!items.length && !isFetching" size="big" text="没有符合条件的图片" />
      </div>
    </section>

    <Lightbox
      v-if="lightboxOpen"
      :items="items"
      :index="lightboxIndex!"
      :workflows="workflows"
      @update:index="lightboxIndex = $event"
      @close="lightboxIndex = null"
      @changed="queryClient.invalidateQueries({ queryKey: ['history'] })"
    />

    <CompareModal
      :open="compareOpen"
      :items="compareItems"
      @close="compareOpen = false"
    />
  </div>
</template>

<style scoped>
.gallery {
  display: flex;
  height: 100%;
  min-height: 0;
}

.sidebar {
  width: 240px;
  flex: none;
  border-right: 1px solid var(--border);
  background: var(--panel);
  padding: var(--gap);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--gap-lg);
}

.group-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--fs-sm);
  color: var(--muted);
  margin-bottom: var(--gap-sm);
}

.clear {
  font-size: var(--fs-xs);
  padding: 1px 6px;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.chip {
  font-size: var(--fs-xs);
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--muted);
  transition: 0.12s;
}

.chip:hover {
  border-color: var(--border-strong);
  color: var(--text);
}

.chip.active {
  background: var(--primary-soft);
  border-color: var(--primary);
  color: var(--primary);
}

.chip i {
  font-style: normal;
  opacity: 0.7;
  margin-left: 3px;
}
.check {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-size: var(--fs-sm);
  margin-bottom: var(--gap-sm);
  cursor: pointer;
}

.full {
  width: 100%;
}

.main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: var(--gap);
  padding: var(--gap) var(--gap-lg);
  border-bottom: 1px solid var(--border);
}

.search {
  width: 260px;
}

.count {
  font-size: var(--fs-sm);
  color: var(--muted);
}

.count b {
  color: var(--text);
}

.fetching {
  margin-left: var(--gap-sm);
  color: var(--primary);
}

.spacer {
  flex: 1;
}

.pager {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
}

.page-num {
  font-size: var(--fs-sm);
  color: var(--muted);
  min-width: 62px;
  text-align: center;
}

.bulk {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm) var(--gap-lg);
  background: var(--primary-soft);
  border-bottom: 1px solid var(--border);
  font-size: var(--fs-sm);
}

.bulk-count b {
  color: var(--primary);
}

.btn.danger {
  border-color: var(--danger);
  color: #fecaca;
}

.btn.danger:hover {
  background: var(--danger-soft);
}

.grid {
  flex: 1;
  overflow-y: auto;
  padding: var(--gap-lg);
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: var(--gap);
  align-content: start;
}

.card {
  position: relative;
  border-radius: var(--radius);
  overflow: hidden;
  background: var(--panel-2);
  border: 1px solid var(--border);
  transition: 0.15s;
  cursor: pointer;
}

.card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-sm);
  border-color: var(--border-strong);
}

.card.picked {
  border-color: var(--primary);
  box-shadow: 0 0 0 1px var(--primary);
}

.card img {
  display: block;
  width: 100%;
  aspect-ratio: 3 / 4;
  /* contain 而非 cover：这是看图工具，裁掉画面比留黑边严重得多 */
  object-fit: contain;
  background: var(--panel-3);
}

.card.missing img {
  opacity: 0.35;
  filter: grayscale(1);
}

.pick {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 20px;
  height: 20px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  border: 1px solid var(--border-strong);
  background: rgba(22, 27, 34, 0.8);
  color: transparent;
  font-size: var(--fs-xs);
  opacity: 0;
  transition: 0.12s;
}

.card:hover .pick,
.pick.on {
  opacity: 1;
}

.pick.on {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}

.fav {
  position: absolute;
  top: 4px;
  left: 6px;
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: var(--fs-lg);
  line-height: 1;
  opacity: 0;
  transition: 0.12s;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.8);
}

.card:hover .fav,
.fav.on {
  opacity: 1;
}

.fav.on {
  color: #fbbf24;
}

.badge-missing {
  position: absolute;
  top: 8px;
  left: 50%;
  transform: translateX(-50%);
  padding: 2px 9px;
  border-radius: 999px;
  background: var(--danger-soft);
  color: #fecaca;
  font-size: var(--fs-xs);
  font-weight: 600;
  white-space: nowrap;
}

.meta {
  position: absolute;
  bottom: 26px;
  left: 0;
  right: 0;
  display: flex;
  gap: var(--gap-sm);
  padding: 2px 8px;
  font-size: var(--fs-xs);
  color: #dbe3ea;
  background: linear-gradient(transparent, rgba(0, 0, 0, 0.65));
}

.filename {
  padding: 4px 8px;
  font-size: var(--fs-xs);
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.empty {
  font-size: var(--fs-sm);
  color: var(--muted);
}

.empty.big {
  grid-column: 1 / -1;
  padding: 60px;
  text-align: center;
}

.error {
  margin: var(--gap-lg);
  padding: var(--gap);
  border-radius: var(--radius);
  border: 1px solid var(--danger);
  color: #fecaca;
  background: var(--danger-soft);
}
</style>
