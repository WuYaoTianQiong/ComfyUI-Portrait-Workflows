<script setup lang="ts">
/**
 * 合成台底部操作条（方案 §5 M6）。
 *
 * - 桌面：右栏内 `position: sticky; bottom: 0`（背景 `--surface-raised` + 上边框 + 8px 内边距）；
 * - `<1024px`：改为 `position: fixed` 全宽吸底（z-index 60）。
 *
 * 左：总数 + 维度明细（超限转危险色）；右：随机捏人（次）+ 生成角色图（主，44px）。
 *
 * 批量提交前二次确认：任何一维 > 1 都要确认，单张直接提交，避免日常操作被打断。
 * 组件本身只负责交互，真正的提交由父组件监听 `submit` 后完成。
 */

import { computed } from 'vue'

import { countSlotCombinations } from '../../../../composables/useReferenceRecipe'
import { createImageSlotModes } from '../../../../composables/recipeTextFragments'
import type { RecipeSlotModes } from '../../../../composables/recipeTextFragments'
import { CONFIRM_PROMPTS } from '../../../../utils/confirmKeys'
import { confirmDialog } from '../../../../utils/naive'

const props = defineProps<{
  /** 全组合总数（父组件的计数口径，已含所有维度）。 */
  total: number
  portraitCount: number
  costumeCount: number
  poseCount: number
  workflowCount: number
  qualityCount: number
  ratioCount: number
  overLimit: boolean
  limitMessage: string
  canSubmit: boolean
  submitting: boolean
  libraryLoading: boolean
  /** P4 整套随机请求中：禁用入口，避免连续点击。 */
  recipeLoading?: boolean
  /** P4 跨源实验请求中：禁用入口。 */
  atomicLoading?: boolean
  /** 三槽模式（P2）：文本槽不参与图片维度计数。缺省 = 全 image。 */
  slotModes?: RecipeSlotModes
  /** v1.5：人物 B 变体数；与 A 人像按序号 1:1 配对，不乘成乘积。 */
  personBVariantCount?: number
}>()

const emit = defineEmits<{ randomize: []; randomizeRecipe: []; randomizeAtomic: []; submit: [] }>()

/**
 * 槽位组合数：与提交口径一致。
 *
 * 空维度按 1 计（例如只选了人像 2 张 → 2 × 1 × 1 = 2）；
 * 三槽全空为 0，和后端拒绝 M==0 的行为一致。
 */
const slotCombos = computed(() =>
  countSlotCombinations(
    {
      portrait: props.portraitCount,
      costume: props.costumeCount,
      pose: props.poseCount,
    },
    props.slotModes ?? createImageSlotModes(),
    props.personBVariantCount ?? 0,
  ),
)

/** 维度明细：人像4 × 服装2 × 姿势3 = 24，×1 工作流 ×1 尺寸（文本槽折叠为 1）。 */
const detailText = computed(() => {
  const modes = props.slotModes ?? createImageSlotModes()
  const dimension = (slot: 'portrait' | 'costume' | 'pose', count: number): string => {
    if (modes[slot] === 'text') return '文本'
    return String(count)
  }
  const variants = props.personBVariantCount ?? 0
  const variantNote = variants
    ? `（人像与 B 变体按序号 1:1 配对，共 ${Math.max(1, props.portraitCount, variants)} 对）`
    : ''
  return (
    `人像${dimension('portrait', props.portraitCount)} × ` +
    `服装${dimension('costume', props.costumeCount)} × ` +
    `姿势${dimension('pose', props.poseCount)} = ${slotCombos.value}${variantNote}，` +
    `×${props.workflowCount} 工作流 ×${props.qualityCount} 尺寸`
  )
})

/** 只读展示用：提交按钮的禁用条件（整套随机 / 跨源实验进行中也拒绝提交）。 */
const submitDisabled = computed(
  () =>
    !props.canSubmit ||
    props.submitting ||
    props.overLimit ||
    props.recipeLoading ||
    props.atomicLoading,
)

/** 任一维度 > 1 才需要确认（`total === 1` 时必然全为 1，直接提交）。 */
const needsConfirm = computed(
  () =>
    props.total > 1 ||
    props.workflowCount > 1 ||
    props.qualityCount > 1 ||
    props.ratioCount > 1,
)

async function onSubmit(): Promise<void> {
  if (submitDisabled.value) return

  // 单张：不弹确认，直接交给父组件提交。
  if (!needsConfirm.value) {
    emit('submit')
    return
  }

  const confirmed = await confirmDialog({
    title: '确认批量提交',
    content:
      `将提交 ${props.total} 张（人像${props.portraitCount} × 服装${props.costumeCount} × ` +
      `姿势${props.poseCount}，${props.workflowCount} 工作流 × ${props.qualityCount} 尺寸），确认继续？`,
    positiveText: '继续提交',
    negativeText: '取消',
    rememberKey: CONFIRM_PROMPTS.studioBatchSubmit.key,
  })
  // 取消（含点遮罩 / 关闭 ×）一律不发 submit。
  if (!confirmed) return
  emit('submit')
}
</script>

