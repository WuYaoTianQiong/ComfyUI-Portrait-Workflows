<script setup lang="ts">
import { computed, ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'

import { apiGet, thumbnailUrl } from '../api/client'
import type { HistoryItem, HistoryPage, TagRow } from '../api/types'

const pageSize = 60
const page = ref(1)
const search = ref('')
const selectedTags = ref<number[]>([])
const tagMatch = ref<'all' | 'any'>('all')
const onlyMissing = ref(false)

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

/** 只展示"确实有图"的标签；已选中的即使计数为 0 也保留，否则取消不掉。 */
const visibleTags = computed<TagRow[]>(() =>
  (tagData.value?.tags ?? []).filter(
    (t) => t.prompt_count > 0 || selectedTags.value.includes(t.id),
  ),
)

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

function formatSize(bytes?: number): string {
  if (!bytes) return ''
  return bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.round(bytes / 1024)} KB`
}

function resolution(item: HistoryItem): string {
  return item.width && item.height ? `${item.width}×${item.height}` : ''
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

        <div class="mode-switch">
          <button
            class="btn btn-sm"
            :class="{ active: tagMatch === 'all' }"
            title="选中的标签必须同时满足"
            @click="setTagMatch('all')"
          >
            全部满足
          </button>
          <button
            class="btn btn-sm"
            :class="{ active: tagMatch === 'any' }"
            title="满足任意一个标签即可"
            @click="setTagMatch('any')"
          >
            任一满足
          </button>
        </div>

        <div class="tag-cloud">
          <button
            v-for="tag in visibleTags"
            :key="tag.id"
            class="tag"
            :class="{ active: selectedTags.includes(tag.id) }"
            :style="{ '--c': tag.color }"
            @click="toggleTag(tag.id)"
          >
            {{ tag.name }}<i>{{ tag.prompt_count }}</i>
          </button>
          <div v-if="!visibleTags.length" class="empty">暂无带图片的标签</div>
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
        <div class="pager">
          <button class="btn btn-sm" :disabled="page <= 1" @click="page--">上一页</button>
          <span class="page-num">{{ page }} / {{ totalPages }}</span>
          <button class="btn btn-sm" :disabled="page >= totalPages" @click="page++">
            下一页
          </button>
        </div>
      </div>

      <div v-if="isError" class="error">加载失败：{{ error?.message }}</div>

      <div v-else class="grid">
        <article
          v-for="item in items"
          :key="item.id"
          class="card"
          :class="{ missing: item.missing }"
          :title="item.missing ? '磁盘上找不到这个文件（勾选「只看文件缺失」可批量清理记录）' : item.filename"
        >
          <img :src="thumbnailUrl(item)" :alt="item.filename" loading="lazy" />
          <span v-if="item.missing" class="badge-missing">🚫 文件缺失</span>
          <span v-if="item.favorite" class="badge-fav">★</span>
          <div class="meta">
            <span>{{ resolution(item) }}</span>
            <span>{{ formatSize(item.file_size) }}</span>
          </div>
          <div class="filename">{{ item.filename }}</div>
        </article>

        <div v-if="!items.length && !isFetching" class="empty big">没有符合条件的图片</div>
      </div>
    </section>
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

.mode-switch {
  display: flex;
  gap: var(--gap-xs);
  margin-bottom: var(--gap-sm);
}

.mode-switch .btn {
  flex: 1;
  font-size: var(--fs-xs);
}

.tag-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tag {
  font-size: var(--fs-sm);
  padding: 3px 9px;
  border-radius: 999px;
  border: 1px solid var(--c, var(--border));
  background: transparent;
  color: var(--text);
  transition: 0.12s;
}

.tag:hover {
  background: color-mix(in srgb, var(--c) 18%, transparent);
}

.tag.active {
  background: var(--c);
  border-color: var(--c);
  color: #fff;
}

.tag i {
  font-style: normal;
  font-size: var(--fs-xs);
  opacity: 0.8;
  margin-left: 4px;
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

.badge-fav {
  position: absolute;
  top: 6px;
  left: 8px;
  color: #fbbf24;
  font-size: var(--fs-lg);
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.8);
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
