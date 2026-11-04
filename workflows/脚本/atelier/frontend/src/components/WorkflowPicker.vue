<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import EmptyState from './EmptyState.vue'
import type { WorkflowRow } from '../composables/useWorkflows'

/**
 * 可搜索的工作流选择器。
 *
 * 原生 select 在 380px 侧栏/长文件名下必然截断，而工作流是出图最关键的上下文。
 * 这里把选择拆成「触发器 + 下拉面板」：触发器显示全文（超出才省略，悬停可看完整路径），
 * 面板里每项允许换行显示完整名称，并支持输入过滤。
 */
const props = defineProps<{
  modelValue: string
  workflows: WorkflowRow[]
}>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const open = ref(false)
const query = ref('')
const root = ref<HTMLElement | null>(null)
const searchInput = ref<HTMLInputElement | null>(null)

/** 去掉扩展名，保留原始命名（下划线换空格更易读）。 */
function displayName(name: string): string {
  return name.replace(/\.json$/i, '').replace(/_/g, ' ')
}

const current = computed(() => props.workflows.find((w) => w.path === props.modelValue))
const currentName = computed(() => {
  if (current.value) return displayName(current.value.name)
  // 选中的工作流被隐藏/不在列表里时，退回路径文件名，至少不显示成"未选择"
  if (props.modelValue) {
    return displayName(props.modelValue.split(/[\\/]/).pop() ?? props.modelValue)
  }
  return '选择工作流…'
})

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return props.workflows
  return props.workflows.filter((w) => `${w.name} ${w.path}`.toLowerCase().includes(q))
})

function toggle() {
  open.value = !open.value
  if (open.value) {
    query.value = ''
    nextTick(() => searchInput.value?.focus())
  }
}

function choose(wf: WorkflowRow) {
  emit('update:modelValue', wf.path)
  open.value = false
}

function onDocMouseDown(event: MouseEvent) {
  if (open.value && root.value && !root.value.contains(event.target as Node)) {
    open.value = false
  }
}

function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape') open.value = false
}

watch(open, (value) => {
  if (value) {
    document.addEventListener('mousedown', onDocMouseDown)
    document.addEventListener('keydown', onKey)
  } else {
    document.removeEventListener('mousedown', onDocMouseDown)
    document.removeEventListener('keydown', onKey)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocMouseDown)
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <div ref="root" class="wf-picker">
    <button
      class="wf-trigger"
      type="button"
      :title="current?.path ?? '选择工作流'"
      @click="toggle"
    >
      <span class="wf-name">{{ currentName }}</span>
      <span class="caret">▾</span>
    </button>

    <div v-if="open" class="wf-menu">
      <input
        ref="searchInput"
        v-model="query"
        class="wf-search"
        type="search"
        placeholder="搜索工作流名称或路径…"
      />
      <div class="wf-list">
        <button
          v-for="wf in filtered"
          :key="wf.path"
          type="button"
          class="wf-option"
          :class="{ active: wf.path === modelValue }"
          :title="wf.path"
          @click="choose(wf)"
        >
          {{ displayName(wf.name) }}
        </button>
        <EmptyState
          v-if="!filtered.length"
          compact
          text="没有匹配的工作流"
          hint="换个关键词，或到「分类与标签 → 工作流」上传 JSON。"
          action-text="清空搜索"
          @action="query = ''"
        />
      </div>
      <div class="wf-hint">
        其他目录的工作流请到「分类与标签 → 工作流」上传自定义 JSON
      </div>
    </div>
  </div>
</template>

<style scoped>
.btn {
  transition:
    color var(--dur-fast) var(--ease),
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease);
}

.wf-picker {
  position: relative;
  /* 这一行里只有工作流名可以省略，所以压缩优先发生在它身上，下拉保持内容宽度 */
  flex: 4 1 240px;
  min-width: 160px;
  max-width: 640px;
}

.wf-trigger {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  width: 100%;
  padding: 5px 8px;
  text-align: left;
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  transition:
    color var(--dur-fast) var(--ease),
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease);
}

.wf-trigger:hover,
.wf-trigger:focus-visible {
  border-color: var(--primary);
}

.wf-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-sm);
}

.caret {
  flex: none;
  color: var(--muted);
  font-size: var(--fs-xs);
}

.wf-menu {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  z-index: 80;
  width: min(560px, 88vw);
  max-height: 52vh;
  display: flex;
  flex-direction: column;
  background: var(--panel);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  overflow: hidden;
}

.wf-search {
  margin: 6px;
  flex: none;
}

.wf-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  padding: 0 6px 6px;
}

.wf-option {
  flex: none;
  padding: 5px 8px;
  text-align: left;
  color: var(--text);
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  font-size: var(--fs-sm);
  line-height: var(--lh-lg);
  white-space: normal;
  word-break: break-all;
  transition:
    color var(--dur-fast) var(--ease),
    background-color var(--dur-fast) var(--ease);
}

.wf-option:hover {
  background: var(--panel-2);
}

.wf-option.active {
  color: var(--primary);
  background: var(--primary-soft);
}

.wf-empty {
  padding: var(--gap-md);
  text-align: center;
  color: var(--muted);
  font-size: var(--fs-sm);
}

.wf-hint {
  padding: 6px 10px;
  border-top: 1px solid var(--border);
  color: var(--muted);
  font-size: var(--fs-xs);
  line-height: var(--lh-lg);
}
</style>
