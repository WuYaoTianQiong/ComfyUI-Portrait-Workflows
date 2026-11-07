<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'

import Modal from './Modal.vue'
import EmptyState from './EmptyState.vue'
import WorkflowPicker from './WorkflowPicker.vue'
import WorkflowParams from './WorkflowParams.vue'
import PromptCreateModal from './PromptCreateModal.vue'
import Lightbox from './Lightbox.vue'
import { thumbnailUrl } from '../api/client'
import { statusLabel } from '../utils/format'
import { useSettings } from '../composables/useSettings'
import { useWorkflowQuality } from '../composables/useWorkflowQuality'
import { useWorkflowAspectRatio } from '../composables/useWorkflowAspectRatio'
import { useWorkflowCaps } from '../composables/useWorkflowCaps'
import { useWorkflows, customWorkflowContent } from '../composables/useWorkflows'
import { useGenerate } from '../composables/useGenerate'
import { useImagePreview } from '../composables/useImagePreview'
import { useToast } from '../composables/useToast'

/**
 * 临时试跑面板。
 *
 * 打开就是空白的粘贴框，不依赖任何提示词（空库也能用）：粘贴一段外来文本，
 * 选工作流/张数/种子直接出图，不写回提示词库。结果就是日志 —— 每条都是真实
 * 任务行，有缩略图、种子和状态；满意了点「存为提示词」把当次实际文本预填进
 * 新建弹窗，试 → 存 的闭环在这里闭合。
 *
 * 归档关联是显式选择：默认不关联（档案标「临时提示词」），当前有选中提示词时
 * 才能显式挂到它名下；不做"文本相等才关联"的隐式魔法。
 */
const props = defineProps<{
  open: boolean
  /** 当前选中的提示词：只用于"归档到"选项，不再当载体预填文本。 */
  promptId: number | null
  promptName: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'created', id: number): void
}>()

const { workflowPath, orientation } = useSettings()
const quality = useWorkflowQuality(workflowPath)
const aspectRatio = useWorkflowAspectRatio(workflowPath)
const { workflows, allWorkflows } = useWorkflows()
const { caps, qualityOptions, aspectRatios, defaultRatio } = useWorkflowCaps(
  workflowPath, allWorkflows, aspectRatio,
)
const { busy, queue, error: runError, submitAndTrack } = useGenerate('prompt-trial', { queue: true })
const toast = useToast()
const queryClient = useQueryClient()

/** 本次输入：打开时清空，不继承任何提示词文本。 */
const promptText = ref('')
const negative = ref('')
const negativeExpanded = ref(false)
const count = ref(1)
const seedInput = ref('')
const linkArchive = ref(false)

watch(
  () => props.open,
  (open) => {
    if (!open) return
    promptText.value = ''
    negative.value = ''
    negativeExpanded.value = false
    count.value = 1
    seedInput.value = ''
    linkArchive.value = false
  },
)

/** 选中的提示词被切走/删掉时，归档选项必须跟着失效，避免挂到看不见的条目上。 */
watch(
  () => props.promptId,
  (id) => {
    if (!id) linkArchive.value = false
  },
)

const canRun = computed(() => promptText.value.trim().length > 0 && !!workflowPath.value)

const qualityLabel = computed(() => {
  if (!caps.value.quality) return '由工作流固定'
  return qualityOptions.value.find((o) => o.value === quality.value)?.label ?? quality.value
})

/**
 * 每张图的实际运行文本。
 *
 * 任务快照的 `JobItem` 只带 40 字预览，刷新后无法据此预填「存为提示词」，
 * 所以这里另存一份精简记录（job id → 文本/负向/种子），只服务本面板的保存闭环。
 */
interface RunRecord {
  prompt: string
  negative_prompt: string
  seed: number | null
}

const RUNS_KEY = 'pb.trialRuns'
const RUNS_LIMIT = 20
const LEGACY_LOG_KEY = 'pb.trialLog'

function loadRuns(): Record<string, RunRecord> {
  try {
    const raw = localStorage.getItem(RUNS_KEY)
    return raw ? (JSON.parse(raw) as Record<string, RunRecord>) : {}
  } catch {
    return {}
  }
}

