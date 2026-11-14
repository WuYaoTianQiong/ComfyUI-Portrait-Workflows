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
 *
 * `multiple` 打开横评多选态：面板变复选列表、选中项变可拖拽排序的芯片。
 * 单选态（默认）行为与样式保持不变，其它页面不受影响。
 */
const props = withDefaults(
  defineProps<{
    modelValue: string
    workflows: WorkflowRow[]
    multiple?: boolean
    selected?: string[]
    /** path → 不可用原因；有原因即置灰（横评里排除编辑/超分/视频类） */
    unavailable?: Record<string, string>
  }>(),
  { multiple: false, selected: () => [], unavailable: () => ({}) },
)
const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:selected': [value: string[]]
}>()

const open = ref(false)
const query = ref('')
const root = ref<HTMLElement | null>(null)
const searchInput = ref<HTMLInputElement | null>(null)
const dragIndex = ref<number | null>(null)
const overIndex = ref<number | null>(null)

/** 去掉扩展名，保留原始命名（下划线换空格更易读）。 */
function displayName(name: string): string {
  return name.replace(/\.json$/i, '').replace(/_/g, ' ')
}

const current = computed(() => props.workflows.find((w) => w.path === props.modelValue))
const selectedRows = computed(() =>
  props.selected
    .map((path) => props.workflows.find((w) => w.path === path))
    .filter((w): w is WorkflowRow => Boolean(w)),
)
const currentName = computed(() => {
  if (props.multiple) {
    if (!selectedRows.value.length) return '选择工作流…'
    const first = displayName(selectedRows.value[0].name)
    return selectedRows.value.length === 1
      ? first
      : `已选 ${selectedRows.value.length} 个（首个：${first}）`
  }
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

function isSelected(path: string): boolean {
  return props.multiple ? props.selected.includes(path) : path === props.modelValue
}

function reasonFor(path: string): string {
  return props.unavailable[path] ?? ''
}

function toggle() {
  open.value = !open.value
  if (open.value) {
    query.value = ''
    nextTick(() => searchInput.value?.focus())
  }
}

function choose(wf: WorkflowRow) {
  if (reasonFor(wf.path)) return
  if (props.multiple) {
    emit(
      'update:selected',
      props.selected.includes(wf.path)
        ? props.selected.filter((p) => p !== wf.path)
        : [...props.selected, wf.path],
    )
    return
  }
  emit('update:modelValue', wf.path)
  open.value = false
}

function remove(path: string) {
  emit('update:selected', props.selected.filter((p) => p !== path))
}

function onDragStart(index: number, event: DragEvent) {
  dragIndex.value = index
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    try {
      event.dataTransfer.setData('text/plain', String(index))
    } catch {
      /* 某些浏览器在受限上下文里会抛，拖拽本身仍可用 */
    }
  }
}

function onDrop(index: number) {
  const from = dragIndex.value
  dragIndex.value = null
  overIndex.value = null
  if (from === null || from === index) return
  const list = props.selected.slice()
  const [item] = list.splice(from, 1)
  list.splice(index, 0, item)
  emit('update:selected', list)
}

/** 键盘也能排序：芯片聚焦时 Alt+←/→ 移动一位。 */
function onChipKey(index: number, event: KeyboardEvent) {
  if (!event.altKey || (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight')) return
  event.preventDefault()
  const to = event.key === 'ArrowLeft' ? index - 1 : index + 1
  if (to < 0 || to >= props.selected.length) return
  const list = props.selected.slice()
  const [item] = list.splice(index, 1)
  list.splice(to, 0, item)
  emit('update:selected', list)
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
  <div ref="root" class="wf-picker" :class="{ multi: multiple }">
    <button
      class="wf-trigger"
      type="button"
      :title="multiple ? selected.join('\n') || '选择工作流' : current?.path ?? '选择工作流'"
      :aria-expanded="open"
      :aria-haspopup="multiple ? 'listbox' : 'menu'"
      @click="toggle"
    >
      <span v-if="multiple && selectedRows.length" class="wf-count">{{ selectedRows.length }}</span>
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
      <div class="wf-list" :role="multiple ? 'listbox' : undefined" :aria-multiselectable="multiple || undefined">
        <button
          v-for="wf in filtered"
          :key="wf.path"
          type="button"
          class="wf-option"
          :class="{ active: isSelected(wf.path), blocked: Boolean(reasonFor(wf.path)) }"
          :title="reasonFor(wf.path) || wf.path"
          :disabled="Boolean(reasonFor(wf.path))"
          :aria-selected="multiple ? isSelected(wf.path) : undefined"
          @click="choose(wf)"
        >
          <span v-if="multiple" class="wf-check" :class="{ on: isSelected(wf.path) }" aria-hidden="true">
            {{ isSelected(wf.path) ? '✓' : '' }}
          </span>
          <span class="wf-optbody">
            <span class="wf-optname">{{ displayName(wf.name) }}</span>
            <span v-if="reasonFor(wf.path)" class="wf-reason">{{ reasonFor(wf.path) }}</span>
          </span>
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
        {{ multiple
          ? '勾选多个工作流即用同一提示词、同一种子横评；编辑 / 超分 / 视频类不参与。'
          : '其他目录的工作流请到「分类与标签 → 工作流」上传自定义 JSON' }}
      </div>
    </div>

    <div v-if="multiple && selectedRows.length" class="wf-chips">
      <span
        v-for="(wf, index) in selectedRows"
        :key="wf.path"
        class="wf-chip"
        :class="{ dragging: dragIndex === index, over: overIndex === index }"
        draggable="true"
        tabindex="0"
        :title="`${wf.path}\n拖动排序，或 Alt+←/→ 移动`"
        @dragstart="onDragStart(index, $event)"
        @dragover.prevent="overIndex = index"
        @dragleave="overIndex = null"
        @drop.prevent="onDrop(index)"
        @dragend="dragIndex = null; overIndex = null"
        @keydown="onChipKey(index, $event)"
      >
        <span class="wf-chip-name">{{ displayName(wf.name) }}</span>
        <button
          type="button"
          class="wf-chip-x"
          :aria-label="`移除 ${displayName(wf.name)}`"
          @click.stop="remove(wf.path)"
        >
          ×
        </button>
      </span>
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

/* 多选横评：选择器吃满整行，芯片按内容排布，宽屏一行放得下三个以上。 */
.wf-picker.multi {
  flex: 1 1 100%;
  max-width: none;
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
  display: flex;
  align-items: flex-start;
  gap: var(--gap-sm);
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

.wf-option.blocked {
  opacity: 0.5;
  cursor: not-allowed;
}

.wf-check {
  flex: none;
  width: 16px;
  height: 16px;
  margin-top: 3px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border-strong);
  border-radius: 4px;
  background: var(--panel-2);
  font-size: var(--fs-xs);
  line-height: 1;
}

.wf-check.on {
  border-color: var(--primary);
  background: var(--primary);
  color: var(--text-strong);
}

.wf-optbody {
  min-width: 0;
  flex: 1 1 auto;
}

.wf-optname {
  display: block;
}

.wf-reason {
  display: block;
  color: var(--muted);
  font-size: var(--fs-xs);
}

.wf-count {
  flex: none;
  min-width: 18px;
  padding: 0 5px;
  border-radius: 999px;
  background: var(--primary);
  color: var(--text-strong);
  font-size: var(--fs-xs);
  text-align: center;
}

.wf-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-xs);
  margin-top: var(--gap-xs);
}

.wf-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  padding: 2px 4px 2px 8px;
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  background: var(--panel-2);
  font-size: var(--fs-xs);
  cursor: grab;
}

.wf-chip.dragging {
  opacity: 0.45;
}

.wf-chip.over {
  border-color: var(--primary);
  background: var(--primary-soft);
}

.wf-chip-name {
  min-width: 0;
  max-width: 340px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wf-chip-x {
  flex: none;
  width: 18px;
  height: 18px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: var(--muted);
  font-size: var(--fs-sm);
  line-height: 1;
  cursor: pointer;
}

.wf-chip-x:hover {
  background: var(--panel-3);
  color: var(--danger);
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
