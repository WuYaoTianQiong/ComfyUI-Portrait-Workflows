<script setup lang="ts">
/**
 * 合成台工作流下拉（`/api/workflows?scope=studio`），**受控多选**。
 *
 * 契约 C-REF-WF-SLOTS@1：下拉项按「当前已选槽位」判定适用性，
 * 缺少对应业务角色（`slots`）的项显示原因并禁止勾选；空槽位不参与判定。
 *
 * `slots` 三态（收紧点 1）：`undefined` = 旧后端字段缺失，不判定；
 * `[]` = 角色不可识别（可能是 UI 格式工作流），对所有非空槽位都禁用并提示；
 * 非空 = 按角色匹配。
 *
 * 为什么不用主站 `WorkflowPicker.vue`：共享组件只接受 `WorkflowRow[]` 且是单选，
 * 也不支持 `scope=studio` 的目录过滤；白名单不允许改共享组件，因此这里重做，
 * 交互约定保持一致（点击触发器展开、点击外部 / Esc 关闭）。
 *
 * §5 尺寸基线：触发器 336.33 × 36px、圆角 8px、字号 12px；
 * 下拉行 435.13 × 28px、圆角 6px、字号 12px、内边距 6px 32px 6px 8px。
 */

import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import type {
  StudioWorkflowOption,
  StudioWorkflowSlot,
} from '../../../../composables/useReferenceRecipe'
import {
  describeWorkflowUnavailableFor,
  workflowDisplayName,
} from '../../../../composables/useReferenceRecipe'

const props = withDefaults(
  defineProps<{
    /** 多选值：有序、去重；空数组 = 使用后端默认工作流。 */
    modelValue: string[]
    workflows: StudioWorkflowOption[]
    /** 当前已选**非空**槽位的业务角色；空槽不传。 */
    selectedRoles?: StudioWorkflowSlot[]
    /** 后端默认工作流路径（空选择时 UI 明示）。 */
    defaultPath?: string
    loading?: boolean
    disabled?: boolean
  }>(),
  {
    selectedRoles: () => [],
    defaultPath: '',
    loading: false,
    disabled: false,
  },
)

const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>()

const open = ref(false)
const root = ref<HTMLElement | null>(null)
const listEl = ref<HTMLElement | null>(null)

const selectedSet = computed(() => new Set(props.modelValue))

/** 已选工作流对应的目录项（保序、过滤目录中已消失的路径）。 */
const selectedItems = computed(() =>
  props.modelValue
    .map((path) => props.workflows.find((item) => item.path === path))
    .filter((item): item is StudioWorkflowOption => Boolean(item)),
)

/** 后端默认项：路径恰好等于 defaultPath。 */
const defaultItem = computed(
  () => props.workflows.find((item) => item.path === props.defaultPath) ?? null,
)

/** 触发器文案：空选择明示「使用默认工作流」，而不是留空白。 */
const triggerLabel = computed(() => {
  if (props.loading) return '正在读取本机工作流…'
  if (selectedItems.value.length === 0) {
    if (defaultItem.value) {
      return `使用默认工作流：${workflowDisplayName(defaultItem.value.name)}`
    }
    return '选择本机工作流'
  }
  if (selectedItems.value.length === 1) {
    const item = selectedItems.value[0]
    return `${workflowDisplayName(item.name)}${inputLabel(item)}`
  }
  const first = selectedItems.value[0]
  return `已选 ${selectedItems.value.length} 个工作流（首个：${workflowDisplayName(first.name)}）`
})

const triggerTitle = computed(() => {
  if (props.modelValue.length) return props.modelValue.join('\n')
  return defaultItem.value?.path ?? '选择工作流'
})

/** 输入数文案：优先后端 `input_count`，旧响应回退 `image_slots`。 */
function inputLabel(item: StudioWorkflowOption): string {
  const count = item.inputCount || item.imageSlots
  return count ? `（${count} 输入）` : ''
}