const runs = ref<Record<string, RunRecord>>(loadRuns())

function rememberRun(jobId: number, record: RunRecord) {
  const next: Record<string, RunRecord> = { [String(jobId)]: record }
  for (const key of Object.keys(runs.value)) {
    if (key in next) continue
    if (Object.keys(next).length >= RUNS_LIMIT) break
    next[key] = runs.value[key]
  }
  runs.value = next
  try {
    localStorage.setItem(RUNS_KEY, JSON.stringify(next))
  } catch {
    /* 隐私模式下忽略 */
  }
}

function recordFor(jobId: number): RunRecord | null {
  return runs.value[String(jobId)] ?? null
}

onMounted(() => {
  // 旧版截断日志不再使用，顺手清掉这台机器上的残留
  try {
    localStorage.removeItem(LEGACY_LOG_KEY)
  } catch {
    /* 忽略 */
  }
})

function thumbUrl(image: { filename: string; subfolder?: string | null; type?: string | null }) {
  return thumbnailUrl(
    { filename: image.filename, subfolder: image.subfolder, img_type: image.type },
    240,
  )
}

/** 任务快照按"一任务一张"展示：本面板每次提交就是一个单图任务。 */
const rows = computed(() =>
  queue.value.map((job) => {
    const item = job.items?.[0] ?? null
    return {
      job,
      item,
      image: item?.images?.[0] ?? null,
      record: recordFor(job.id),
    }
  }),
)

const { items: previewItems, readonly: previewReadonly, open: previewOpen, preview, close: closePreview } =
  useImagePreview()

const saveOpen = ref(false)
const saveTarget = ref<RunRecord | null>(null)

function saveAsPrompt(jobId: number) {
  const record = recordFor(jobId)
  if (!record) return
  saveTarget.value = record
  saveOpen.value = true
}

function onCreated(id: number) {
  saveOpen.value = false
  emit('created', id)
}

