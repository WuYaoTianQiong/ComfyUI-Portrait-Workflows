<script setup lang="ts">
import { computed, watch } from 'vue'

import { qualityOptionsFor, type WorkflowCaps, type WorkflowParams } from '../utils/workflowCaps'

type Orientation = 'portrait' | 'landscape'

/**
 * 画质档位 + 横竖屏控件。
 *
 * 档位不是固定的 2K..12K：按工作流的实际作用方式生成（真实分辨率 / 倍率后的像素 / MP），
 * 工作流不支持时直接隐藏，而不是摆一个点了不生效的旋钮。
 */
const props = defineProps<{
  workflowPath: string
  caps: WorkflowCaps
  params?: WorkflowParams
  quality: string
  orientation: Orientation
}>()

const emit = defineEmits<{
  'update:quality': [value: string]
  'update:orientation': [value: Orientation]
}>()

const options = computed(() => qualityOptionsFor(props.params, props.caps))

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

function onQuality(event: Event) {
  emit('update:quality', (event.target as HTMLSelectElement).value)
}

function toggleOrientation() {
  emit('update:orientation', props.orientation === 'portrait' ? 'landscape' : 'portrait')
}
</script>

<template>
  <select
    v-if="caps.quality && options.length"
    class="wf-param-select"
    :value="quality"
    title="出图分辨率（按当前工作流的实际尺寸换算）"
    @change="onQuality"
  >
    <option v-for="opt in options" :key="opt.value" :value="opt.value">
      {{ opt.label }}
    </option>
  </select>
  <button
    v-if="caps.orientation"
    class="btn btn-sm"
    title="横竖屏"
    @click="toggleOrientation"
  >
    {{ orientation === 'portrait' ? '📱 竖' : '🖥️ 横' }}
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
    title="该工作流没有横竖比旋钮"
  >
    不支持横竖
  </span>
</template>

<style scoped>
.wf-param-select {
  max-width: 190px;
  flex: none;
}

.cap-hint {
  font-size: var(--fs-xs);
  color: var(--muted);
  flex: none;
}
</style>
