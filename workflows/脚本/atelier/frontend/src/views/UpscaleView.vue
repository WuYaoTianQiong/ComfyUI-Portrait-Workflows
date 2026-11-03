<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useQuery } from '@tanstack/vue-query'

import ImagePicker from '../components/ImagePicker.vue'
import DiskPathList from '../components/DiskPathList.vue'
import FilePicker from '../components/FilePicker.vue'
import { apiPost } from '../api/client'
import { useGenerate } from '../composables/useGenerate'
import { useSettings } from '../composables/useSettings'
import { useWorkflows, customWorkflowContent } from '../composables/useWorkflows'
import { useWorkflowCaps } from '../composables/useWorkflowCaps'
import { useWorkflowQuality } from '../composables/useWorkflowQuality'
import { useToast } from '../composables/useToast'
import { readSession, writeSession } from '../composables/useSessionState'
import { statusLabel } from '../utils/format'

/**
 * 批量超分：多选图片 → 选工作流和档位 → 逐张提交 ComfyUI。
 *
 * 与「图像编辑」的区别：这里只做单图进 / 单图出，没有参考图、遮罩、提示词、
 * 种子与组合方式。提交仍复用 `/api/editor/faceswap/batch`（单 LoadImage 工作流
 * 天然就是单目标图），任务类型保持 faceswap 以沿用现有的失败重试链路。
 */

interface UpscaleSession {
  ids: number[]
  paths: string[]
}

const SESSION_KEY = 'pb.session.upscale'
const saved = readSession<Partial<UpscaleSession>>(SESSION_KEY, {})

/** 画廊多选（历史图 id）与磁盘多选（绝对路径），两组按顺序合并提交。 */
const ids = ref<number[]>(saved.ids ?? [])
const paths = ref<string[]>(saved.paths ?? [])
watch(
  [ids, paths],
  () => writeSession(SESSION_KEY, { ids: ids.value, paths: paths.value }),
  { deep: true },
)

const { upscaleWorkflowPath: workflowPath } = useSettings()
const { workflows, allWorkflows } = useWorkflows()
const quality = useWorkflowQuality(workflowPath)
const { caps, qualityOptions } = useWorkflowCaps(workflowPath, allWorkflows)
const { busy: submitting, job: activeJob, error: submitError, submitAndTrack } =
  useGenerate('', { queue: true })
const toast = useToast()

const pickerOpen = ref(false)
const total = computed(() => ids.value.length + paths.value.length)

interface NodeInfo {
  loadimages: Array<{ id: string; title: string }>
  inputs: Array<{ role: string; id: string }>
}

/** 探测工作流：批量超分只接受 1 个 LoadImage（多图编辑工作流请走「图像编辑」）。 */
const { data: nodeInfo, error: nodeError, isFetching: probing } = useQuery<NodeInfo>({
  queryKey: computed(() => ['upscale-nodes', workflowPath.value]),
  queryFn: () =>
    apiPost<NodeInfo>('/api/editor/faceswap/nodes', { workflow_path: workflowPath.value }),
  enabled: computed(() => !!workflowPath.value),
  retry: false,
})

const loadCount = computed(() => nodeInfo.value?.loadimages.length ?? 0)

const nodeMessage = computed(() => {
  if (!workflowPath.value) return '先选择一个超分工作流'
  if (probing.value) return '探测工作流中…'
  if (nodeError.value) return nodeError.value.message
  if (!nodeInfo.value) return ''
  if (loadCount.value === 0) return '该工作流没有 LoadImage，不能投喂图片'
  if (loadCount.value > 1) {
    return `该工作流有 ${loadCount.value} 个 LoadImage，批量超分只支持 1 个`
  }
  return ''
})

const nodeReady = computed(() => loadCount.value === 1)

/** 换工作流后旧档位可能不在新列表里：退回 4K，避免给后端无效值。 */
watch(
  [qualityOptions, quality],
  () => {
    if (!caps.value.quality || !qualityOptions.value.length) return
    if (qualityOptions.value.some((opt) => opt.value === quality.value)) return
    quality.value =
      qualityOptions.value.find((opt) => opt.value === '4K')?.value ??
      qualityOptions.value[0].value
  },
  { immediate: true },
)

const canSubmit = computed(
  () => !submitting.value && !!workflowPath.value && nodeReady.value && total.value > 0,
)

async function submit() {
  if (!canSubmit.value) return
  try {
    const result = await submitAndTrack<{
      success: boolean
      job_id: number
      total: number
      queued?: number
    }>('/api/editor/faceswap/batch', {
      main_ids: ids.value,
      main_paths: paths.value,
      workflow_path: workflowPath.value,
      // 自定义工作流的内容只在本地，提交时必须一起带上
      workflow_content: customWorkflowContent(workflowPath.value),
      quality: caps.value.quality ? quality.value : '',
      job_label: '批量超分',
      // 保留原文件名，SaveImageFromSource 才能把源图名写进成品名
      clean_source_name: true,
    })
    if (!result.success) toast.error('提交失败')
    else toast.success(`已加入提交队列（${result.queued ?? result.total} 张）`)
  } catch (e) {
    toast.error(`提交失败：${e instanceof Error ? e.message : String(e)}`)
  }
}
</script>