async function runTrial() {
  if (!promptText.value.trim()) {
    toast.error('提示词是空的')
    return
  }
  if (!workflowPath.value) {
    toast.error('请先选择工作流')
    return
  }
  const n = Math.min(4, Math.max(1, count.value))
  const seedText = String(seedInput.value).trim()
  const base = seedText === '' ? null : Number(seedText)
  const sourceId = linkArchive.value && props.promptId ? props.promptId : 0
  const text = promptText.value
  const neg = negative.value

  // 并发提交：张数之间没有依赖，串行等只会多等几倍；种子依次 +1，图才有区别
  const results = await Promise.allSettled(
    Array.from({ length: n }, (_, i) => {
      const seed = base === null ? null : base + i
      return submitAndTrack<{ success: boolean; job_id?: number | null; seed?: number }>(
        '/api/runs/text',
        {
          prompt: text,
          negative_prompt: neg,
          workflow_path: workflowPath.value,
          workflow_content: customWorkflowContent(workflowPath.value),
          orientation: caps.value.orientation ? orientation.value : 'keep',
          quality: caps.value.quality ? quality.value : '1.0x',
          aspect_ratio: aspectRatio.value || defaultRatio.value,
          seed,
          source_prompt_id: sourceId,
        },
      ).then((result) => {
        if (result.job_id) {
          rememberRun(result.job_id, {
            prompt: text,
            negative_prompt: neg,
            seed: result.seed ?? seed,
          })
        }
        return result
      })
    }),
  )

  const failed = results.filter((r) => r.status === 'rejected')
  if (failed.length) {
    const reason = failed[0].status === 'rejected' ? failed[0].reason : ''
    toast.error(`跑图失败：${reason instanceof Error ? reason.message : String(reason)}`)
    return
  }
  toast.success(n > 1 ? `已提交 ${n} 张` : '已提交跑图')
}
</script>
<template>
  <Modal
    :open="open"
    title="临时试跑"
    width="min(720px, 94vw)"
    @close="emit('close')"
  >
    <div class="trial-body">
      <p class="note">
        粘贴想试的提示词直接出图，不写回提示词库；结果满意可在下方「存为提示词」。
      </p>

      <label class="field">
        <span>提示词</span>
        <textarea
          v-model="promptText"
          class="prompt-input"
          rows="6"
          spellcheck="false"
          placeholder="粘贴想试的提示词"
        />
      </label>

      <div class="neg">
        <div class="neg-head">
          <span>负面提示词</span>
          <span v-if="negative.trim() && caps.negative_effective === false" class="warn-text">
            负向不生效
          </span>
          <button class="btn btn-sm" @click="negativeExpanded = !negativeExpanded">
            {{ negativeExpanded ? '收起' : negative ? '展开' : '＋ 添加' }}
          </button>
        </div>
        <textarea
          v-if="negativeExpanded"
          v-model="negative"
          class="neg-input"
          rows="2"
          spellcheck="false"
          placeholder="可留空"
        />
        <button v-else-if="negative" class="neg-line" @click="negativeExpanded = true">
          {{ negative }}
        </button>
      </div>

      <div class="settings">
        <WorkflowPicker
          :model-value="workflowPath"
          :workflows="workflows"
          @update:model-value="workflowPath = $event"
        />
        <WorkflowParams
          :quality="quality"
          :orientation="orientation"
          :aspect-ratio="aspectRatio"
          :aspect-ratios="aspectRatios"
          :default-ratio="defaultRatio"
          :workflow-path="workflowPath"
          :caps="caps"
          :quality-options="qualityOptions"
          @update:quality="quality = $event"
          @update:orientation="orientation = $event"
          @update:aspect-ratio="aspectRatio = $event"
        />
        <span v-if="workflowPath && !caps.prompt" class="cap-hint warn" title="该工作流不注入提示词">
          不注入提示词
        </span>
      </div>

      <div class="controls">
        <div class="field">
          <span>张数</span>
          <span class="counts">
            <button
              v-for="n in [1, 2, 3, 4]"
              :key="n"
              class="btn btn-sm count-btn"
              :class="{ on: count === n }"
              @click="count = n"
            >
              {{ n }}
            </button>
          </span>
        </div>
        <label class="field seed-field">
          <span>种子（空 = 随机）</span>
          <input v-model="seedInput" type="number" min="0" step="1" placeholder="空 = 随机" />
        </label>
      </div>

      <div class="archive">
        <span class="archive-label">归档到：</span>
        <label class="radio">
          <input v-model="linkArchive" type="radio" :value="false" />
          不关联（临时提示词）
        </label>
        <label v-if="promptId" class="radio">
          <input v-model="linkArchive" type="radio" :value="true" />
          关联到《{{ promptName || `#${promptId}` }}》
        </label>
      </div>

      <p v-if="runError" class="note warn">{{ runError }}</p>

      <div class="actions">
        <span class="hint">
          画质 {{ qualityLabel }} ·
          {{ caps.orientation ? (aspectRatio || defaultRatio || '比例固定') : '方向固定' }}
        </span>
        <span class="spacer" />
        <button
          class="btn btn-sm primary"
          :class="{ loading: busy }"
          :disabled="busy || !canRun"
          @click="runTrial"
        >
          {{ busy ? '提交中…' : '▶ 跑图' }}
        </button>
      </div>

      <div class="results">
        <div class="results-head">
          <span>本次结果</span>
          <span v-if="rows.length" class="muted">{{ rows.length }} 个任务</span>
        </div>
        <div class="result-list">
          <div v-for="row in rows" :key="row.job.id" class="result-row">
            <button
              v-if="row.image"
              class="shot"
              type="button"
              :title="`查看原图：${row.image.filename}`"
              @click="preview(row.image)"
            >
              <img :src="thumbUrl(row.image)" :alt="row.image.filename" loading="lazy" />
            </button>
            <span v-else class="shot placeholder">…</span>
            <div class="result-body">
              <div class="result-line">
                <span :class="['st', row.job.status]">{{ statusLabel(row.job.status) }}</span>
                <span class="muted">{{ row.job.done_count ?? 0 }}/{{ row.job.total || 1 }}</span>
                <span class="muted">种子 {{ row.item?.seed ?? '随机' }}</span>
              </div>
              <div class="result-preview" :title="row.record?.prompt">
                {{ row.record?.prompt || row.item?.prompt_preview || '正在提交…' }}
              </div>
              <div v-if="row.item?.error" class="err">{{ row.item.error }}</div>
            </div>
            <button class="btn btn-sm" :disabled="!row.image" @click="row.image && preview(row.image)">
              看图
            </button>
            <button class="btn btn-sm" :disabled="!row.record" @click="saveAsPrompt(row.job.id)">
              存为提示词
            </button>
          </div>
          <EmptyState v-if="!rows.length" compact text="还没有试跑记录" />
        </div>
      </div>
    </div>
  </Modal>

  <Lightbox
    v-if="previewOpen"
    :items="previewItems"
    :index="0"
    :readonly="previewReadonly"
    :workflows="workflows"
    can-open-gallery
    @close="closePreview"
    @changed="queryClient.invalidateQueries({ queryKey: ['history'] })"
  />

  <PromptCreateModal
    :open="saveOpen"
    :initial="saveTarget"
    @close="saveOpen = false"
    @created="onCreated"
  />
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

