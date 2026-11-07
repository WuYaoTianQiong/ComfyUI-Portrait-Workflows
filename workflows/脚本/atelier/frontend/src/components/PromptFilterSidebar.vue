<script setup lang="ts">
import { computed, ref } from 'vue'

import CategoryFilter from './CategoryFilter.vue'
import TagCloud from './TagCloud.vue'
import { SORT_OPTIONS } from '../composables/usePromptWorkspace'
import { FRAGMENT_TYPES } from '../constants'
import type { CategoryNode, TagRow } from '../api/types'

/**
 * 提示词页左侧的搜索 + 筛选区。
 *
 * 只负责呈现与把交互抛给父组件，筛选状态仍由 PromptView 持有：
 * 页码重置、查询参数都留在父组件，避免两处各存一份。
 */
const props = defineProps<{
  search: string
  categories: CategoryNode[] | undefined
  categoryId: number | null
  tags: TagRow[]
  tagIds: number[]
  tagMatch: 'all' | 'any'
  sort: string
  order: 'asc' | 'desc'
  fragmentType: string
  fragmentMatch: 'has' | 'only'
}>()

const emit = defineEmits<{
  collapse: []
  'update:search': [value: string]
  'select-category': [id: number | null]
  'update:sort': [value: string]
  'toggle-order': []
  'update:tag-match': [value: 'all' | 'any']
  'toggle-tag': [id: number]
  'set-fragment-type': [value: string]
  'set-fragment-match': [value: 'has' | 'only']
  'clear-tags': []
  'clear-fragment': []
  'clear-filters': []
}>()

const tagPanelOpen = ref(false)

const tagById = computed(() => new Map(props.tags.map((t) => [t.id, t])))
/** 分类选中态在分类列表里已经高亮，不再重复出筛选 chip；这里只汇总标签/碎片。 */
const hasChipFilters = computed(() => props.tagIds.length > 0 || props.fragmentType !== '')

function onSearchInput(event: Event) {
  emit('update:search', (event.target as HTMLInputElement).value)
}

function onSortChange(event: Event) {
  emit('update:sort', (event.target as HTMLSelectElement).value)
}

function onFragmentTypeChange(event: Event) {
  emit('set-fragment-type', (event.target as HTMLSelectElement).value)
}
</script>

<template>
  <div class="side-head">
    <button class="btn btn-sm collapse-btn" title="收起侧栏" @click="emit('collapse')">
      «
    </button>
    <div class="search-box">
      <span class="search-icon" aria-hidden="true">⌕</span>
      <input
        :value="search"
        class="search"
        type="text"
        placeholder="搜索名称 / 内容 / 标签 / 备注…"
        @input="onSearchInput"
      />
      <button
        v-if="search"
        class="search-clear"
        type="button"
        title="清除搜索"
        @click="emit('update:search', '')"
      >
        ✕
      </button>
    </div>
  </div>

  <slot name="actions" />

  <div class="side-filters">
    <CategoryFilter
      select
      show-count
      all-label="全部分类"
      :categories="categories"
      :model-value="categoryId"
      @update:model-value="emit('select-category', $event)"
    />

    <select :value="sort" title="排序" @change="onSortChange">
      <option v-for="opt in SORT_OPTIONS" :key="opt.value" :value="opt.value">
        {{ opt.label }}
      </option>
    </select>
    <button
      v-if="sort !== 'default'"
      class="btn btn-sm order-btn"
      :title="order === 'desc' ? '降序（点切换）' : '升序（点切换）'"
      @click="emit('toggle-order')"
    >
      {{ order === 'desc' ? '↓' : '↑' }}
    </button>
    <button
      class="btn btn-sm tag-toggle"
      :class="{ active: tagPanelOpen }"
      title="标签 / 碎片类型筛选"
      @click="tagPanelOpen = !tagPanelOpen"
    >
      筛选
      <span v-if="tagIds.length || fragmentType" class="badge">
        {{ tagIds.length + (fragmentType ? 1 : 0) }}
      </span>
    </button>
  </div>

  <div v-if="tagPanelOpen" class="tag-panel">
    <div class="frag-filter-row inline">
      <select
        :value="fragmentType"
        class="frag-select"
        title="按碎片类型筛选（正文里的【类型】结构）"
        @change="onFragmentTypeChange"
      >
        <option value="">全部碎片</option>
        <option v-for="t in FRAGMENT_TYPES" :key="t" :value="t">{{ t }}</option>
      </select>
      <template v-if="fragmentType">
        <button
          class="btn btn-sm"
          :class="{ active: fragmentMatch === 'has' }"
          title="含有该类型（多出来的类型不影响）"
          @click="emit('set-fragment-match', 'has')"
        >
          含有
        </button>
        <button
          class="btn btn-sm"
          :class="{ active: fragmentMatch === 'only' }"
          title="只含该类型：出现别的类型就不算，用来找「只有某一段描写」的提示词"
          @click="emit('set-fragment-match', 'only')"
        >
          仅含
        </button>
      </template>
    </div>
    <TagCloud
      :tags="tags"
      :selected="tagIds"
      :match="tagMatch"
      clearable
      empty-text="暂无带提示词的标签"
      @toggle="emit('toggle-tag', $event)"
      @update:match="emit('update:tag-match', $event)"
      @clear="emit('clear-tags')"
    />
    <button class="btn btn-sm full" @click="emit('clear-tags')">清空标签</button>
  </div>

  <div v-if="hasChipFilters" class="active-filters">
    <button
      v-for="id in tagIds"
      :key="id"
      class="filter-chip"
      :title="`清除标签：${tagById.get(id)?.name ?? id}`"
      @click="emit('toggle-tag', id)"
    >
      {{ tagById.get(id)?.name ?? `#${id}` }} ×
    </button>
    <button
      v-if="fragmentType"
      class="filter-chip"
      :title="`清除碎片筛选：${fragmentType}`"
      @click="emit('clear-fragment')"
    >
      {{ fragmentMatch === 'only' ? '仅' : '含' }}{{ fragmentType }} ×
    </button>
    <button class="btn btn-sm ghost" @click="emit('clear-filters')">全部清除</button>
  </div>
