<script setup lang="ts">
/**
 * 合成台工作流下拉（`/api/workflows?scope=studio`）。
 *
 * 为什么不直接用主站 `WorkflowPicker.vue`：共享组件只接受 `WorkflowRow[]`
 * （name/path），既不支持 `scope=studio` 的目录过滤，也没有 `recommended`
 * 徽章的插槽；而白名单不允许改共享组件。因此这里按 §5「工作流下拉」数值重做，
 * 交互约定与 `WorkflowPicker` 保持一致（点击触发器展开、点击外部 / Esc 关闭）。
 *
 * §5 补充实测：触发器 336.33 × 36px、圆角 8px、字号 12px；
 * 下拉行 435.13 × 28px、圆角 6px、字号 12px、内边距 6px 32px 6px 8px；
 * 「推荐」徽章 26 × 13px、圆角 4px、9px / 500、内边距 2px 4px、
 * 字 `#009966`、底 `rgba(0,188,128,0.15)`。
 */

import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import type { StudioWorkflowOption } from '../../../../composables/useReferenceRecipe'
import { workflowDisplayName } from '../../../../composables/useReferenceRecipe'

const props = withDefaults(
  defineProps<{
    modelValue: string
    workflows: StudioWorkflowOption[]
    loading?: boolean
    disabled?: boolean
  }>(),
  { loading: false, disabled: false },
)

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const open = ref(false)
const root = ref<HTMLElement | null>(null)
const listEl = ref<HTMLElement | null>(null)

const current = computed(() => props.workflows.find((item) => item.path === props.modelValue))

/** 触发器文案：没有选中项时给出占位，而不是空白。 */
const triggerLabel = computed(() => {
  if (props.loading) return '正在读取本机工作流…'
  const item = current.value
  if (!item) return '选择本机工作流'
  return `${workflowDisplayName(item.name)}${item.imageSlots ? `（${item.imageSlots} 图）` : ''}`
})

/** 行内展示：来源前缀（库根本身不加）+ 名称 + 槽位数。 */
function optionLabel(item: StudioWorkflowOption): string {
  const name = workflowDisplayName(item.name)
  const prefix =
    item.source && item.source !== '库根' && !name.startsWith(item.source) ? `${item.source} · ` : ''
  return `${prefix}${name}${item.imageSlots ? `（${item.imageSlots} 图）` : ''}`
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

function choose(item: StudioWorkflowOption): void {
  emit('update:modelValue', item.path)
  open.value = false
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
      :title="current?.path ?? '选择工作流'"
      data-testid="studio-workflow-trigger"
      @click="toggle"
    >
      <span class="wf-trigger__label">{{ triggerLabel }}</span>
      <span
        v-if="current?.recommended"
        class="wf-badge"
        data-testid="studio-workflow-recommended"
      >推荐</span>
      <span class="wf-trigger__caret" aria-hidden="true">▾</span>
    </button>

    <div v-if="open" class="wf-menu">
      <div ref="listEl" class="wf-list" role="listbox" aria-label="本机工作流列表">
        <button
          v-for="item in workflows"
          :key="item.path"
          type="button"
          class="wf-option"
          :class="{ 'is-active': item.path === modelValue }"
          role="option"
          :aria-selected="item.path === modelValue"
          :title="item.path"
          @click="choose(item)"
        >
          <span v-if="item.recommended" class="wf-badge">推荐</span>
          <span class="wf-option__text">{{ optionLabel(item) }}</span>
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
  background: #0a0a0a;
  color: #fafafa;
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
  color: #a1a1a1;
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
  background: rgba(0, 188, 128, 0.15);
  color: #009966;
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
  max-height: 300px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-radius: 10px;
  background: #171717;
  box-shadow:
    0 0 0 1px var(--border-strong, var(--border)),
    0 12px 32px rgba(0, 0, 0, 0.45);
}

.wf-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0;
  overflow-y: auto;
}

/* 行 435.13 × 28、圆角 6、12px、内边距 6px 32px 6px 8px */
.wf-option {
  display: flex;
  align-items: center;
  gap: 4px;
  box-sizing: border-box;
  width: 100%;
  min-height: 28px;
  padding: 6px 32px 6px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #fafafa;
  font-size: 12px;
  line-height: 1.3;
  text-align: left;
  white-space: normal;
  word-break: break-all;
  cursor: pointer;
}

.wf-option:hover {
  background: rgba(255, 255, 255, 0.06);
}

.wf-option.is-active {
  background: var(--primary-soft, rgba(99, 102, 241, 0.16));
  color: #fafafa;
}

.wf-option:focus-visible {
  outline: 1px solid var(--primary);
  outline-offset: -1px;
}

.wf-option__text {
  min-width: 0;
}

.wf-empty {
  margin: 0;
  padding: 10px 8px;
  color: #a1a1a1;
  font-size: 11px;
  line-height: 1.6;
}
</style>