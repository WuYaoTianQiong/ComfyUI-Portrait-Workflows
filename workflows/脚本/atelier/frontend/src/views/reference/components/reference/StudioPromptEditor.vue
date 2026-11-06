<!--
  提示词分段编辑器（P3，方案 §14）。

  设计依据（不设「阅读态 / 编辑态」两套 UI）：
  - Direct manipulation：对象本身可操作，每段直接是 textarea，改完立即生效；
  - User control & freedom：非空修改才写入 `prompt_override`，随时可「恢复自动生成」；
  - Visibility of system status：顶部常显「自动生成 / 已手动修改」与字数；
  - 渐进披露：不再重复渲染顶部目录，段标题 + 来源已足够定位。

  纯受控：`modelValue === null` = 内容跟随自动生成；字符串 = 用户改过的原文。
-->
<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import {
  composePromptSegments,
  parsePromptSegments,
  segmentDisplayLabel,
  segmentSourceHint,
  segmentTone,
} from '../../../../composables/promptSegments'
import type { PromptSegment } from '../../../../composables/promptSegments'
import type { RecipeSupplementFlags } from '../../../../composables/recipeTextFragments'

const props = withDefaults(
  defineProps<{
    /** 后端 dry-run 编译后的正向提示词（自动模式的数据源）。 */
    prompt: string
    /** `null` = 跟随自动生成；字符串 = 用户改过的原文。 */
    modelValue: string | null
    /** 槽位模式：text 槽的来源提示写成「文本替代」。 */
    slotModes?: Partial<Record<'portrait' | 'costume' | 'pose', string>>
    /** P4：image 模式只有补充开关打开才显示「图片 + 补充碎片」。 */
    supplementFlags?: RecipeSupplementFlags
    loading?: boolean
    error?: string
  }>(),
  { slotModes: undefined, supplementFlags: undefined, loading: false, error: '' },
)

const emit = defineEmits<{
  'update:modelValue': [value: string | null]
  retry: []
}>()

/** 是否有用户改动：只有非 null 才作为 `prompt_override` 提交。 */
const dirty = computed(() => props.modelValue !== null)

/** 当前渲染的段。 */
const segments = ref<PromptSegment[]>([])

/** 编辑器根节点：只在本组件内查询 / 撑高 textarea。 */
const rootRef = ref<HTMLElement | null>(null)

/** 总字数：只算正文，不含 `• 标签：` 前缀。 */
const totalChars = computed(() =>
  segments.value.reduce((sum, segment) => sum + segment.text.trim().length, 0),
)

/** 手动内容全空：直接提示，避免提交时才在结果区报错。 */
const manualEmpty = computed(
  () => dirty.value && !segments.value.some((segment) => segment.text.trim()),
)

/**
 * 把后端提示词解析成可编辑段。
 *
 * 始终补出「开头 / 结尾」：后端正常情况下首尾都有文字，但只有 bullet 的提示词
 * 仍要能补开头或结尾，否则用户没有入口。
 */
function buildEditableSegments(source: string): PromptSegment[] {
  const editable = [...parsePromptSegments(source)]
  if (!editable.some((segment) => segment.kind === 'head')) {
    editable.unshift({ id: 'head', label: '', text: '', kind: 'head' })
  }
  if (!editable.some((segment) => segment.kind === 'tail')) {
    editable.push({ id: 'tail', label: '', text: '', kind: 'tail' })
  }
  return editable
}

function syncFromPrompt(): void {
  segments.value = buildEditableSegments(props.prompt)
  void nextTick(autoGrowTextareas)
}

function syncFromValue(source: string): void {
  segments.value = buildEditableSegments(source)
  void nextTick(autoGrowTextareas)
}

// 自动生成刷新：用户没改过时才覆盖输入框；改过则保留，避免吞掉编辑。
watch(
  () => props.prompt,
  () => {
    if (!dirty.value) syncFromPrompt()
  },
)

/**
 * 受控回流：外部清空（恢复自动）或写入新原文时同步。
 * 与本地拼装结果相同则不动，避免每次输入都把光标重置到末尾。
 */
watch(
  () => props.modelValue,
  (value) => {
    if (value === null) {
      if (composePromptSegments(segments.value) !== props.prompt) syncFromPrompt()
      return
    }
    if (value !== composePromptSegments(segments.value)) syncFromValue(value)
  },
  { immediate: true },
)

/**
 * 按内容撑高 textarea，避免长碎片在框内出现第二层滚动条。
 * 先归零再读 scrollHeight，否则缩短内容后高度只增不减。
 */
function autoGrowTextareas(): void {
  const inputs = rootRef.value?.querySelectorAll<HTMLTextAreaElement>('[data-segment-input]')
  inputs?.forEach((input) => {
    const border = input.offsetHeight - input.clientHeight
    input.style.height = 'auto'
    // box-sizing: border-box；scrollHeight 不含边框，补上才不出现 2px 内滚。
    input.style.height = `${input.scrollHeight + Math.max(0, border)}px`
  })
}