/** 行内展示：来源前缀（库根本身不加）+ 名称 + 输入数。 */
function optionLabel(item: StudioWorkflowOption): string {
  const name = workflowDisplayName(item.name)
  const prefix =
    item.source && item.source !== '库根' && !name.startsWith(item.source) ? `${item.source} · ` : ''
  return `${prefix}${name}${inputLabel(item)}`
}

function isSelected(path: string): boolean {
  return selectedSet.value.has(path)
}

/**
 * 不可用原因：缺少当前已选槽位对应的输入、或 slots 为空导致角色不可识别时，
 * 返回中文原因；否则空串。
 *
 * 三态口径（收紧点）：`slots === undefined`（旧后端字段缺失）不判定；
 * `slots === []`（UI 格式工作流 / 解析失败）一律视为不可识别并禁用。
 */
function reasonFor(item: StudioWorkflowOption): string {
  return describeWorkflowUnavailableFor(item, props.selectedRoles)
}

function toggle(): void {
  if (props.disabled || props.loading) return
  open.value = !open.value
  if (open.value) {
    void nextTick(() => {
      listEl.value?.querySelector<HTMLElement>('.wf-option.is-active')?.scrollIntoView({
        block: 'nearest',
      })
    })
  }
}

/** 勾选 / 取消：不可用项直接忽略（禁止选中）。 */
function toggleOption(item: StudioWorkflowOption): void {
  if (props.disabled || props.loading) return
  if (reasonFor(item)) return

  const next = isSelected(item.path)
    ? props.modelValue.filter((path) => path !== item.path)
    : [...props.modelValue, item.path]
  emit('update:modelValue', next)
}

function onDocMouseDown(event: MouseEvent): void {
  if (open.value && root.value && !root.value.contains(event.target as Node)) {
    open.value = false
  }
}

function onKey(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    open.value = false
    root.value?.querySelector<HTMLElement>('.wf-trigger')?.focus()
  }
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
  <div ref="root" class="wf-select" data-testid="studio-workflow-select">
    <button
      type="button"
      class="wf-trigger"
      :disabled="loading || disabled"
      :aria-expanded="open"
      aria-haspopup="listbox"
      :title="triggerTitle"
      data-testid="studio-workflow-trigger"
      @click="toggle"
    >
      <span class="wf-trigger__label">{{ triggerLabel }}</span>
      <span
        v-if="selectedItems.length === 1 && selectedItems[0].recommended"
        class="wf-badge"
        data-testid="studio-workflow-recommended"
      >推荐</span>
      <span class="wf-trigger__caret" aria-hidden="true">▾</span>
    </button>

    <div v-if="open" class="wf-menu">
      <!-- 未选时明示默认工作流；已选时明示多选数量 -->
      <p
        v-if="!modelValue.length && defaultItem"
        class="wf-default"
        data-testid="studio-workflow-default-hint"
      >
        当前使用默认工作流：{{ workflowDisplayName(defaultItem.name) }}
      </p>
      <p v-else-if="modelValue.length" class="wf-default" data-testid="studio-workflow-selected-hint">
        已选 {{ modelValue.length }} 个工作流；每组任务按所选工作流分别提交。
      </p>

      <div
        ref="listEl"
        class="wf-list"
        role="listbox"
        aria-label="本机工作流列表"
        aria-multiselectable="true"
      >
        <button
          v-for="item in workflows"
          :key="item.path"
          type="button"
          class="wf-option"
          :class="{
            'is-active': isSelected(item.path),
            'is-unavailable': Boolean(reasonFor(item)),
          }"
          role="option"
          :aria-selected="isSelected(item.path) || undefined"
          :aria-disabled="Boolean(reasonFor(item)) || undefined"
          :title="item.path"
          data-testid="studio-workflow-option"
          @click="toggleOption(item)"
        >
          <span class="wf-check" aria-hidden="true">{{ isSelected(item.path) ? '✓' : '' }}</span>
          <span class="wf-option__body">
            <span class="wf-option__text">{{ optionLabel(item) }}</span>
            <span
              v-if="reasonFor(item)"
              class="wf-option__reason"
              data-testid="studio-workflow-unavailable"
            >{{ reasonFor(item) }}</span>
          </span>
          <span v-if="item.recommended" class="wf-badge">推荐</span>
        </button>

        <p v-if="!loading && workflows.length === 0" class="wf-empty">
          本机库目录中没有可用工作流，请先放入出图工作流 JSON。
        </p>
        <p v-if="loading" class="wf-empty">正在读取本机工作流列表…</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wf-select {
  position: relative;
  width: 100%;
  max-width: 336.33px;
  min-width: 0;
}

