<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'

import Modal from './Modal.vue'
import Icon from './Icon.vue'
import WorkflowPicker from './WorkflowPicker.vue'
import WorkflowParams from './WorkflowParams.vue'
import PromptMatrixStack from './PromptMatrixStack.vue'
import PromptCreateModal from './PromptCreateModal.vue'
import CompareModal from './CompareModal.vue'
import Lightbox from './Lightbox.vue'
import { useSettings } from '../composables/useSettings'
import { useWorkflowQuality } from '../composables/useWorkflowQuality'
import { useWorkflowAspectRatio } from '../composables/useWorkflowAspectRatio'
import { useWorkflowCaps } from '../composables/useWorkflowCaps'
import { useWorkflows, customWorkflowContent } from '../composables/useWorkflows'
import { useGenerate } from '../composables/useGenerate'
import { usePromptMatrix } from '../composables/usePromptMatrix'
import { useImagePreview, resolveHistoryItems } from '../composables/useImagePreview'
import { useToast } from '../composables/useToast'
import { linkImagesToPrompt } from '../api/images'
import { apiGet } from '../api/client'
import type { HistoryItem, JobSnapshot } from '../api/types'
import type { MatrixAlign, MatrixImage } from '../composables/useWorkflowMatrix'
import type { MatrixBatch } from '../composables/usePromptMatrix'

/**
 * 临时试跑工作台。
 *
 * 与详情页横评的分工：详情页跑**库内提示词**，这里跑**外来文本**（不写回库，
 * 空库也能用）。两者共用 `usePromptMatrix` 一套引擎，多选、逐流档位回退、
 * 同种子、一格一 job、矩阵结果的口径完全一致，不用学两套。
 *
 * 左右双栏：左边文本吃满弹窗高度（长提示词不用反复滚动），
 * 右边参数常驻 + 结果堆叠。结果矩阵按列=工作流转置，
 * 竖图并排吃满右栏宽度，不再是旧版 300px 窄条留白。
 * 文本与结果同屏，改一句话就能再跑一轮对比。
 *
 * 闭环：跑 → 满意 → 「存为提示词」新建一条并把**整批图**认领过去，
 * 否则新提示词的出图历史是空的。
 */
const props = defineProps<{
  open: boolean
  /** 当前选中的提示词：只用于「归档到」选项，不当载体预填文本。 */
  promptId: number | null
  promptName: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'created', id: number): void
}>()

const TEXT_KEY = 'pb.trialDraft'
const settings = useSettings()
const toast = useToast()
const queryClient = useQueryClient()

/** 本面板自己的工作流/方向：改这里不该顺带改掉详情页的单跑默认。 */
const workflowPath = ref(settings.workflowPath.value)
const orientation = ref(settings.orientation.value)
const quality = useWorkflowQuality(workflowPath)
const aspectRatio = useWorkflowAspectRatio(workflowPath)
const { workflows, allWorkflows } = useWorkflows()
const { caps, qualityOptions, aspectRatios, defaultRatio } = useWorkflowCaps(
  workflowPath, allWorkflows, aspectRatio,
)
const { queue, error: runError, submitAndTrack, trackQueued } = useGenerate('prompt-trial', { queue: true })

function readDraft(): { prompt: string; negative: string } {
  try {
    const raw = localStorage.getItem(TEXT_KEY)
    if (!raw) return { prompt: '', negative: '' }
    const parsed = JSON.parse(raw) as { prompt?: string; negative?: string }
    return { prompt: parsed.prompt ?? '', negative: parsed.negative ?? '' }
  } catch {
    return { prompt: '', negative: '' }
  }
}

const initialDraft = readDraft()
const promptText = ref(initialDraft.prompt)
const negative = ref(initialDraft.negative)
const negativeExpanded = ref(Boolean(initialDraft.negative))
const seedInput = ref('')
const linkArchive = ref(false)

