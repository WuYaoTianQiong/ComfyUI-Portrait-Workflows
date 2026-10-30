<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'

import TagCloud from '../components/TagCloud.vue'
import { apiGet, apiPost, apiPut } from '../api/client'
import type { CategoryNode, PromptDetail, PromptListPage, TagRow } from '../api/types'

const pageSize = 50
const page = ref(1)
const search = ref('')
const categoryId = ref<number | null>(null)
const tagIds = ref<number[]>([])
const tagMatch = ref<'all' | 'any'>('all')
const selectedId = ref<number | null>(null)

const queryClient = useQueryClient()

const listKey = computed(() => [
  'prompts',
  page.value,
  search.value.trim(),
  categoryId.value,
  tagIds.value.slice().sort((a, b) => a - b).join(','),
  tagMatch.value,
])

const { data: listData, isFetching } = useQuery<PromptListPage>({
  queryKey: listKey,
  queryFn: () =>
    apiGet<PromptListPage>('/api/prompts', {
      page: page.value,
      page_size: pageSize,
      search: search.value.trim(),
      category_id: categoryId.value ?? undefined,
      tag_ids: tagIds.value.join(','),
      tag_match: tagMatch.value,
    }),
  placeholderData: (prev) => prev,
})

const list = computed(() => listData.value?.prompts ?? [])
const total = computed(() => listData.value?.total ?? 0)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

const { data: catData } = useQuery<{ categories: CategoryNode[] }>({
  queryKey: ['categories', 'prompt'],
  queryFn: () =>
    apiGet<{ categories: CategoryNode[] }>('/api/categories', {
      tree: true,
      count_scope: 'prompt',
    }),
})

const { data: tagData } = useQuery<{ tags: TagRow[] }>({
  queryKey: ['tags', 'prompt'],
  queryFn: () => apiGet<{ tags: TagRow[] }>('/api/tags', { count_scope: 'prompt' }),
})

/** 树拍平成一维，带 depth 做缩进 —— 分类层级只有两级，递归组件是过度设计。 */
const flatCats = computed(() => {
  const out: Array<CategoryNode & { depth: number }> = []
  const walk = (nodes: CategoryNode[], depth: number) => {
    nodes.forEach((node) => {
      out.push({ ...node, depth })
      if (node.children?.length) walk(node.children, depth + 1)
    })
  }
  walk(catData.value?.categories ?? [], 0)
  return out
})

// ---------------- 详情 ----------------

const { data: detail } = useQuery<PromptDetail>({
  queryKey: computed(() => ['prompt', selectedId.value]),
  queryFn: () => apiGet<PromptDetail>(`/api/prompts/${selectedId.value}`),
  enabled: computed(() => selectedId.value !== null),
})

const draft = ref<PromptDetail | null>(null)
watch(
  detail,
  (value) => {
    draft.value = value ? { ...value } : null
  },
  { immediate: true },
)

/** 列表变化后保证"总有一条被选中"，避免右侧空着。 */
watch(
  list,
  (items) => {
    if (!items.length) return
    if (selectedId.value === null || !items.some((it) => it.id === selectedId.value)) {
      selectedId.value = items[0].id
    }
  },
  { immediate: true },
)

const dirty = computed(() => {
  if (!draft.value || !detail.value) return false
  return (
    draft.value.name !== detail.value.name ||
    draft.value.tags !== detail.value.tags ||
    draft.value.prompt !== detail.value.prompt ||
    draft.value.negative_prompt !== detail.value.negative_prompt ||
    draft.value.note !== detail.value.note
  )
})

function invalidateAll(id: number | null) {
  queryClient.invalidateQueries({ queryKey: ['prompts'] })
  if (id !== null) queryClient.invalidateQueries({ queryKey: ['prompt', id] })
  queryClient.invalidateQueries({ queryKey: ['tags'] })
}

const saveMutation = useMutation({
  mutationFn: (payload: Partial<PromptDetail>) =>
    apiPut<{ success: boolean }>(`/api/prompts/${selectedId.value}`, payload),
  onSuccess: () => invalidateAll(selectedId.value),
})

function save() {
  if (!draft.value) return
  saveMutation.mutate({
    name: draft.value.name,
    tags: draft.value.tags,
    prompt: draft.value.prompt,
    negative_prompt: draft.value.negative_prompt,
    note: draft.value.note,
  })
}

function revert() {
  draft.value = detail.value ? { ...detail.value } : null
}

const favoriteMutation = useMutation({
  mutationFn: () => apiPost(`/api/prompts/${selectedId.value}/favorite`),
  onSuccess: () => invalidateAll(selectedId.value),
})

const pinMutation = useMutation({
  mutationFn: () => apiPost(`/api/prompts/${selectedId.value}/pin`),
  onSuccess: () => invalidateAll(selectedId.value),
})