</template>

<style scoped>
.side-head {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm) var(--gap);
  border-bottom: 1px solid var(--border);
}

.collapse-btn {
  flex: none;
}

.search-box {
  position: relative;
  display: flex;
  align-items: center;
  flex: 1;
  min-width: 0;
}

.search-icon {
  position: absolute;
  left: var(--gap-sm);
  color: var(--muted);
  font-size: var(--fs-lg);
  line-height: 1;
  pointer-events: none;
}

.search {
  flex: 1;
  min-width: 0;
  padding-left: 28px;
  padding-right: 24px;
}

.search:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 1px;
}

.search-clear {
  position: absolute;
  right: var(--gap-xs);
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: var(--muted);
  font-size: var(--fs-xs);
  line-height: 1;
  padding: 0;
  transition:
    background-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.search-clear:hover {
  background: var(--panel-3);
  color: var(--text);
}

/* 分类收成下拉后，一行放得下：分类下拉 + 排序 + 筛选 */
.side-filters {
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
  padding: var(--gap-sm) var(--gap);
  border-bottom: 1px solid var(--border);
}

.side-filters :deep(.group) {
  flex: 1 1 auto;
  min-width: 0;
}

.side-filters select {
  min-width: 0;
  background: var(--panel-2);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 3px 6px;
  font: inherit;
  font-size: var(--fs-sm);
}

.cat-select {
  flex: 1;
}

.order-btn {
  flex: none;
  padding: 2px 7px;
}

.tag-toggle {
  flex: none;
}

.tag-toggle.active {
  border-color: var(--primary);
  color: var(--primary);
}

.tag-panel {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  padding: var(--gap-sm) var(--gap);
  border-bottom: 1px solid var(--border);
  background: var(--panel-2);
  max-height: 42vh;
  overflow-y: auto;
}

.tag-panel .full {
  width: 100%;
}

.frag-filter-row {
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
  padding: var(--gap-sm) var(--gap);
  border-bottom: 1px solid var(--border);
}

.frag-filter-row.inline {
  padding: 0;
  border-bottom: 0;
}

.frag-select {
  flex: 1;
  min-width: 0;
  background: var(--panel-2);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 3px 6px;
  font: inherit;
  font-size: var(--fs-sm);
}

.frag-filter-row .btn {
  flex: none;
}

.frag-filter-row .btn.active {
  border-color: var(--primary);
  background: var(--primary-soft);
  color: var(--primary);
}

.badge {
  display: inline-grid;
  place-items: center;
  min-width: 15px;
  height: 15px;
  margin-left: var(--gap-xs);
  padding: 0 var(--gap-xs);
  border-radius: var(--radius-pill);
  background: var(--primary);
  color: rgb(255 255 255);
  font-size: var(--fs-xs);
  line-height: 1;
}

.active-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-xs);
  padding: var(--gap-xs) var(--gap);
  border-bottom: 1px solid var(--border);
}

.filter-chip {
  border: 1px solid var(--primary);
  background: var(--primary-soft);
  color: var(--primary);
  border-radius: var(--radius-pill);
  padding: 1px var(--gap-sm);
  font-size: var(--fs-xs);
}

.btn.ghost {
  border-color: transparent;
  color: var(--muted);
}
</style>