<script setup lang="ts">
import { computed } from 'vue'

import WorkflowParams from './WorkflowParams.vue'
import { useWorkflowAspectRatio } from '../composables/useWorkflowAspectRatio'
import { useWorkflowQuality } from '../composables/useWorkflowQuality'
import { useWorkflowCaps } from '../composables/useWorkflowCaps'
import { workflowDisplayName } from '../composables/recipeModel'
import type { WorkflowRow } from '../composables/useWorkflows'

/**
 * 横评的逐流参数行：每个勾选的工作流各自一套比例与画质档。
 *
 * 试跑弹窗与详情页横评共用同一份实现。比例 / 画质沿用「按工作流记忆」的
 * 同一份存储（`pb.aspectRatio:<path>`、`pb.quality:<path>`），所以这里改完，
 * 单跑与下次横评的默认值都跟着变，不需要再维护一套横评专用偏好。
 */
const props = defineProps<{
  path: string
  workflows: WorkflowRow[]
}>()

const pathRef = computed(() => props.path)
const ratio = useWorkflowAspectRatio(pathRef)
const quality = useWorkflowQuality(pathRef)
const allWorkflows = computed(() => props.workflows)
const { caps, qualityOptions, aspectRatios, defaultRatio } = useWorkflowCaps(
  pathRef, allWorkflows, ratio,
)

const name = computed(() => {
  const wf = props.workflows.find((w) => w.path === props.path)
  const raw = wf?.name ?? props.path.split(/[\\/]/).pop() ?? props.path
  return workflowDisplayName(raw).replace(/_/g, ' ')
})
</script>

<template>
  <div class="flow-row">
    <span class="flow-name" :title="path">{{ name }}</span>
    <WorkflowParams
      :quality="quality"
      :orientation="'portrait'"
      :aspect-ratio="ratio"
      :aspect-ratios="aspectRatios"
      :default-ratio="defaultRatio"
      :workflow-path="path"
      :caps="caps"
      :quality-options="qualityOptions"
      @update:quality="quality = $event"
      @update:aspect-ratio="ratio = $event"
    />
  </div>
</template>

<style scoped>
.flow-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--gap-sm);
  min-width: 0;
}

.flow-name {
  flex: 0 1 220px;
  min-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-sm);
  color: var(--text);
}
</style>
