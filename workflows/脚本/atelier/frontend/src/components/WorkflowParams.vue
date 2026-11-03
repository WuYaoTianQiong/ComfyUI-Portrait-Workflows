<script setup lang="ts">
import { computed, watch } from 'vue'

import type { QualityOption, WorkflowCaps } from '../composables/useWorkflowCaps'

type Orientation = 'portrait' | 'landscape'

/**
 * 画质档位 + 横竖屏控件。
 *
 * 档位不是固定的 2K..12K：按工作流的实际作用方式生成（真实分辨率 / 倍率后的像素 / MP），
 * 工作流不支持时直接隐藏，而不是摆一个点了不生效的旋钮。
 *
 * 档位由调用方用 `useWorkflowCaps(...).qualityOptions` 算好后传进来 ——
 * 同一份档位逻辑只实现一次（`命名规范.md` §8.2）。
 */
const props = defineProps<{
  workflowPath: string
  caps: WorkflowCaps
  qualityOptions: QualityOption[]
  quality: string
  orientation: Orientation
  aspectRatios: string[]
  aspectRatio: string
  defaultRatio: string
}>()

const emit = defineEmits<{
  'update:quality': [value: string]
  'update:orientation': [value: Orientation]
  'update:aspectRatio': [value: string]
}>()

const options = computed(() => props.qualityOptions)
const ratioOptions = computed(() => props.aspectRatios)

const RATIO_LABELS: Record<string, string> = {
  '1:1': '1:1 方形',
  '2:3': '2:3 竖版',
  '3:2': '3:2 横版',
  '3:4': '3:4 竖版',
  '4:3': '4:3 标准',
  '9:16': '9:16 竖屏',
  '16:9': '16:9 宽屏',
  '21:9': '21:9 超宽',
  '9:21': '9:21 竖超宽',
}

const RECIPROCAL: Record<string, string> = {
  '2:3': '3:2',
  '3:2': '2:3',
  '3:4': '4:3',
  '4:3': '3:4',
  '9:16': '16:9',
  '16:9': '9:16',
  '21:9': '9:21',
  '9:21': '21:9',
}

function ratioLabel(ratio: string): string {
  const name = RATIO_LABELS[ratio] ?? ratio
  return ratio === props.defaultRatio ? `${name}（推荐）` : name
}

/** 换工作流后旧档位可能不在新列表里：退回标准档，避免给后端一个无效值。 */
watch(
  [options, () => props.quality],
  () => {
    if (!props.caps.quality || !options.value.length) return
    if (options.value.some((o) => o.value === props.quality)) return
    const fallback = options.value.find((o) => o.value === '4K') ?? options.value[0]
    emit('update:quality', fallback.value)
  },
  { immediate: true },
)

/** 比例同理：空值 / 不属于当前工作流的比例，回退到工作流默认比例。 */
watch(
  [ratioOptions, () => props.aspectRatio, () => props.defaultRatio],
  () => {
    if (!ratioOptions.value.length) return
    const fallback = ratioOptions.value.includes(props.defaultRatio)
      ? props.defaultRatio
      : ratioOptions.value[0]
    if (!props.aspectRatio || !ratioOptions.value.includes(props.aspectRatio)) {
      emit('update:aspectRatio', fallback)
    }
  },
  { immediate: true },
)

function onQuality(event: Event) {
  emit('update:quality', (event.target as HTMLSelectElement).value)
}

function onAspectRatio(event: Event) {
  emit('update:aspectRatio', (event.target as HTMLSelectElement).value)
}

function toggleOrientation() {
  const target = RECIPROCAL[props.aspectRatio]
  if (target) {
    emit('update:aspectRatio', target)
    return
  }
  emit('update:orientation', props.orientation === 'portrait' ? 'landscape' : 'portrait')
}

const canFlipRatio = computed(() => Boolean(RECIPROCAL[props.aspectRatio]))
const isLandscape = computed(() => {
  const [a, b] = props.aspectRatio.split(':').map(Number)
  return Boolean(a && b && a > b)
})
</script>

<template>
  <select
    v-if="caps.orientation && ratioOptions.length"
    class="wf-param-select wf-param-ratio"
    :value="aspectRatio"
    title="出图比例；标（推荐）的是工作流原生比例"
    @change="onAspectRatio"
  >
    <option v-for="ratio in ratioOptions" :key="ratio" :value="ratio">
      {{ ratioLabel(ratio) }}
    </option>
  </select>
  <select
    v-if="caps.quality && options.length"
    class="wf-param-select wf-param-quality"
    :value="quality"
    title="出图分辨率：原生 = 工作流基准；更高倍率只增加像素，不增加模型理解"
    @change="onQuality"
  >
    <option v-for="opt in options" :key="opt.value" :value="opt.value">
      {{ opt.label }}
    </option>
  </select>
  <button
    v-if="caps.orientation"
    class="btn btn-sm wf-flip"
    :disabled="!canFlipRatio"
    :title="canFlipRatio ? '切换横竖（互为倒数的比例）' : '当前比例没有横竖对'"
    @click="toggleOrientation"
  >
    {{ isLandscape ? '🖥️ 横' : '📱 竖' }}
  </button>
  <span
    v-if="workflowPath && !caps.quality"
    class="cap-hint"
    title="该工作流没有可调分辨率"
  >
    不支持画质
  </span>
  <span
    v-if="workflowPath && !caps.orientation"
    class="cap-hint"
    title="该工作流没有可调画幅"
  >
    不支持画幅
  </span>
</template>

<style scoped>
.wf-param-select {
  /* 按当前文案取自然宽度（field-sizing）；空间不足时按下面的优先级收缩 */
  flex: 0 1 auto;
  min-width: 0;
  max-width: 100%;
  field-sizing: content;
}

/* 比例文案短，先让出一部分宽度；分辨率是关键信息，整段保留 */
.wf-param-ratio {
  min-width: 118px;
}

.wf-param-quality {
  flex: 0 0 auto;
}

/* 图标 + 一个字，被压窄就会折成两行 */
.wf-flip {
  flex: none;
  white-space: nowrap;
}

.cap-hint {
  font-size: var(--fs-xs);
  color: var(--muted);
  flex: none;
  white-space: nowrap;
}

/* 单行放不下时让位给选择器，下方对应分区里还有同样的说明 */
@container (min-width: 1041px) and (max-width: 1260px) {
  .cap-hint {
    display: none;
  }
}
</style>