const rateMutation = useMutation({
  mutationFn: (rating: number) =>
    apiPost(`/api/prompts/${selectedId.value}/rate`, undefined, { rating }),
  onSuccess: () => invalidateAll(selectedId.value),
})

// ---------------- 筛选 ----------------

function selectCategory(id: number | null) {
  categoryId.value = id
  page.value = 1
}

function toggleTag(id: number) {
  const idx = tagIds.value.indexOf(id)
  if (idx >= 0) tagIds.value.splice(idx, 1)
  else tagIds.value.push(id)
  page.value = 1
}

function clearFilters() {
  search.value = ''
  categoryId.value = null
  tagIds.value = []
  tagMatch.value = 'all'
  page.value = 1
}
</script>

<template>
  <div class="prompt-page">
    <aside class="filters">
      <section class="group">
        <div class="group-head">
          <span>分类</span>
          <button class="btn btn-sm" @click="selectCategory(null)">全部</button>
        </div>
        <div class="cat-list">
          <button
            v-for="cat in flatCats"
            :key="cat.id"
            class="cat"
            :class="{ active: categoryId === cat.id }"
            :style="{ paddingLeft: `${8 + cat.depth * 14}px` }"
            @click="selectCategory(cat.id)"
          >
            <span class="dot" :style="{ background: cat.color }" />
            <span class="cat-name">{{ cat.name }}</span>
            <i>{{ cat.prompt_count }}</i>
          </button>
          <div v-if="!flatCats.length" class="empty">暂无分类</div>
        </div>
      </section>

      <section class="group">
        <div class="group-head">
          <span>标签</span>
          <button
            v-if="tagIds.length"
            class="btn btn-sm"
            @click="tagIds = []; page = 1"
          >
            清空 ({{ tagIds.length }})
          </button>
        </div>
        <TagCloud
          :tags="tagData?.tags ?? []"
          :selected="tagIds"
          :match="tagMatch"
          empty-text="暂无带提示词的标签"
          @toggle="toggleTag"
          @update:match="(m) => { tagMatch = m; page = 1 }"
        />
      </section>

      <button class="btn btn-sm full" @click="clearFilters">清除全部筛选</button>
    </aside>

    <section class="list-pane">
      <div class="list-head">
        <input
          v-model="search"
          class="search"
          type="search"
          placeholder="搜索名称 / 内容 / 标签…"
          @input="page = 1"
        />
        <span class="count">{{ total }} 条<span v-if="isFetching"> · 加载中</span></span>
      </div>

      <div class="list">
        <button
          v-for="item in list"
          :key="item.id"
          class="row"
          :class="{ active: selectedId === item.id }"
          @click="selectedId = item.id"
        >
          <div class="row-title">
            <span v-if="item.is_pinned" class="pin" title="置顶">📌</span>
            <span v-if="item.is_favorite" class="star" title="收藏">★</span>
            <span class="name">{{ item.name || `#${item.id}` }}</span>
            <span v-if="item.rating" class="rating">{{ '★'.repeat(item.rating) }}</span>
          </div>
          <div class="row-preview">{{ item.prompt_preview }}</div>
          <div v-if="item.tags" class="row-tags">{{ item.tags }}</div>
        </button>

        <div v-if="!list.length && !isFetching" class="empty big">没有符合条件的提示词</div>
      </div>

      <div class="pager">
        <button class="btn btn-sm" :disabled="page <= 1" @click="page--">上一页</button>
        <span class="page-num">{{ page }} / {{ totalPages }}</span>
        <button class="btn btn-sm" :disabled="page >= totalPages" @click="page++">下一页</button>
      </div>
    </section>

    <section class="detail-pane">
      <div v-if="!draft" class="empty big">选择左侧任意一条提示词</div>

      <div v-else class="detail">
        <header class="detail-head">
          <input v-model="draft.name" class="name-input" placeholder="未命名" />
          <button
            class="btn btn-sm"
            :class="{ active: draft.is_favorite }"
            title="收藏"
            @click="favoriteMutation.mutate()"
          >
            {{ draft.is_favorite ? '★ 已收藏' : '☆ 收藏' }}
          </button>
          <button
            class="btn btn-sm"
            :class="{ active: draft.is_pinned }"
            title="置顶"
            @click="pinMutation.mutate()"
          >
            📌
          </button>
        </header>

        <div class="stars">
          <span class="label">评级</span>
          <button
            v-for="n in 5"
            :key="n"
            class="star-btn"
            :class="{ on: (draft.rating ?? 0) >= n }"
            @click="rateMutation.mutate(n)"
          >
            ★
          </button>
          <span class="meta">使用 {{ draft.usage_count }} 次 · 更新 {{ draft.updated_at.slice(0, 16) }}</span>
        </div>

        <label class="field">
          <span>标签（逗号分隔，保存后自动同步到标签库）</span>
          <input v-model="draft.tags" />
        </label>

        <label class="field grow">
          <span>正向提示词</span>
          <textarea v-model="draft.prompt" spellcheck="false" />
        </label>

        <label class="field">
          <span>负向提示词</span>
          <textarea v-model="draft.negative_prompt" spellcheck="false" class="small" />
        </label>

        <label class="field">
          <span>备注</span>
          <input v-model="draft.note" />
        </label>

        <footer class="detail-foot">
          <span v-if="dirty" class="dirty">有未保存的修改</span>
          <span v-else class="saved">已保存</span>
          <span class="spacer" />
          <button class="btn btn-sm" :disabled="!dirty" @click="revert">撤销</button>
          <button class="btn btn-sm primary" :disabled="!dirty || saveMutation.isPending.value" @click="save">
            {{ saveMutation.isPending.value ? '保存中…' : '保存' }}
          </button>
        </footer>
      </div>
    </section>
  </div>
