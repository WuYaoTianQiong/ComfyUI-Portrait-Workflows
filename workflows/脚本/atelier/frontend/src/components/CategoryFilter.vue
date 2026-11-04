<script setup lang="ts">
import { computed } from 'vue'

import type { CategoryNode } from '../api/types'
import { flattenCategories } from '../utils/categories'

/**
 * 分类筛选（提示词页 / 组合器共用）。
 *
 * 只负责「全部 + 分层分类列表」，不持有查询状态；选中值走 v-model。
 * 分类以 pill 分段控件呈现：选中 `--primary` 实底，未选 `--panel-2`。
 * `inline` 用于提示词页单行横向滚动，避免分类把筛选区撑成多行。
 */
const props = defineProps<{
  categories: CategoryNode[] | undefined
  modelValue: number | null
  allLabel?: string
  showCount?: boolean
  inline?: boolean
}>()

const emit = defineEmits<{ 'update:modelValue': [value: number | null] }>()

const flat = computed(() => flattenCategories(props.categories))
</script>

<template>
  <section class="group">
    <div v-if="!inline" class="group-head"><span>分类</span></div>
    <div class="cat-list" :class="{ inline }">
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
  </section>
</template>

<style scoped>
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
  flex-wrap: wrap;
  gap: var(--gap-xs);
}

.cat-list.inline {
  flex-wrap: nowrap;
  overflow-x: auto;
  padding-bottom: 2px;
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