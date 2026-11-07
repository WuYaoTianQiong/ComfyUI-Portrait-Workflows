<script setup lang="ts">
import { computed, ref } from 'vue'

import type { CategoryNode } from '../api/types'
import { flattenCategories } from '../utils/categories'

/**
 * 分类筛选（提示词页 / 组合器共用）。
 *
 * 只负责「全部 + 分层分类列表」，不持有查询状态；选中值走 v-model。
 * 默认以 pill 分段控件呈现：选中 `--primary` 实底，未选 `--panel-2`。
 * `select` 用于提示词页侧栏：收成一个下拉，分类再多也不占纵向空间。
 */
const props = defineProps<{
  categories: CategoryNode[] | undefined
  modelValue: number | null
  allLabel?: string
  showCount?: boolean
  select?: boolean
}>()

const emit = defineEmits<{ 'update:modelValue': [value: number | null] }>()

const flat = computed(() => flattenCategories(props.categories))

function onSelectChange(event: Event) {
  const raw = (event.target as HTMLSelectElement).value
  emit('update:modelValue', raw === '' ? null : Number(raw))
}

/** 两级分类用全角空格缩进，原生下拉里也能看出层级。 */
function optionLabel(name: string, depth: number) {
  return `${'　'.repeat(depth)}${name}`
}

/**
 * 「分类」分组可折叠，默认展开。
 * 仅控制展示，不参与 v-model：收起再展开后已选分类保持不变（选中值在父组件）。
 */
const collapsed = ref(false)

function toggleCollapsed() {
  collapsed.value = !collapsed.value
}
</script>

<template>
  <section class="group">
    <select
      v-if="select"
      class="cat-select"
      :value="modelValue ?? ''"
      :title="allLabel ?? '全部'"
      @change="onSelectChange"
    >
      <option value="">{{ allLabel ?? '全部' }}</option>
      <option v-for="cat in flat" :key="cat.id" :value="cat.id">
        {{ optionLabel(cat.name, cat.depth) }}{{ showCount ? ` (${cat.prompt_count})` : '' }}
      </option>
    </select>

    <template v-else>
      <button
        type="button"
        class="group-head"
        :aria-expanded="!collapsed"
        @click="toggleCollapsed"
      >
        <span>{{ collapsed ? '▸' : '▾' }} 分类</span>
      </button>
      <div v-show="!collapsed" class="cat-list">
        <button
          class="cat"
          :class="{ active: modelValue === null }"
          @click="emit('update:modelValue', null)"
        >
          {{ allLabel ?? '全部' }}
        </button>
        <button
          v-for="cat in flat"
          :key="cat.id"
          class="cat"
          :class="{ active: modelValue === cat.id }"
          :title="cat.name"
          @click="emit('update:modelValue', cat.id)"
        >
          <span class="dot" :style="{ background: cat.color }" />
          <span class="cat-name">{{ cat.name }}</span>
          <i v-if="showCount" class="cat-count">{{ cat.prompt_count }}</i>
        </button>
      </div>
    </template>
  </section>
</template>

<style scoped>
/* 与 GalleryView 侧栏其它可折叠分面组头保持一致（字号/颜色/hover/右侧不占位）。 */
.group-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  margin: 0 0 var(--gap-sm);
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  text-align: left;
  font-family: inherit;
  line-height: inherit;
  font-size: var(--fs-sm);
  color: var(--muted);
  transition: color var(--dur-fast) var(--ease);
}

.group-head:hover {
  color: var(--text);
}

.group-head:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

.cat-list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-xs);
}

/* 下拉形态：与侧栏里其它 select 同一套外观 */
.cat-select {
  width: 100%;
  min-width: 0;
  background: var(--panel-2);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 3px 6px;
  font: inherit;
  font-size: var(--fs-sm);
}

.cat {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-xs);
  flex: none;
  border: 1px solid var(--border);
  background: var(--panel-2);
  border-radius: var(--radius-pill);
  padding: 2px var(--gap-sm);
  font-size: var(--fs-sm);
  color: var(--text);
  white-space: nowrap;
  transition:
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.cat:hover {
  border-color: var(--border-strong);
  background: var(--panel-3);
}

.cat.active {
  border-color: var(--primary);
  background: var(--primary);
  color: rgb(255 255 255);
}

.cat:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex: none;
}

.cat-name {
  overflow: hidden;
  text-overflow: ellipsis;
}

.cat-count {
  color: var(--muted);
  font-size: var(--fs-xs);
  font-style: normal;
}

.cat.active .cat-count {
  color: rgb(255 255 255);
  opacity: 0.8;
}
</style>