/** 文本落盘：关掉弹窗再打开还能接着改，不用重新粘一遍。 */
watch([promptText, negative], () => {
  try {
    localStorage.setItem(TEXT_KEY, JSON.stringify({ prompt: promptText.value, negative: negative.value }))
  } catch {
    /* 隐私模式下忽略 */
  }
})

watch(
  () => props.open,
  (open) => {
    if (open && !workflowPath.value) workflowPath.value = settings.workflowPath.value
  },
)

/** 选中的提示词被切走/删掉时，归档选项必须跟着失效。 */
watch(
  () => props.promptId,
  (id) => {
    if (!id) linkArchive.value = false
  },
)

const matrix = usePromptMatrix({
  scope: () => 'trial',
  storeKey: 'pb.trialMatrix',
  promptText: () => promptText.value,
  negativeText: () => negative.value,
  savedSeed: () => null,
  workflows: () => workflows.value,
  currentWorkflow: () => workflowPath.value,
  ratio: () => aspectRatio.value || defaultRatio.value,
  tier: () => quality.value,
  orientation: () => (caps.value.orientation ? orientation.value : 'keep'),
  submit: (req) =>
    submitAndTrack<{ success: boolean; job_id?: number | null }>('/api/runs/text', {
      prompt: req.prompt,
      negative_prompt: req.negative,
      workflow_path: req.path,
      workflow_content: customWorkflowContent(req.path),
      quality: req.tier,
      orientation: req.orientation,
      aspect_ratio: req.ratio,
      seed: req.seed,
      source_prompt_id: linkArchive.value && props.promptId ? props.promptId : 0,
    }),
  track: trackQueued,
  fetchJob: (id) => apiGet<JobSnapshot>(`/api/jobs/${id}`).catch(() => null),
  jobs: () => queue.value,
  refreshShots: () => {
    queryClient.invalidateQueries({ queryKey: ['history'] })
  },
  useWorkflow: (path) => {
    workflowPath.value = path
  },
  notify: (kind, message) => {
    if (kind === 'error') toast.error(message)
    else if (kind === 'success') toast.success(message)
    else toast.info(message)
  },
})

const alignOptions: Array<{ value: MatrixAlign; label: string }> = [
  { value: 'native', label: '各自原生档' },
  { value: 'first', label: '对齐到首个' },
  { value: 'ref', label: '对齐到 1024×1536' },
]

const charCount = computed(() => promptText.value.length)
const canRun = computed(
  () => promptText.value.trim().length > 0 && matrix.plan.usable.length > 0 && !matrix.submitting,
)
const planSummary = computed(() => {
  const p = matrix.plan
  if (!p.usable.length) return '勾选工作流后开始试跑'
  return `${p.usable.length} 个工作流 × ${p.count} 张 = ${p.total} 张`
})

function runTrial() {
  const raw = String(seedInput.value ?? '').trim()
  matrix.submit(raw === '' ? null : Number(raw))
}

function randomSeed() {
  seedInput.value = String(Math.floor(Math.random() * 2 ** 31))
}

function clearText() {
  promptText.value = ''
  negative.value = ''
  negativeExpanded.value = false
}

// ---------------- 看图 / 对比 ----------------

const { items: previewItems, readonly: previewReadonly, open: previewOpen, preview, close: closePreview } =
  useImagePreview()
const compareItems = ref<HistoryItem[]>([])
const compareOpen = ref(false)

function toRef(image: MatrixImage) {
  return { filename: image.filename, subfolder: image.subfolder, type: image.img_type }
}

function openImage(payload: { items: MatrixImage[]; index: number; prompt?: string; negative?: string }) {
  const target = payload.items[payload.index]
  if (target) {
    preview(toRef(target), {
      prompt: payload.prompt ?? promptText.value,
      negative: payload.negative ?? negative.value,
    })
  }
}

async function openCompare(images: MatrixImage[]) {
  if (images.length < 2) {
    toast.info('并排对比至少选 2 张')
    return
  }
  compareItems.value = await resolveHistoryItems(images.slice(0, 4).map(toRef))
  compareOpen.value = true
}