/** 任一段输入：拼回完整原文并回传，进入 / 保持手动修改状态。 */
function emitManualText(): void {
  autoGrowTextareas()
  emit('update:modelValue', composePromptSegments(segments.value))
}

/** 恢复自动生成：清空 override，回到碎片驱动。 */
function restoreAuto(): void {
  emit('update:modelValue', null)
}

/** 段色调枚举 → CSS 类名（颜色只在组件样式里用 var(--token)，不出现色值）。 */
function toneClass(segment: PromptSegment): string {
  return `prompt-segment--${segmentTone(segmentDisplayLabel(segment))}`
}

/** 标签对应的槽位键（人物 / 服装 / 姿势），其它返回 null。 */
function slotKeyOf(label: string): 'portrait' | 'costume' | 'pose' | null {
  if (label.startsWith('人物')) return 'portrait'
  if (label.startsWith('服装')) return 'costume'
  if (label.startsWith('姿势')) return 'pose'
  return null
}

/** 段来源：text 槽写「文本替代」；image 槽按补充开关写「图片」/「图片 + 补充碎片」。 */
function sourceHint(segment: PromptSegment): string {
  const label = segmentDisplayLabel(segment)
  const key = slotKeyOf(label)
  if (key) {
    // 槽位模式缺省按 image（旧调用方行为）；image 下只有补充开关打开才写「+ 补充碎片」。
    const mode = props.slotModes?.[key] ?? 'image'
    if (mode === 'text') return '文本替代'
    return props.supplementFlags?.[key] ? '图片 + 补充碎片' : '图片'
  }
  return segmentSourceHint(label)
}

/** 空段给一个可操作的占位提示；有内容时不显示。 */
function placeholderOf(segment: PromptSegment): string {
  if (segment.kind === 'head') return '填写开头…'
  if (segment.kind === 'tail') return '填写结尾约束…'
  return `填写${segment.label || '本段'}…`
}

/** textarea 初始行数：按内容长度估，最少 2 行、最多 10 行；随后自动撑高。 */
function segmentRows(segment: PromptSegment): number {
  const length = segment.text.length
  if (!length) return 2
  return Math.min(10, Math.max(2, Math.ceil(length / 52)))
}
</script>

<template>
  <div
    ref="rootRef"
    class="prompt-editor"
    :data-dirty="dirty ? 'true' : 'false'"
    data-testid="studio-prompt-editor"
  >
    <div class="prompt-editor__bar">
      <span
        class="prompt-editor__state-badge"
        :class="dirty ? 'is-dirty' : 'is-auto'"
        :data-testid="dirty ? 'studio-prompt-dirty-badge' : 'studio-prompt-auto-badge'"
      >
        {{ dirty ? '已手动修改' : '自动生成' }}
      </span>
      <span v-if="segments.length" class="prompt-editor__meta" data-testid="studio-prompt-meta">
        共 {{ segments.length }} 段 · {{ totalChars }} 字
      </span>
      <button
        v-if="dirty"
        type="button"
        class="prompt-editor__btn"
        data-testid="studio-prompt-restore"
        @click="restoreAuto"
      >
        恢复自动生成
      </button>
    </div>

    <p class="prompt-editor__hint" data-testid="studio-prompt-mode-hint">
      <template v-if="dirty">当前按你改后的原文提交，不再二次编译；素材或碎片变化不会覆盖它。</template>
      <template v-else>每段都可直接编辑；改动任意一段后，整段按原文提交。</template>
    </p>

    <p v-if="loading" class="prompt-editor__state" data-testid="studio-prompt-loading">
      正在生成提示词预览…
    </p>

    <div v-else-if="error" class="prompt-editor__error" role="alert">
      <span class="prompt-editor__error-text" data-testid="studio-prompt-error">{{ error }}</span>
      <button
        type="button"
        class="prompt-editor__btn"
        data-testid="studio-prompt-retry"
        @click="emit('retry')"
      >
        重试
      </button>
    </div>

    <p v-else-if="!prompt.trim()" class="prompt-editor__state" data-testid="studio-prompt-empty">
      三槽均未选择：选择任一参考图后将在此显示后端组合出的提示词。
    </p>

    <div v-else class="prompt-editor__segments">
      <article
        v-for="segment in segments"
        :key="segment.id"
        class="prompt-segment"
        :class="toneClass(segment)"
        :data-testid="`studio-prompt-segment-${segment.id}`"
      >
        <header class="prompt-segment__head">
          <span
            class="prompt-segment__label"
            :data-testid="`studio-prompt-segment-label-${segment.id}`"
          >
            {{ segmentDisplayLabel(segment) }}
          </span>
          <span
            class="prompt-segment__source"
            :data-testid="`studio-prompt-segment-source-${segment.id}`"
          >
            {{ sourceHint(segment) }}
          </span>
          <span class="prompt-segment__chars" :data-testid="`studio-prompt-chars-${segment.id}`">
            {{ segment.text.trim().length }} 字
          </span>
        </header>
        <textarea
          v-model="segment.text"
          class="prompt-segment__input"
          :rows="segmentRows(segment)"
          :placeholder="placeholderOf(segment)"
          :aria-label="`${segmentDisplayLabel(segment)}段内容`"
          :data-segment-input="segment.id"
          :data-testid="`studio-prompt-segment-input-${segment.id}`"
          @input="emitManualText"
        />
      </article>

      <p
        v-if="manualEmpty"
        class="prompt-editor__error"
        role="alert"
        data-testid="studio-prompt-manual-empty"
      >
        手动改写内容为空：填写任意一段，或点「恢复自动生成」。
      </p>
    </div>
  </div>