<template>
  <div class="upscale">
    <div class="picker-col">
      <div class="picker-head">
        <span>待超分图片（画廊多选）</span>
        <span class="count">已选 {{ total }} 张</span>
        <button class="btn btn-sm" title="从磁盘任意目录多选图片" @click="pickerOpen = true">
          📁 磁盘<template v-if="paths.length"> {{ paths.length }}</template>
        </button>
      </div>
      <ImagePicker v-model="ids" title="" />
    </div>

    <aside class="panel">
      <div class="section">
        <span class="label">超分工作流</span>
        <select v-model="workflowPath">
          <option value="">选择超分工作流…</option>
          <option v-for="wf in workflows" :key="wf.path" :value="wf.path">{{ wf.name }}</option>
        </select>
      </div>

      <div class="section">
        <span class="label">节点检查</span>
        <div v-if="nodeReady && nodeInfo" class="node-row">
          <span class="node-role">输入图</span>
          <span class="node-id">{{ nodeInfo.loadimages[0].id }}</span>
        </div>
        <div v-else class="hint" :class="{ 'err-text': !!nodeError || loadCount > 1 }">
          {{ nodeMessage }}
        </div>
      </div>

      <div class="section">
        <span class="label">输出档位</span>
        <select
          v-if="workflowPath && caps.quality && qualityOptions.length"
          v-model="quality"
          title="超分档位直接对应真实输出分辨率"
        >
          <option v-for="opt in qualityOptions" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </option>
        </select>
        <div v-else class="hint">
          {{ workflowPath ? '该工作流没有可调档位，按工作流自身设置输出' : '先选择工作流' }}
        </div>
      </div>

      <div class="section disk-section">
        <span class="label">磁盘图（{{ paths.length }}）</span>
        <div v-if="!paths.length" class="hint">点上方「📁 磁盘」从任意文件夹多选</div>
        <div v-else class="disk-list">
          <DiskPathList v-model="paths" />
        </div>
      </div>

      <div class="summary">
        <span>将超分</span>
        <b>{{ total }}</b>
        <span>张</span>
      </div>

      <div class="actions">
        <span v-if="submitError" class="err-text">{{ submitError }}</span>
        <span v-else-if="activeJob" class="job-state" :class="activeJob.status">
          {{ statusLabel(activeJob.status) }} {{ activeJob.done_count ?? 0 }}/{{ activeJob.total ?? 1 }}
        </span>
        <span class="spacer" />
        <button
          class="btn btn-sm primary"
          :class="{ loading: submitting }"
          :disabled="!canSubmit"
          @click="submit"
        >
          {{ submitting ? '提交中…' : '🚀 开始超分' }}
        </button>
      </div>
    </aside>

    <FilePicker
      v-model="paths"
      :open="pickerOpen"
      title="从磁盘选要超分的图片"
      @close="pickerOpen = false"
    />
  </div>
</template>

<style scoped>
.upscale {
  display: flex;
  height: 100%;
  min-height: 0;
}

.upscale > :deep(.picker) {
  flex: 1;
  min-width: 0;
}

.picker-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.picker-head {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm) var(--gap);
  font-size: var(--fs-sm);
  border-bottom: 1px solid var(--border);
}

.picker-head .count {
  color: var(--muted);
  font-size: var(--fs-xs);
}

.picker-head .btn {
  margin-left: auto;
}

.panel {
  width: 340px;
  flex: none;
  background: var(--panel);
  padding: var(--gap);
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  overflow-y: auto;
}

.section {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  font-size: var(--fs-sm);
}

.label {
  color: var(--muted);
  font-size: var(--fs-xs);
}

.hint {
  color: var(--muted);
  font-size: var(--fs-xs);
}

.err-text {
  color: var(--danger);
  font-size: var(--fs-xs);
}

.node-row {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-size: var(--fs-xs);
}

.node-role {
  color: var(--muted);
}

.node-id {
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  background: var(--panel-2);
}

/* 磁盘图分区吃掉右栏剩余高度，图多时只在列表内滚动 */
.disk-section {
  flex: 1 1 auto;
  min-height: 0;
}

.disk-list {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 120px;
  min-width: 0;
  overflow: hidden;
  padding-right: 2px;
}

.summary {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: var(--fs-sm);
}

.summary b {
  color: var(--primary);
  font-size: var(--fs-lg);
}

.actions {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  margin-top: auto;
}

.spacer {
  flex: 1;
}

.job-state {
  font-size: var(--fs-xs);
  color: var(--muted);
}

.job-state.error {
  color: var(--danger);
}

.job-state.done {
  color: var(--primary);
}
</style>