// ---------------- 存为提示词（按批认领整批图） ----------------

const saveOpen = ref(false)
const linking = ref(false)
const savingBatch = ref<MatrixBatch | null>(null)

const saveInitial = computed(() => ({
  prompt: savingBatch.value?.prompt || promptText.value,
  negative_prompt: savingBatch.value?.negative ?? negative.value,
  seed: savingBatch.value?.baseSeed || matrix.baseSeed || null,
}))

function startSave(batch: MatrixBatch) {
  if (!batch.cells.some((c) => c.status === 'done' && c.image)) {
    toast.error('这一批还没有出好的图')
    return
  }
  savingBatch.value = batch
  saveOpen.value = true
}

async function onCreated(id: number) {
  saveOpen.value = false
  const refs = (savingBatch.value?.cells ?? [])
    .filter((c) => c.status === 'done' && c.image)
    .map((c) => c.image as MatrixImage)
  linking.value = true
  try {
    // 任务快照只给文件名，认领需要图库 id：按名取回完整记录，取不到的跳过。
    const resolved = await resolveHistoryItems(refs.map(toRef))
    const ids = resolved.map((r) => r.id).filter((n) => n > 0)
    if (ids.length) {
      const result = await linkImagesToPrompt(ids, id)
      toast.success(`已存为提示词，并认领 ${result.linked} 张图`)
    } else {
      toast.info('已存为提示词；图还没入库，稍后可在画廊同步后认领')
    }
    queryClient.invalidateQueries({ queryKey: ['prompts'] })
    queryClient.invalidateQueries({ queryKey: ['history'] })
    queryClient.invalidateQueries({ queryKey: ['prompt-history', id] })
  } catch (error) {
    toast.error(`认领图片失败：${error instanceof Error ? error.message : String(error)}`)
  } finally {
    linking.value = false
    emit('created', id)
  }
}
</script>