</template>

<style scoped>
.prompt-editor {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  box-sizing: border-box;
  width: 100%;
}

.prompt-editor__bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-sm);
}

/* 状态徽标：自动 / 已修改，文字优先可读 */
.prompt-editor__state-badge {
  padding: 2px 8px;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-pill);
  font-size: var(--fs-sm);
  line-height: var(--lh-md);
}

.prompt-editor__state-badge.is-auto {
  background: var(--fill-subtle);
  color: var(--text-muted);
}

.prompt-editor__state-badge.is-dirty {
  background: var(--primary-soft);
  color: var(--text-strong);
}

.prompt-editor__meta {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: var(--lh-md);
  font-variant-numeric: tabular-nums;
}

.prompt-editor__btn {
  padding: 4px 10px;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-sm);
  background: var(--fill-subtle);
  color: var(--text-body);
  font-size: var(--fs-sm);
  line-height: var(--lh-md);
  cursor: pointer;
}

.prompt-editor__btn:hover:not(:disabled) {
  background: var(--fill-medium);
  color: var(--text-strong);
}

.prompt-editor__btn:focus-visible {
  outline: 1px solid var(--primary);
  outline-offset: 1px;
}

.prompt-editor__hint {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: var(--lh-md);
}

.prompt-editor__segments {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}

.prompt-segment {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  box-sizing: border-box;
  padding: 8px 10px;
  border: 1px solid var(--border-faint);
  border-radius: var(--radius);
  background: var(--surface-raised);
}

/* 段类型用左侧色条区分：人物 / 服装 / 姿势 / 修饰 */
.prompt-segment--portrait {
  border-left: 3px solid var(--tone-blue);
}

.prompt-segment--costume {
  border-left: 3px solid var(--tone-green);
}

.prompt-segment--pose {
  border-left: 3px solid var(--tone-violet);
}

.prompt-segment--modifier {
  border-left: 3px solid var(--warn);
}

.prompt-segment__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-sm);
}

/* 彩色标签放在名称前：色条用 tone 令牌，文字保持高对比 */
.prompt-segment__label {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-xs);
  color: var(--text-strong);
  font-size: var(--fs-sm);
  font-weight: 600;
  line-height: var(--lh-md);
}

.prompt-segment__label::before {
  content: '';
  width: 3px;
  height: 12px;
  border-radius: var(--radius-pill);
  background: var(--text-muted);
}

.prompt-segment--portrait .prompt-segment__label::before {
  background: var(--tone-blue);
}

.prompt-segment--costume .prompt-segment__label::before {
  background: var(--tone-green);
}

.prompt-segment--pose .prompt-segment__label::before {
  background: var(--tone-violet);
}

.prompt-segment--modifier .prompt-segment__label::before {
  background: var(--warn);
}

.prompt-segment--neutral .prompt-segment__label::before {
  background: var(--text-muted);
}

.prompt-segment__source {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: var(--lh-md);
}

.prompt-segment__chars {
  margin-left: auto;
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: var(--lh-md);
  font-variant-numeric: tabular-nums;
}

/* 每段就是输入框：边框即「可编辑」的可见暗示 */
.prompt-segment__input {
  box-sizing: border-box;
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-sm);
  background: var(--surface-deep);
  color: var(--text-strong);
  font-family: inherit;
  font-size: var(--fs-sm);
  line-height: var(--lh-md);
  overflow: hidden;
  resize: none;
}

.prompt-segment__input::placeholder {
  color: var(--text-disabled);
}

.prompt-segment__input:hover {
  border-color: var(--border-hover);
}

.prompt-segment__input:focus-visible {
  outline: 1px solid var(--primary);
  outline-offset: 1px;
}

.prompt-editor__state {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: var(--lh-md);
}

.prompt-editor__error {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-sm);
  color: var(--danger-text-soft);
  font-size: var(--fs-sm);
  line-height: var(--lh-md);
}

.prompt-editor__error-text {
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
