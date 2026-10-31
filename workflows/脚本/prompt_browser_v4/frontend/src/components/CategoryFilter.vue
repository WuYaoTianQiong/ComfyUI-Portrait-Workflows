<script setup lang="ts">
import { computed } from 'vue'

import type { CategoryNode } from '../api/types'
import { flattenCategories } from '../utils/categories'

/**
 * 分类筛选（提示词页 / 组合器共用）。
 *
 * 只负责「全部 + 分层分类列表」，不持有查询状态；选中值走 v-model。
 */
const props = defineProps<{
  categories: CategoryNode[] | undefined
  modelValue: number | null
  allLabel?: string
  showCount?: boolean
}>()

const emit = defineEmits<{ 'update:modelValue': [value: number | null] }>()

const flat = computed(() => flattenCategories(props.categories))
</script>

<template>
  <section class="group">
    <div class="group-head"><span>分类</span></div>
    <div class="cat-list">
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
        :style="{ paddingLeft: `${8 + cat.depth * 14}px` }"
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

.cat-count {
  color: var(--muted);
  font-size: var(--fs-xs);
  font-style: normal;
}
</style>