.note.warn,
.warn-text {
  color: var(--warn);
}

.field {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  font-size: var(--fs-xs);
  color: var(--muted);
}

.prompt-input,
.neg-input {
  font: inherit;
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--gap-sm);
  resize: vertical;
  line-height: 1.6;
}

.prompt-input {
  min-height: 120px;
}

.neg-head {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-size: var(--fs-xs);
  color: var(--muted);
}

.neg-head .btn {
  margin-left: auto;
}

.neg-line {
  width: 100%;
  padding: 4px 0 4px var(--gap);
  text-align: left;
  background: transparent;
  border: none;
  border-left: 3px solid var(--danger);
  color: var(--text);
  font: inherit;
  font-size: var(--fs-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.settings {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-sm);
}

.cap-hint {
  font-size: var(--fs-xs);
  color: var(--muted);
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-pill);
  padding: 1px 7px;
}

.cap-hint.warn {
  color: var(--warn);
  border-color: var(--warn);
}

.controls {
  display: flex;
  align-items: flex-end;
  gap: var(--gap-lg);
}

.counts {
  display: flex;
  gap: 3px;
}

.count-btn.on {
  border-color: var(--primary);
  color: var(--primary);
}

.seed-field input {
  width: 120px;
}

.archive {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap);
  font-size: var(--fs-sm);
  color: var(--muted);
}

.archive-label {
  flex: none;
}

.radio {
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
  cursor: pointer;
}

.radio input {
  accent-color: var(--primary);
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

.results {
  border-top: 1px solid var(--border);
  padding-top: var(--gap);
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
}

.results-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--fs-sm);
  color: var(--muted);
}

.result-list {
  max-height: 260px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
}

.result-row {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: 5px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
}

.shot {
  flex: none;
  width: 52px;
  height: 52px;
  border-radius: var(--radius-sm);
  overflow: hidden;
  background: var(--panel-3);
  display: grid;
  place-items: center;
  color: var(--muted);
  font-size: var(--fs-xs);
  border: none;
  padding: 0;
  cursor: zoom-in;
}

.shot img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.result-body {
  flex: 1;
  min-width: 0;
}

.result-line {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-size: var(--fs-xs);
}

.result-preview {
  margin-top: 2px;
  font-size: var(--fs-xs);
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.st.done {
  color: var(--success);
}

.st.running,
.st.pending {
  color: var(--primary);
}

.st.error {
  color: var(--danger);
}

.muted {
  color: var(--muted);
  font-size: var(--fs-xs);
}

.err {
  margin-top: 2px;
  font-size: var(--fs-xs);
  color: var(--danger);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.btn.primary {
  border-color: var(--primary);
  background: var(--primary);
  color: rgb(255 255 255);
}

.btn.primary:disabled {
  opacity: 0.4;
  cursor: default;
}
</style>