<template>
  <div class="action-bar" data-testid="studio-action-bar">
    <div class="action-bar__summary">
      <p class="action-bar__total" :class="{ 'is-over': overLimit }">将生成 {{ total }} 张</p>
      <p class="action-bar__detail" :class="{ 'is-over': overLimit }">{{ detailText }}</p>
      <p
        v-if="overLimit"
        class="action-bar__blocked"
        role="alert"
        data-testid="studio-generate-blocked"
      >
        {{ limitMessage }}
      </p>
    </div>

    <div class="action-bar__actions">
      <button
        type="button"
        class="action-bar__secondary"
        data-testid="studio-random"
        :disabled="libraryLoading"
        :title="libraryLoading ? '图库加载中，请稍候' : '从三个库中各随机抽取一条'"
        @click="emit('randomize')"
      >
        随机捏人
      </button>
      <button
        type="button"
        class="action-bar__secondary"
        data-testid="studio-random-recipe"
        :disabled="libraryLoading || recipeLoading"
        :title="
          libraryLoading
            ? '图库加载中，请稍候'
            : '从完整配方池中抽一套，姿势图锚定，其余 7 类文本生效'
        "
        @click="emit('randomizeRecipe')"
      >
        {{ recipeLoading ? '整套随机中…' : '同源整套随机' }}
      </button>
      <button
        type="button"
        class="action-bar__secondary"
        data-testid="studio-random-atomic"
        :disabled="libraryLoading || atomicLoading"
        :title="
          libraryLoading
            ? '图库加载中，请稍候'
            : '从原子碎片库跨源组合（实验，建议人工复核）'
        "
        @click="emit('randomizeAtomic')"
      >
        {{ atomicLoading ? '跨源实验中…' : '跨源实验' }}
      </button>
      <button
        type="button"
        class="action-bar__primary"
        data-testid="studio-generate"
        :disabled="submitDisabled"
        @click="onSubmit"
      >
        <span v-if="submitting" class="action-bar__spinner" aria-hidden="true" />
        {{ submitting ? '提交中…' : '生成角色图' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
/*
 * 桌面：fixed 常驻吸底，左侧避开 rail（--rail-effective-w 随折叠切换）。
 * 不再用 sticky：sticky 元素位于文档流末尾，首屏看不见生成按钮。
 */
.action-bar {
  position: fixed;
  left: calc(var(--page-gutter, 32px) + var(--rail-effective-w, 180px) + 24px);
  right: var(--page-gutter, 32px);
  bottom: 0;
  z-index: 40;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px 16px;
  box-sizing: border-box;
  width: auto;
  min-width: 0;
  padding: 8px;
  border-top: 1px solid var(--border);
  background: var(--surface-raised);
}

.action-bar__summary {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.action-bar__total {
  margin: 0;
  color: var(--text-strong);
  font-size: 14px;
  font-weight: 600;
  line-height: 1.4;
}

.action-bar__detail {
  margin: 0;
  color: var(--text-body-soft);
  font-size: 12px;
  line-height: 1.5;
}

/* 超限：数字与明细原地转危险色，不整块变色 */
.action-bar__total.is-over,
.action-bar__detail.is-over {
  color: var(--danger-text-soft);
}

.action-bar__blocked {
  margin: 0;
  color: var(--danger-text-soft);
  font-size: 12px;
  line-height: 1.5;
}

.action-bar__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

/* 次按钮：36px / 圆角 8 / 描边 */
.action-bar__secondary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: transparent;
  color: var(--text-strong);
  font-size: 13px;
  font-weight: 500;
  line-height: 1;
  white-space: nowrap;
  cursor: pointer;
}

.action-bar__secondary:hover:not(:disabled) {
  background: var(--fill-subtle);
}

.action-bar__secondary:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* 主按钮：44px / 圆角 8 / 14px 600 / 反色底 */
.action-bar__primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  box-sizing: border-box;
  height: 44px;
  padding: 0 18px;
  border: 0;
  border-radius: 8px;
  background: var(--btn-inverse-bg);
  color: var(--on-inverse);
  font-size: 14px;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
  cursor: pointer;
}

.action-bar__primary:hover:not(:disabled) {
  background: var(--btn-inverse-bg-hover-strong);
}

.action-bar__primary:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.action-bar__secondary:focus-visible,
.action-bar__primary:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

.action-bar__spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--spinner-track-inverse);
  border-top-color: var(--on-inverse);
  border-radius: 50%;
  animation: action-bar-spin 0.8s linear infinite;
}

@keyframes action-bar-spin {
  to {
    transform: rotate(360deg);
  }
}

/* <1024：全宽吸底（覆盖桌面 rail 偏移） */
@media (max-width: 1023px) {
  .action-bar {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 60;
  }
}
</style>