</template>

<style scoped>
.prompt-page {
  display: flex;
  height: 100%;
  min-height: 0;
}

.filters {
  width: 220px;
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

.cat-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.cat {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  border: none;
  background: transparent;
  border-radius: var(--radius-sm);
  padding: 4px 8px;
  font-size: var(--fs-sm);
  text-align: left;
}

.cat:hover {
  background: var(--panel-2);
}

.cat.active {
  background: var(--primary-soft);
  color: var(--primary);
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex: none;
}

.cat-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cat i {
  font-style: normal;
  font-size: var(--fs-xs);
  color: var(--muted);
}

.full {
  width: 100%;
}

.list-pane {
  width: 340px;
  flex: none;
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.list-head {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap);
  border-bottom: 1px solid var(--border);
}

.search {
  flex: 1;
  min-width: 0;
}

.count {
  font-size: var(--fs-xs);
  color: var(--muted);
  white-space: nowrap;
}

.list {
  flex: 1;
  overflow-y: auto;
}

.row {
  display: block;
  width: 100%;
  text-align: left;
  border: none;
  border-bottom: 1px solid var(--border);
  background: transparent;
  padding: var(--gap-sm) var(--gap);
  transition: 0.1s;
}

.row:hover {
  background: var(--panel-2);
}

.row.active {
  background: var(--primary-soft);
  box-shadow: inset 2px 0 0 var(--primary);
}

.row-title {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--fs-sm);
  font-weight: 600;
}

.name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pin,
.star {
  font-size: var(--fs-xs);
  color: #fbbf24;
}

.rating {
  margin-left: auto;
  font-size: var(--fs-xs);
  color: #fbbf24;
}

.row-preview {
  font-size: var(--fs-xs);
  color: var(--muted);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-tags {
  font-size: var(--fs-xs);
  color: var(--primary);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm);
  border-top: 1px solid var(--border);
}

.page-num {
  font-size: var(--fs-sm);
  color: var(--muted);
}

.detail-pane {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
}

.detail {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  padding: var(--gap-lg);
  height: 100%;
}

.detail-head {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
}

.name-input {
  flex: 1;
  font-size: var(--fs-lg);
  font-weight: 600;
  background: transparent;
  border: 1px solid transparent;
  padding: 4px 6px;
}

.name-input:hover,
.name-input:focus {
  border-color: var(--border);
  background: var(--panel-2);
}

.stars {
  display: flex;
  align-items: center;
  gap: 2px;
}

.label {
  font-size: var(--fs-sm);
  color: var(--muted);
  margin-right: var(--gap-sm);
}

.star-btn {
  border: none;
  background: transparent;
  color: var(--border-strong);
  font-size: var(--fs-lg);
  line-height: 1;
  padding: 0 1px;
}

.star-btn.on {
  color: #fbbf24;
}

.meta {
  margin-left: auto;
  font-size: var(--fs-xs);
  color: var(--muted);
}

.field {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  font-size: var(--fs-sm);
  color: var(--muted);
}

.field.grow {
  flex: 1;
  min-height: 0;
}

.field textarea {
  flex: 1;
  min-height: 120px;
  resize: vertical;
  font: inherit;
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--gap-sm);
  outline: none;
}

.field textarea.small {
  min-height: 64px;
}

.field textarea:focus {
  border-color: var(--primary);
}

.field input {
  background: var(--panel-2);
}

.detail-foot {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding-top: var(--gap-sm);
  border-top: 1px solid var(--border);
  font-size: var(--fs-sm);
}

.dirty {
  color: var(--warn);
}

.saved {
  color: var(--muted);
}

.spacer {
  flex: 1;
}

.btn.primary {
  border-color: var(--primary);
  background: var(--primary);
  color: #fff;
}

.btn.primary:disabled {
  opacity: 0.4;
}

.empty {
  font-size: var(--fs-sm);
  color: var(--muted);
}

.empty.big {
  padding: 60px;
  text-align: center;
}
</style>
