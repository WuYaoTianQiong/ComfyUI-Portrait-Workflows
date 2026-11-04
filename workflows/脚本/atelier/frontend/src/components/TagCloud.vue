<script setup lang="ts">
import { computed } from 'vue'

import type { TagRow } from '../api/types'
import EmptyState from './EmptyState.vue'

/**
 * 标签云 + 交集/并集切换（画廊与提示词页共用）。
 *
 * 只展示"确实有内容"的标签：库里 178 个标签有一半是历史孤儿，
 * 全铺出来会把有用的淹掉。已选中的即使计数为 0 也保留，否则取消不掉。
 */
const props = defineProps<{
  tags: TagRow[]
  selected: number[]
  match: 'all' | 'any'
  emptyText?: string
  /** 多选时在匹配方式旁给出「清除」，由父组件处理清空逻辑 */
  clearable?: boolean
}>()

const emit = defineEmits<{
  (e: 'toggle', id: number): void
  (e: 'update:match', value: 'all' | 'any'): void
  (e: 'clear'): void
}>()

const visible = computed(() =>
  props.tags.filter((t) => t.prompt_count > 0 || props.selected.includes(t.id)),
)
</script>

<template>
  <div class="wrap">
    <div class="mode-switch">
      <button
        class="btn btn-sm"
        :class="{ active: match === 'all' }"
        title="选中的标签必须同时满足"
        @click="emit('update:match', 'all')"
      >
        全部满足
      </button>
      <button
        class="btn btn-sm"
        :class="{ active: match === 'any' }"
        title="满足任意一个标签即可"
        @click="emit('update:match', 'any')"
      >
        任一满足
      </button>
      <button
        v-if="clearable && selected.length"
        class="btn btn-sm clear-btn"
        title="清除所有已选标签"
        @click="emit('clear')"
      >
        清除
      </button>
    </div>

    <div class="cloud">
      <button
        v-for="tag in visible"
        :key="tag.id"
        class="tag"
        :class="{ active: selected.includes(tag.id) }"

        @click="emit('toggle', tag.id)"
      >
        {{ tag.name }}<i>{{ tag.prompt_count }}</i>
      </button>
      <EmptyState v-if="!visible.length" :text="emptyText ?? '暂无可用标签'" />
    </div>
  </div>
</template>

<style scoped>
.wrap {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}

.mode-switch {
  display: flex;
  gap: var(--gap-xs);
}

.mode-switch .btn {
  flex: 1;
  font-size: var(--fs-xs);
  border-radius: var(--radius-pill);
  background: var(--panel-2);
  transition:
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.mode-switch .btn.active {
  border-color: var(--primary);
  background: var(--primary);
  color: rgb(255 255 255);
}

.mode-switch .clear-btn {
  flex: none;
  border-radius: var(--radius-pill);
  transition:
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.cloud {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-xs);
  /* 提示词维度有 95 个标签，不封顶会把整个侧栏撑满、把分类和按钮挤出去 */
  max-height: 46vh;
  overflow-y: auto;
  padding-right: 2px;
}

.tag {
  font-size: var(--fs-sm);
  padding: 3px var(--gap-sm);
  border-radius: var(--radius-pill);
  border: 1px solid var(--border);
  background: var(--panel-2);
  color: var(--text);
  transition:
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.tag:hover {
  border-color: var(--border-strong);
  background: var(--panel-3);
}

.tag.active {
  background: var(--primary);
  border-color: var(--primary);
  color: rgb(255 255 255);
}

.tag:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

.tag i {
  font-style: normal;
  font-size: var(--fs-xs);
  opacity: 0.8;
  margin-left: 4px;
}

.empty {
  font-size: var(--fs-sm);
  color: var(--muted);
}
</style>
