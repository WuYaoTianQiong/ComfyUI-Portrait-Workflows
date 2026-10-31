<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { apiPost } from '../api/client'
import Modal from './Modal.vue'
import EmptyState from './EmptyState.vue'
import { useSettings } from '../composables/useSettings'
import { useWorkflowCaps } from '../composables/useWorkflowCaps'
import { useWorkflows, customWorkflowContent } from '../composables/useWorkflows'
import { useToast } from '../composables/useToast'

/**
 * 试跑 / 变体生成（面板）。
 *
 * 试跑：用当前草稿的文本出图，但**不写回提示词库** —— 试的就是"临时改的那版"。
 * 变体：同一条提示词换种子出多张，用来挑手感。
 *
 * 试跑日志记在 localStorage：这台机器上"我试过什么、结果如何"是本地的事，
 * 不该进数据库。
 */
const props = defineProps<{
  open: boolean
  prompt: string
  negativePrompt: string
  promptId: number | null
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

interface TrialRecord {
  id: number
  at: string
  kind: 'trial' | 'variant'
  seed: number
  jobId: number | null
  count: number
  preview: string
}

const LOG_KEY = 'pb.trialLog'

function loadLog(): TrialRecord[] {
  try {
    const raw = localStorage.getItem(LOG_KEY)
    return raw ? (JSON.parse(raw) as TrialRecord[]) : []
  } catch {
    return []
  }
}

const log = ref<TrialRecord[]>(loadLog())

function saveLog() {
  try {
    localStorage.setItem(LOG_KEY, JSON.stringify(log.value.slice(0, 20)))
  } catch {
    /* 隐私模式下 localStorage 可能不可用，忽略即可 */
  }
}

const { workflowPath, quality, orientation } = useSettings()
const { allWorkflows } = useWorkflows()
const { caps, qualityOptions } = useWorkflowCaps(workflowPath, allWorkflows)
const toast = useToast()

/** 面板里只展示当前档位对应的真实尺寸/MP，不支持画质时写明"由工作流固定"。 */
const qualityLabel = computed(() => {
  if (!caps.value.quality) return '由工作流固定'
  return qualityOptions.value.find((o) => o.value === quality.value)?.label ?? quality.value
})

/** 变体张数（1~4）与种子（0 = 随机）。 */
const variantCount = ref(2)
const seed = ref(0)
const busy = ref(false)

watch(
  () => props.open,
  (open) => {
    if (open) log.value = loadLog()
  },
)

const canRun = computed(() => props.prompt.trim().length > 0 && !!workflowPath.value)

function record(kind: 'trial' | 'variant', usedSeed: number, jobId: number | null, count: number) {
  log.value = [
    {
      id: Date.now(),
      at: new Date().toLocaleString('zh-CN', { hour12: false }),
      kind,
      seed: usedSeed,
      jobId,
      count,
      preview: props.prompt.slice(0, 60),
    },
    ...log.value,
  ].slice(0, 20)
  saveLog()
}

async function runTrial() {
  if (!canRun.value) {
    toast.error(!workflowPath.value ? '请先选择工作流' : '提示词是空的')
    return
  }
  busy.value = true
  try {
    const result = await apiPost<{ success: boolean; job_id: number }>('/api/run_text', {
      prompt: props.prompt,
      negative_prompt: props.negativePrompt,
      workflow_path: workflowPath.value,
      workflow_content: customWorkflowContent(workflowPath.value),
      orientation: caps.value.orientation ? orientation.value : 'keep',
      quality: caps.value.quality ? quality.value : '4K',
      seed: seed.value,
      // 与「改文本跑」一致：出图仍关联回当前提示词
      source_prompt_id: props.promptId ?? 0,
    })
    record('trial', seed.value, result.job_id ?? null, 1)
    toast.success('已提交试跑，可在「任务」页看进度')
  } catch (e) {
    toast.error(`试跑失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    busy.value = false
  }
}

async function runVariants() {
  if (!canRun.value) {
    toast.error(!workflowPath.value ? '请先选择工作流' : '提示词是空的')
    return
  }
  busy.value = true
  const count = Math.min(4, Math.max(1, variantCount.value))
  // 并发提交：变体之间没有依赖，串行等会让用户多等几倍时间
  const results = await Promise.allSettled(
    Array.from({ length: count }, (_, i) => {
      // 种子为 0 时交给后端随机；指定种子时依次 +1，出来的图才有区别
      const useSeed = seed.value ? seed.value + i : 0
      return apiPost<{ success: boolean; job_id: number }>('/api/run_text', {
        prompt: props.prompt,
        negative_prompt: props.negativePrompt,
        workflow_path: workflowPath.value,
        workflow_content: customWorkflowContent(workflowPath.value),
        orientation: caps.value.orientation ? orientation.value : 'keep',
        quality: caps.value.quality ? quality.value : '4K',
        seed: useSeed,
        source_prompt_id: props.promptId ?? 0,
      }).then((result) => {
        record('variant', useSeed, result.job_id ?? null, 1)
        return result
      })
    }),
  )
  const submitted = results.filter((r) => r.status === 'fulfilled').length
  busy.value = false
  toast.success(submitted ? `已提交 ${submitted} 张变体` : '变体提交失败')
}

function clearLog() {
  log.value = []
  saveLog()
}
</script>
<template>
  <Modal
    :open="open"
    title="试跑 / 变体生成"
    width="min(680px, 92vw)"
    @close="emit('close')"
  >
    <div class="trial-body">
      <p class="note">
        试跑用的就是当前草稿的文本，不会写回提示词库 —— 试完满意再保存。
      </p>

      <div class="controls">
        <label class="field">
          <span>种子（0 = 随机）</span>
          <input v-model.number="seed" type="number" min="0" step="1" />
        </label>
        <div class="field">
          <span>变体张数</span>
          <span class="counts">
            <button
              v-for="n in [1, 2, 3, 4]"
              :key="n"
              class="btn btn-sm count-btn"
              :class="{ on: variantCount === n }"
              @click="variantCount = n"
            >
              {{ n }}
            </button>
          </span>
        </div>
      </div>

      <div class="actions">
        <button
          class="btn btn-sm primary"
          :class="{ loading: busy }"
          :disabled="busy || !canRun"
          @click="runTrial"
        >
          {{ busy ? '提交中…' : '🧪 试跑一张' }}
        </button>
        <button
          class="btn btn-sm"
          :class="{ loading: busy }"
          :disabled="busy || !canRun"
          @click="runVariants"
        >
          {{ busy ? '提交中…' : '生成 ' + variantCount + ' 张变体' }}
        </button>
        <span class="spacer" />
        <span class="hint">
          画质 {{ qualityLabel }} ·
          {{ caps.orientation ? (orientation === 'portrait' ? '竖图' : '横图') : '方向固定' }}
        </span>
      </div>

      <div class="log-head">
        <span>试跑日志</span>
        <button v-if="log.length" class="btn btn-sm" @click="clearLog">清空</button>
      </div>
      <div class="log">
        <div v-for="r in log" :key="r.id" class="log-row">
          <span class="log-kind" :class="r.kind">{{ r.kind === 'trial' ? '试跑' : '变体' }}</span>
          <span class="log-at">{{ r.at }}</span>
          <span class="log-seed">种子 {{ r.seed || '随机' }}</span>
          <span class="log-preview" :title="r.preview">{{ r.preview }}</span>
        </div>
        <EmptyState v-if="!log.length" text="还没有试跑记录" compact />
      </div>
    </div>
  </Modal>
</template>

<style scoped>
.trial-body {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  padding: var(--gap-lg);
}

.note {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--muted);
  line-height: 1.6;
}

.controls {
  display: flex;
  gap: var(--gap);
}

.controls .field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--fs-xs);
  color: var(--muted);
}

.controls input {
  width: 120px;
}

.counts {
  display: flex;
  gap: 3px;
}

.count-btn.on {
  border-color: var(--primary);
  color: var(--primary);
}

.actions {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
}

.spacer {
  flex: 1;
}

.hint {
  font-size: var(--fs-xs);
  color: var(--muted);
}

.log-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--fs-sm);
  color: var(--muted);
  border-top: 1px solid var(--border);
  padding-top: var(--gap);
}

.log {
  max-height: 220px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.log-row {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-size: var(--fs-xs);
  padding: 3px 0;
  border-bottom: 1px solid var(--border);
}

.log-kind {
  flex: none;
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  color: var(--muted);
}

.log-kind.variant {
  border-color: var(--primary);
  color: var(--primary);
}

.log-at {
  flex: none;
  color: var(--muted);
  width: 130px;
}

.log-seed {
  flex: none;
  color: var(--muted);
  width: 70px;
}

.log-preview {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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