<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'

import Lightbox from '../components/Lightbox.vue'
import TagCloud from '../components/TagCloud.vue'
import { apiGet, apiPost, thumbnailUrl } from '../api/client'
import type { HistoryItem, HistoryPage, TagRow } from '../api/types'
import { formatSize, resolution } from '../utils/format'

const pageSize = 60
const page = ref(1)
const search = ref('')
const selectedTags = ref<number[]>([])
const tagMatch = ref<'all' | 'any'>('all')
const onlyMissing = ref(false)

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
])

const {
  data: history,
  isFetching,
  isError,
  error,
} = useQuery<HistoryPage>({
  queryKey: historyKey,
  queryFn: () =>
    apiGet<HistoryPage>('/api/history', {
      page: page.value,
      page_size: pageSize,
      tag_ids: selectedTags.value.join(','),
      tag_match: tagMatch.value,
      missing: onlyMissing.value ? 1 : undefined,
      search: search.value.trim(),
    }),
  // 翻页时保留上一页内容，避免整页闪烁
  placeholderData: (prev) => prev,
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
const selectedCount = computed(() => selected.value.size)
const allOnPageSelected = computed(
  () => items.value.length > 0 && items.value.every((it) => selected.value.has(it.id)),
)

function toggleSelect(id: number) {
  if (selected.value.has(id)) selected.value.delete(id)
  else selected.value.add(id)
  // 触发响应式：Set 的增删不会自动让 size 计算属性更新
  selected.value = new Set(selected.value)
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

const lightboxIndex = ref<number | null>(null)
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

        <div v-if="!items.length && !isFetching" class="empty big">没有符合条件的图片</div>
      </div>
    </section>

    <Lightbox
      v-if="lightboxOpen"
      :items="items"
      :index="lightboxIndex!"
      @update:index="lightboxIndex = $event"
      @close="lightboxIndex = null"
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
