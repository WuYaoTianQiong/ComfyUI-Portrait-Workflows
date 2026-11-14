<script setup lang="ts">
import WorkflowPicker from './WorkflowPicker.vue'
import Icon from './Icon.vue'
import WorkflowParams from './WorkflowParams.vue'
import type { JobSnapshot } from '../api/types'
import type { QualityOption, WorkflowCaps } from '../composables/useWorkflowCaps'
import type { WorkflowRow } from '../composables/useWorkflows'

/**
 * 组合器顶部控制条：检索、筛选、工作流/画质、结果与随机入口、提交状态。
 *
 * 状态全部由 ComposerView 持有；这里只做呈现与事件转发。
 */
defineProps<{
  search: string
  filtersOpen: boolean
  filterCount: number
  fragmentTotal: number
  isFetching: boolean
  workflowPath: string
  workflows: WorkflowRow[]
  quality: string
  orientation: 'portrait' | 'landscape'
  aspectRatio: string
  aspectRatios: string[]
  defaultRatio: string
  qualityOptions: QualityOption[]
  caps: WorkflowCaps
  canvasCount: number
  negativePrompt: string
  negativeEffective: boolean
  negativeTip: string
  templatesCount: number
  pinnedCount: number
  generating: boolean
  generateErrorText: string
  activeCount: number
  activeJob: JobSnapshot | null
}>()

const emit = defineEmits<{
  'update:search': [value: string]
  'update:workflow-path': [value: string]
  'update:quality': [value: string]
  'update:orientation': [value: 'portrait' | 'landscape']
  'update:aspect-ratio': [value: string]
  'toggle-filters': []
  'open-result': []
  'open-negative': []
  'open-compile': []
  'open-templates': []
  'roll-one': []
  'preview-random': []
  'run-once': []
  'open-job-tab': []
}>()

function onSearchInput(event: Event) {
  emit('update:search', (event.target as HTMLInputElement).value)
}
</script>

<template>
  <div class="composer-bar">
    <input
      :value="search"
      class="bar-search"
      type="search"
      placeholder="检索碎片内容…"
      @input="onSearchInput"
    />
    <button
      class="btn btn-sm"
      :class="{ on: filtersOpen || filterCount }"
      @click="emit('toggle-filters')"
    >
      筛选<template v-if="filterCount"> · {{ filterCount }}</template>
    </button>
    <span class="count">
      碎片 {{ fragmentTotal }}<span v-if="isFetching"> · 加载中</span>
    </span>
    <div class="bar-wf">
      <WorkflowPicker
        :model-value="workflowPath"
        :workflows="workflows"
        @update:model-value="emit('update:workflow-path', $event)"
      />
    </div>
    <WorkflowParams
      :quality="quality"
      :orientation="orientation"
      :aspect-ratio="aspectRatio"
      :aspect-ratios="aspectRatios"
      :default-ratio="defaultRatio"
      :workflow-path="workflowPath"
      :caps="caps"
      :quality-options="qualityOptions"
      @update:quality="emit('update:quality', $event)"
      @update:orientation="emit('update:orientation', $event)"
      @update:aspect-ratio="emit('update:aspect-ratio', $event)"
    />
    <button
      class="btn btn-sm"
      :class="{ on: canvasCount }"
      title="查看组合结果（画布 / 随机组 / 任务结果）"
      @click="emit('open-result')"
    >
      组合结果 · {{ canvasCount }} 个碎片
    </button>
    <button
      class="btn btn-sm"
      :class="{ on: !!negativePrompt.trim(), 'cap-off': !negativeEffective }"
      :title="negativeTip"
      @click="emit('open-negative')"
    >
      <Icon name="ban" /> 负面提示词
      <span v-if="!negativeEffective" class="cap-badge">不生效</span>
    </button>
    <button
      class="btn btn-sm"
      :disabled="!canvasCount"
      title="查看编译后的正向/负向（只编译，不出图）"
      @click="emit('open-compile')"
    >
      <Icon name="code-2" /> 编译
    </button>
    <button class="btn btn-sm" @click="emit('open-templates')">
      <Icon name="library" /> 模板 {{ templatesCount }}
    </button>
    <button class="btn btn-sm" title="随机抽一版并滚动定位，不出图" @click="emit('roll-one')">
      <Icon name="dices" /> 随机一版
    </button>
    <button
      class="btn btn-sm"
      :title="pinnedCount ? `锁定 ${pinnedCount} 列，其余随机` : '预览随机组合，确认后才出图'"
      @click="emit('preview-random')"
    >
      <Icon name="dices" /> 预览
    </button>
    <button
      class="btn btn-sm primary"
      :class="{ loading: generating }"
      :disabled="generating || !canvasCount"
      @click="emit('run-once')"
    >
      <Icon v-if="!generating" name="play" /> {{ generating ? '提交中…' : '试跑' }}
    </button>
    <span v-if="generateErrorText" class="gen-error">{{ generateErrorText }}</span>
    <button
      v-if="activeCount"
      class="job-state queue"
      :title="`${activeCount} 个任务排队中（ComfyUI 顺序出图），点开看进度`"
      @click="emit('open-job-tab')"
    >
      队列 {{ activeCount }}
    </button>
    <span v-if="activeJob" class="job-state" :class="activeJob.status">
      {{ activeJob.status }} {{ activeJob.done_count ?? 0 }}/{{ activeJob.total ?? 1 }}
    </span>
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

.composer-bar {
  flex: none;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--gap);
  padding: 6px var(--gap-lg);
  border-bottom: 1px solid var(--border);
  font-size: var(--fs-sm);
}

.composer-bar .on {
  color: var(--primary);
}

.count {
  color: var(--muted);
  font-size: var(--fs-xs);
}

.bar-search {
  flex: 1 1 220px;
  min-width: 160px;
}

/* 工作流和画质是出图时始终有效的状态，常驻控制条中段（原来收在设置浮层里，
   宽屏时控制条中间反而空出一大块）。WorkflowPicker 自带可搜索下拉，比原生 select 好认长文件名。
   搜索框和它一起做弹性项，把剩余宽度分摊掉，避免行尾留白。 */
.bar-wf {
  flex: 1 1 220px;
  min-width: 150px;
}

/* 组件自带的 max-width 会在超宽屏下卡住选择器、反而在行尾留白 */
.bar-wf :deep(.wf-picker) {
  max-width: none;
}

.cap-badge {
  margin-left: var(--gap-xs);
  padding: 0 var(--gap-xs);
  border: 1px solid currentColor;
  border-radius: var(--radius-sm);
  font-size: var(--fs-xs);
  line-height: var(--lh-lg);
  color: var(--warn);
}

.btn.cap-off {
  opacity: 0.75;
}

.gen-error {
  color: var(--danger);
  font-size: var(--fs-xs);
}

.job-state {
  color: var(--muted);
  font-size: var(--fs-xs);
}

/* 「队列 N」是个按钮（点心开结果中心），去掉浏览器默认外观 */
.job-state.queue {
  border: 1px solid var(--primary);
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--primary);
  padding: 1px 8px;
  cursor: pointer;
  transition:
    color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease),
    background-color var(--dur-fast) var(--ease);
}
</style>