<template>
  <Modal
    :open="open"
    title="临时试跑"
    width="min(1760px, 96vw)"
    height="88vh"
    @close="emit('close')"
  >
    <template #head>
      <span class="head-sub">外来文本 · 多工作流横评 · 不写回提示词库</span>
    </template>

    <template #actions>
      <span v-if="linking" class="head-sub">正在认领图片…</span>
      <details class="more">
        <summary class="btn btn-sm">归档 ▾</summary>
        <div class="more-pop">
          <label class="radio">
            <input v-model="linkArchive" type="radio" :value="false" />
            不关联（档案标「临时提示词」）
          </label>
          <label v-if="promptId" class="radio">
            <input v-model="linkArchive" type="radio" :value="true" />
            关联到《{{ promptName || `#${promptId}` }}》
          </label>
          <p class="more-note">关联只影响图片归属，不会把文本写回那条提示词。</p>
        </div>
      </details>
    </template>

    <div class="trial-grid">
      <section class="pane pane-text">
        <div class="pane-head">
          <span class="pane-title">提示词</span>
          <span class="counter">{{ charCount }} 字</span>
          <span class="grow" />
          <button class="btn btn-sm" type="button" :disabled="!charCount" @click="clearText">清空</button>
        </div>
        <textarea
          v-model="promptText"
          class="big-text scroll"
          spellcheck="false"
          placeholder="把从别处复制的提示词粘进来。这里不依赖任何已存提示词，空库也能跑。"
        />
        <div class="neg">
          <div class="neg-head">
            <span class="pane-title">负面提示词</span>
            <span v-if="negative.trim() && caps.negative_effective === false" class="warn-text">
              当前工作流负向不生效
            </span>
            <span class="grow" />
            <button class="btn btn-sm" type="button" @click="negativeExpanded = !negativeExpanded">
              {{ negativeExpanded ? '收起' : negative ? '展开' : '＋ 添加' }}
            </button>
          </div>
          <textarea
            v-if="negativeExpanded"
            v-model="negative"
            class="neg-input scroll"
            rows="3"
            spellcheck="false"
            placeholder="可留空"
          />
        </div>
      </section>

      <section class="controls">
          <div class="control-row">
            <WorkflowPicker
              :model-value="workflowPath"
              :workflows="workflows"
              multiple
              :selected="matrix.paths"
              :unavailable="matrix.unavailable"
              @update:model-value="workflowPath = $event"
              @update:selected="matrix.setPaths($event)"
            />
          </div>
          <div class="control-row">
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
            <label class="mini-field">
              <span>尺寸对齐</span>
              <select
                :value="matrix.align"
                title="各工作流档位机制不同，同一档出的尺寸并不一样"
                @change="matrix.setAlign(($event.target as HTMLSelectElement).value as MatrixAlign)"
              >
                <option v-for="opt in alignOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
              </select>
            </label>
          </div>
          <div class="control-row">
            <div class="mini-field">
              <span>每个工作流张数</span>
              <span class="counts">
                <button
                  v-for="n in [1, 2, 3, 4]"
                  :key="n"
                  class="btn btn-sm count-btn"
                  :class="{ on: matrix.count === n }"
                  type="button"
                  @click="matrix.setCount(n)"
                >
                  {{ n }}
                </button>
              </span>
            </div>
            <label class="mini-field seed">
              <span>基准种子</span>
              <input v-model="seedInput" type="number" min="0" step="1" placeholder="空 = 随机" />
            </label>
            <button class="btn btn-sm" type="button" @click="randomSeed"><Icon name="dices" /> 随机</button>
            <label class="lock" title="锁定后各工作流同列用同一个种子，差异才归因于模型">
              <input v-model="matrix.lockSeed" type="checkbox" />
              同种子
            </label>
            <span class="grow" />
            <button
              class="btn btn-sm primary run"
              type="button"
              :class="{ loading: matrix.submitting }"
              :disabled="!canRun"
              @click="runTrial"
            >
              {{ matrix.submitting ? '提交中…' : `▶ 跑 ${matrix.plan.total} 张` }}
            </button>
          </div>
          <div class="plan">
            <span class="plan-count">{{ planSummary }}</span>
            <span v-for="(warn, i) in matrix.plan.warnings" :key="i" class="plan-warn" :class="warn.kind">
              {{ warn.text }}
            </span>
            <span v-if="runError" class="plan-warn warn">{{ runError }}</span>
          </div>
      </section>

      <div class="results scroll">
        <PromptMatrixStack
          :matrix="matrix"
          saveable
          @compare="openCompare($event)"
          @open-image="openImage($event)"
          @save="startSave($event)"
        />
      </div>
    </div>
  </Modal>

  <CompareModal :open="compareOpen" :items="compareItems" @close="compareOpen = false" />

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
    :initial="saveInitial"
    @close="saveOpen = false"
    @created="onCreated"
  />
</template>

<style scoped>
.head-sub {
  color: var(--muted);
  font-size: var(--fs-xs);
}

.btn.primary {
  border-color: var(--primary);
  background: var(--primary);
  color: rgb(255 255 255);
}

.btn.primary:disabled {
  opacity: 0.45;
  cursor: default;
}

.more {
  position: relative;
}

.more > summary {
  display: flex;
  align-items: center;
  list-style: none;
  cursor: pointer;
}

.more > summary::-webkit-details-marker {
  display: none;
}

.more-pop {
  position: absolute;
  top: calc(100% + var(--gap-xs));
  right: 0;
  z-index: var(--z-modal);
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  width: max-content;
  max-width: min(320px, 80vw);
  padding: var(--gap-sm);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--panel);
  box-shadow: var(--shadow-2);
}

.more-note {
  margin: 0;
  color: var(--muted);
  font-size: var(--fs-xs);
  line-height: var(--lh-lg);
}

.radio {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-sm);
  cursor: pointer;
}

.radio input {
  accent-color: var(--primary);
}

