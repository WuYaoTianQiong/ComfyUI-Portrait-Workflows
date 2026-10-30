<script setup lang="ts">
import { computed, ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'

import ImagePicker from '../components/ImagePicker.vue'
import { apiPost } from '../api/client'
import { useGenerate } from '../composables/useGenerate'
import { useSettings } from '../composables/useSettings'
import { useWorkflows } from '../composables/useWorkflows'
import { statusLabel } from '../utils/format'

/** 与后端 `faceswap.DEFAULT_PROMPT` 保持一致；留空提交时后端也会用这句。 */
const DEFAULT_PROMPT =
  '保持主图人物的姿势、构图、服装、背景与光线完全不变，' +
  '只把人物的面部替换成参考图中人物的脸，脸型与五官保持一致，自然真实，写实人像摄影，高清细节'

const { workflowPath } = useSettings()
const { workflows } = useWorkflows()
const { busy: generating, job: activeJob, error: generateError, track } = useGenerate()

const mainIds = ref<number[]>([])
const refIds = ref<number[]>([])

const pairMode = ref<'cross' | 'zip'>('cross')
const seedMode = ref<'fixed' | 'random' | 'increment'>('fixed')
const seed = ref(100000)
const promptText = ref('')

interface NodeInfo {
  loadimages: Array<{ id: string; title: string }>
  main: string | null
  ref: string | null
}

/** 探测工作流的 LoadImage 节点，提前暴露"只有一个 LoadImage"这类不可用配置。 */
const {
  data: nodeInfo,
  error: nodeError,
  isFetching: probing,
} = useQuery<NodeInfo>({
  queryKey: computed(() => ['fs-nodes', workflowPath.value]),
  queryFn: () => apiPost<NodeInfo>('/api/faceswap/nodes', { workflow_path: workflowPath.value }),
  enabled: computed(() => !!workflowPath.value),
  retry: false,
})

const comboCount = computed(() => {
  if (!mainIds.value.length || !refIds.value.length) return 0
  return pairMode.value === 'zip' ? mainIds.value.length : mainIds.value.length * refIds.value.length
})

const zipMismatch = computed(
  () => pairMode.value === 'zip' && mainIds.value.length !== refIds.value.length,
)

/**
 * 换脸工作流必须有两个 LoadImage（主图 + 参考图）。
 * 选到文生图工作流是常见误操作，这里提前拦住，不要等提交时报 400。
 */
const nodeReady = computed(() => !!(nodeInfo.value?.main && nodeInfo.value?.ref))

const canSubmit = computed(
  () =>
    !generating.value &&
    !!workflowPath.value &&
    nodeReady.value &&
    mainIds.value.length > 0 &&
    refIds.value.length > 0 &&
    !zipMismatch.value,
)

async function submit() {
  if (!canSubmit.value) return
  if (!confirm(`将提交 ${comboCount.value} 个换脸任务，确认继续？`)) return
  try {
    const result = await apiPost<{ success: boolean; job_id: number; total: number; submitted: number }>(
      '/api/faceswap/batch',
      {
        main_ids: mainIds.value,
        ref_ids: refIds.value,
        workflow_path: workflowPath.value,
        prompt: promptText.value,
        seed_mode: seedMode.value,
        seed: seed.value,
        pair_mode: pairMode.value,
      },
    )
    if (result.success) track(result.job_id)
  } catch (e) {
    alert(`提交失败：${e instanceof Error ? e.message : String(e)}`)
  }
}
</script>

<template>
  <div class="faceswap">
    <ImagePicker v-model="mainIds" title="主图（保留姿势/服装/背景）" />
    <ImagePicker v-model="refIds" title="参考图（提供面部）" />

    <aside class="panel">
      <div class="section">
        <span class="label">工作流</span>
        <select v-model="workflowPath">
          <option value="">选择换脸工作流…</option>
          <option v-for="wf in workflows" :key="wf.path" :value="wf.path">{{ wf.name }}</option>
        </select>
      </div>

      <div class="section nodes">
        <span class="label">节点映射</span>
        <template v-if="probing">探测中…</template>
        <div v-else-if="nodeError" class="err-text">{{ nodeError.message }}</div>
        <template v-else-if="nodeInfo">
          <div v-if="nodeReady" class="node-row">
            <span class="node-role">主图</span>
            <span class="node-id">{{ nodeInfo.main }}</span>
            <span class="node-role">参考</span>
            <span class="node-id">{{ nodeInfo.ref }}</span>
          </div>
          <div v-else class="err-text">
            这个工作流只有 {{ nodeInfo.loadimages.length }} 个 LoadImage，
            不是换脸工作流，请换一个（换脸工作流需要两个 LoadImage 分别接主图与参考图）
          </div>
          <div class="node-list">
            LoadImage 节点 {{ nodeInfo.loadimages.length }} 个：
            {{ nodeInfo.loadimages.map((n) => n.id).join(' / ') || '无' }}
          </div>
        </template>
      </div>

      <div class="section">
        <span class="label">组合方式</span>
        <div class="seg">
          <button class="btn btn-sm" :class="{ active: pairMode === 'cross' }" @click="pairMode = 'cross'">
            全组合
          </button>
          <button class="btn btn-sm" :class="{ active: pairMode === 'zip' }" @click="pairMode = 'zip'">
            1:1 配对
          </button>
        </div>
        <div class="hint">
          全组合 = 主图 × 参考图的笛卡尔积；1:1 = 按两侧选中顺序一一对应
        </div>
        <div v-if="zipMismatch" class="err-text">
          1:1 配对要求两侧数量相同（当前 {{ mainIds.length }} vs {{ refIds.length }}）
        </div>
      </div>

      <div class="section">
        <span class="label">种子</span>
        <div class="seg">
          <button class="btn btn-sm" :class="{ active: seedMode === 'fixed' }" @click="seedMode = 'fixed'">
            固定
          </button>
          <button class="btn btn-sm" :class="{ active: seedMode === 'increment' }" @click="seedMode = 'increment'">
            递增
          </button>
          <button class="btn btn-sm" :class="{ active: seedMode === 'random' }" @click="seedMode = 'random'">
            随机
          </button>
        </div>
        <input v-if="seedMode !== 'random'" v-model.number="seed" type="number" class="seed-input" />
      </div>

      <label class="section">
        <span class="label">提示词（留空使用内置换脸提示）</span>
        <textarea v-model="promptText" spellcheck="false" :placeholder="DEFAULT_PROMPT" />
        <button class="btn btn-sm" @click="promptText = DEFAULT_PROMPT">填入默认提示词</button>
      </label>

      <div class="summary">
        <span>将生成</span>
        <b>{{ comboCount }}</b>
        <span>张（{{ mainIds.length }} 主图 × {{ refIds.length }} 参考图）</span>
      </div>

      <div class="actions">
        <span v-if="generateError" class="err-text">{{ generateError }}</span>
        <span v-else-if="activeJob" class="job-state" :class="activeJob.status">
          {{ statusLabel(activeJob.status) }} {{ activeJob.done_count ?? 0 }}/{{ activeJob.total ?? 1 }}
        </span>
        <span class="spacer" />
        <button class="btn btn-sm primary" :disabled="!canSubmit" @click="submit">
          {{ generating ? '提交中…' : '🚀 开始换脸' }}
        </button>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.faceswap {
  display: flex;
  height: 100%;
  min-height: 0;
}

.faceswap > :deep(.picker) {
  flex: 1;
  min-width: 0;
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

.seg {
  display: flex;
  gap: var(--gap-xs);
}

.seg .btn {
  flex: 1;
}

.nodes {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--gap-sm);
  font-size: var(--fs-xs);
}

.node-row {
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
}

.node-role {
  color: var(--muted);
}

.node-id {
  font-family: ui-monospace, monospace;
  color: var(--primary);
  margin-right: var(--gap-sm);
}

.node-list {
  color: var(--muted);
  margin-top: 2px;
}

.hint {
  font-size: 10px;
  color: var(--muted);
  line-height: 1.5;
}

.err-text {
  font-size: var(--fs-xs);
  color: var(--danger);
}

.seed-input {
  width: 130px;
}

textarea {
  min-height: 84px;
  resize: vertical;
  font: inherit;
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--gap-sm);
  outline: none;
}

.summary {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: var(--fs-sm);
  color: var(--muted);
  border-top: 1px solid var(--border);
  padding-top: var(--gap-sm);
}

.summary b {
  font-size: var(--fs-xl);
  color: var(--primary);
}

.actions {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-size: var(--fs-xs);
}

.spacer {
  flex: 1;
}

.job-state {
  color: var(--muted);
}

.job-state.running,
.job-state.pending {
  color: var(--primary);
}

.job-state.done {
  color: var(--success);
}

.job-state.error {
  color: var(--danger);
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