/* 触发器 336.33 × 36、圆角 8、字号 12 */
.wf-trigger {
  display: flex;
  align-items: center;
  gap: 6px;
  box-sizing: border-box;
  width: 100%;
  height: 36px;
  padding: 0 8px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-deep);
  color: var(--text-strong);
  font-size: 12px;
  line-height: 1;
  text-align: left;
  cursor: pointer;
}

.wf-trigger:hover:not(:disabled) {
  border-color: var(--primary);
}

.wf-trigger:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.wf-trigger:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 1px;
}

.wf-trigger__label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wf-trigger__caret {
  flex: none;
  color: var(--text-muted);
  font-size: 11px;
}

/* 「推荐」徽章 26 × 13、圆角 4、9px / 500、内边距 2px 4px */
.wf-badge {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  width: 26px;
  height: 13px;
  padding: 2px 4px;
  border-radius: 4px;
  background: var(--accent-green-soft);
  color: var(--accent-green);
  font-size: 9px;
  font-weight: 500;
  line-height: 1;
  white-space: nowrap;
}

/*
 * 下拉面板：行宽 435.13（§5）。
 * 边框用 box-shadow 画而不是 border：border 会占 1px 宽度，把行宽压到 433。
 */
.wf-menu {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  z-index: 80;
  box-sizing: border-box;
  width: min(435.13px, calc(100vw - 64px));
  max-height: 360px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-radius: 10px;
  background: var(--surface-raised);
  box-shadow:
    0 0 0 1px var(--border-strong, var(--border)),
    var(--shadow-3);
}

/* 默认 / 多选说明：常驻在列表顶部，进下拉第一眼就能看到 */
.wf-default {
  margin: 0;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
  color: var(--text-body-soft);
  font-size: 11px;
  line-height: 1.5;
}

.wf-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 0;
  overflow-y: auto;
}

/* 行 435.13 × 28、圆角 6、12px、内边距 6px 32px 6px 8px */
.wf-option {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  box-sizing: border-box;
  width: 100%;
  min-height: 28px;
  padding: 6px 32px 6px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--text-strong);
  font-size: 12px;
  line-height: 1.3;
  text-align: left;
  white-space: normal;
  word-break: break-all;
  cursor: pointer;
}

.wf-option:hover {
  background: var(--fill-subtle);
}

.wf-option.is-active {
  background: var(--primary-soft, rgba(99, 102, 241, 0.16));
  color: var(--text-strong);
}

/* 不适用项：名称保持可读，不整体降透明度（灰底灰字难辨认） */
.wf-option.is-unavailable {
  cursor: not-allowed;
}

.wf-option.is-unavailable:hover {
  background: transparent;
}

.wf-option.is-unavailable .wf-option__text {
  color: var(--text-muted);
}

.wf-option:focus-visible {
  outline: 1px solid var(--primary);
  outline-offset: -1px;
}

/* 多选勾选框：固定 14px，避免行高跳动 */
.wf-check {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  width: 14px;
  height: 14px;
  margin-top: 1px;
  border: 1px solid var(--border);
  border-radius: 3px;
  color: var(--on-inverse);
  font-size: 10px;
  line-height: 1;
}

.wf-option.is-active .wf-check {
  border-color: transparent;
  background: var(--primary);
}

.wf-option__body {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.wf-option__text {
  min-width: 0;
}

/* 不适用原因：红色可读，不靠浅灰 */
.wf-option__reason {
  color: var(--danger-text-soft);
  font-size: 10px;
  line-height: 1.5;
  word-break: break-word;
}

.wf-empty {
  margin: 0;
  padding: 10px 8px;
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.6;
}
</style>