/* ---------- 双栏骨架 ---------- */

.trial-grid {
  display: grid;
  grid-template-columns: minmax(320px, 40%) minmax(0, 1fr);
  grid-template-rows: auto minmax(0, 1fr);
  grid-template-areas:
    "text controls"
    "text results";
  height: 100%;
  min-height: 0;
}

.pane {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.pane-text {
  grid-area: text;
  gap: var(--gap-sm);
  padding: var(--gap) var(--gap-lg);
  border-right: 1px solid var(--border);
  background: var(--panel-2);
}

.pane-head,
.neg-head {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  flex: none;
}

.pane-title {
  font-size: var(--fs-sm);
  font-weight: 500;
}

.counter {
  color: var(--muted);
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
}

.grow {
  flex: 1 1 auto;
}

.big-text {
  flex: 1 1 auto;
  min-height: 200px;
  width: 100%;
  resize: none;
  padding: var(--gap-sm) var(--gap);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel);
  color: var(--text);
  font: inherit;
  font-size: var(--fs-sm);
  line-height: 1.7;
}

.big-text:focus {
  border-color: var(--primary);
  outline: none;
}

.neg {
  flex: none;
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
}

.neg-input {
  width: 100%;
  resize: vertical;
  padding: 6px var(--gap-sm);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel);
  color: var(--text);
  font: inherit;
  font-size: var(--fs-sm);
}

.warn-text {
  color: var(--warn);
  font-size: var(--fs-xs);
}

/* ---------- 右侧常驻控制区 ---------- */

.controls {
  grid-area: controls;
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  padding: var(--gap) var(--gap-lg);
  border-bottom: 1px solid var(--border);
  background: var(--panel);
}

.control-row {
  display: flex;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: var(--gap-sm);
}

.mini-field {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: var(--fs-xs);
  color: var(--muted);
}

.mini-field select,
.mini-field input {
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
  color: var(--text);
  font: inherit;
  font-size: var(--fs-sm);
}

.mini-field.seed input {
  width: 130px;
}

.counts {
  display: flex;
  gap: 3px;
}

.count-btn.on {
  border-color: var(--primary);
  color: var(--accent-link);
  background: var(--primary-soft);
}

.lock {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: var(--fs-xs);
  color: var(--muted);
  cursor: pointer;
}

.lock input {
  width: 14px;
  height: 14px;
  accent-color: var(--primary);
}

.run {
  min-width: 116px;
}

.plan {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: var(--gap-xs) var(--gap-sm);
}

.plan-count {
  font-size: var(--fs-sm);
  font-weight: 500;
}

.plan-warn {
  padding: 1px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--muted);
  font-size: var(--fs-xs);
  line-height: var(--lh-lg);
}

.plan-warn.warn {
  border-color: var(--warn);
  color: var(--warn);
}

.plan-warn.ok {
  border-color: var(--success-border);
  color: var(--success-text);
}

.results {
  grid-area: results;
  min-height: 0;
  overflow-y: auto;
  background: var(--bg);
}

/* ---------- 滚动条跟随面板配色 ---------- */

.scroll {
  scrollbar-width: thin;
  scrollbar-color: var(--border-strong) var(--panel-2);
}

.scroll::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}

.scroll::-webkit-scrollbar-track {
  background: var(--panel-2);
}

.scroll::-webkit-scrollbar-thumb {
  background: var(--border-strong);
  border: 2px solid var(--panel-2);
  border-radius: 999px;
}

.scroll::-webkit-scrollbar-thumb:hover {
  background: var(--muted);
}

@media (max-width: 900px) {
  .head-sub {
    display: none;
  }

  .trial-grid {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto auto auto;
    grid-template-areas:
      "text"
      "controls"
      "results";
    height: auto;
  }

  .pane-text {
    border-right: none;
    border-bottom: 1px solid var(--border);
  }

  .big-text {
    min-height: 180px;
  }

  .results {
    overflow: visible;
  }
}
</style>
