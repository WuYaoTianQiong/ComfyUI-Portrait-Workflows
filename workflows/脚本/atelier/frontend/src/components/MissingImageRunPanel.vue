<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'

import { apiGet, apiPost } from '../api/client'
import Modal from './Modal.vue'
import EmptyState from './EmptyState.vue'
import { useSettings } from '../composables/useSettings'
import { useWorkflowCaps } from '../composables/useWorkflowCaps'
import WorkflowParams from './WorkflowParams.vue'
import { useGenerate } from '../composables/useGenerate'
import { useWorkflows, customWorkflowContent } from '../composables/useWorkflows'
import { useToast } from '../composables/useToast'

/**
 * 批量补跑：给「有提示词但没出图」的条目补图。
 *
 * 缺图判定在后端（DB 关联），前端只负责列清单、勾选、提交、跟踪进度。
 * 每条提示词用的是它自己保存的参数（steps/cfg/采样器/分辨率），
 * 这里传的 workflow_path / quality / orientation 只决定走哪个工作流与画幅。
 */
const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()

interface MissingItem {
  id: number
  name: string
  category: string
  steps: number | null
  cfg_scale: number | null
  sampler: string | null
  model: string | null
  width: number | null
  height: number | null
}

const { workflowPath, quality, orientation } = useSettings()
const { workflows, allWorkflows } = useWorkflows()
const { caps, qualityOptions } = useWorkflowCaps(workflowPath, allWorkflows)
const { track } = useGenerate()
const toast = useToast()
const queryClient = useQueryClient()

const { data, isFetching } = useQuery<{ items: MissingItem[] }>({
  queryKey: ['generate-missing'],
  queryFn: () => apiGet('/api/generate_missing/list'),
  enabled: computed(() => props.open),
})

const items = computed<MissingItem[]>(() => data.value?.items ?? [])
const selected = ref<Set<number>>(new Set())

/** 默认全选：补跑的默认语义就是"全都补上"，用户可以再取消个别条目。 */
watch(
  () => items.value,
  (list) => {
    selected.value = new Set(list.map((i) => i.id))
  },
  { immediate: true },
)

const allSelected = computed(
  () => items.value.length > 0 && selected.value.size === items.value.length,
)

function toggle(id: number) {
  const next = new Set(selected.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selected.value = next
}

function toggleAll() {
  selected.value = allSelected.value ? new Set() : new Set(items.value.map((i) => i.id))
}

const submitting = ref(false)

async function submit() {
  if (!workflowPath.value) {
    toast.error('请先选择工作流')
    return
  }
  if (!selected.value.size) {
    toast.error('请至少勾选一条')
    return
  }
  submitting.value = true
  try {
    const result = await apiPost<{
      success: boolean
      job_id: number | null
      count: number
      message?: string
    }>('/api/generate_missing', {
      prompt_ids: Array.from(selected.value),
      workflow_path: workflowPath.value,
      // 自定义工作流不在后端磁盘上，内容必须一起带过去
      workflow_content: customWorkflowContent(workflowPath.value),
      quality: caps.value.quality ? quality.value : '4K',
      orientation: caps.value.orientation ? orientation.value : 'keep',
    })
    if (!result.job_id) {
      toast.info(result.message || '没有需要补跑的条目')
      emit('close')
      return
    }
    track(result.job_id)
    toast.success(`已提交 ${result.count} 条补跑任务，可在「任务」页看进度`)
    emit('close')
    queryClient.invalidateQueries({ queryKey: ['history'] })
  } catch (e) {
    toast.error(`提交失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    submitting.value = false
  }
}
</script>
<template>
  <Modal :open="open" title="批量补跑缺图" @close="emit('close')">
      <template #head>
        <span class="count">
          {{ items.length }} 条缺图<template v-if="isFetching"> · 加载中</template>
        </span>
      </template>

      <div class="toolbar">
        <label class="check">
          <input type="checkbox" :checked="allSelected" @change="toggleAll" />
          <span>全选（已选 {{ selected.size }}）</span>
        </label>
        <span class="spacer" />
        <select v-model="workflowPath" class="wf-select">
          <option value="">选择工作流…</option>
          <option v-for="wf in workflows" :key="wf.path" :value="wf.path">{{ wf.name }}</option>
        </select>
        <WorkflowParams
          v-model:quality="quality"
          v-model:orientation="orientation"
          :workflow-path="workflowPath"
          :caps="caps"
          :quality-options="qualityOptions"
        />
      </div>

      <div class="list">
        <label v-for="item in items" :key="item.id" class="item">
          <input type="checkbox" :checked="selected.has(item.id)" @change="toggle(item.id)" />
          <span class="name">{{ item.name }}</span>
          <span class="cat">{{ item.category || '未分类' }}</span>
          <span class="params">
            <template v-if="item.steps">{{ item.steps }}步</template>
            <template v-if="item.width && item.height"> · {{ item.width }}×{{ item.height }}</template>
            <template v-if="item.sampler"> · {{ item.sampler }}</template>
          </span>
        </label>
        <EmptyState
          v-if="!items.length && !isFetching"
          text="没有缺图的提示词 —— 全部都已经出过图了"
        />
      </div>

      <template #footer>
        <span class="hint">每条提示词用它自己保存的参数出图；这里只决定工作流与画幅。</span>
        <span class="spacer" />
        <button
          class="btn btn-sm primary"
          :disabled="submitting || !selected.size || !workflowPath"
          @click="submit"
        >
          {{ submitting ? '提交中…' : `补跑 ${selected.size} 条` }}
        </button>
      </template>
  </Modal>
</template>

<style scoped>




.count {
  font-size: var(--fs-xs);
  color: var(--muted);
}

.spacer {
  flex: 1;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm) var(--gap-lg);
  border-bottom: 1px solid var(--border);
}

.check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-sm);
  cursor: pointer;
}

.wf-select {
  width: 230px;
}

.list {
  flex: 1;
  overflow-y: auto;
  padding: var(--gap-sm) var(--gap-lg);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.item {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: 4px 6px;
  border-radius: var(--radius-sm);
  font-size: var(--fs-sm);
  cursor: pointer;
}

.item:hover {
  background: var(--panel-2);
}

.name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cat {
  font-size: var(--fs-xs);
  color: var(--muted);
  flex: none;
}

.params {
  font-size: 10px;
  color: var(--muted);
  flex: none;
  width: 200px;
  text-align: right;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.empty {
  padding: var(--gap-lg);
  text-align: center;
  color: var(--muted);
  font-size: var(--fs-sm);
}


.hint {
  font-size: var(--fs-xs);
  color: var(--muted);
}

.btn.primary {
  border-color: var(--primary);
  background: var(--primary);
  color: #fff;
}

.btn.primary:disabled {
  opacity: 0.4;
  cursor: default;
}
</style>