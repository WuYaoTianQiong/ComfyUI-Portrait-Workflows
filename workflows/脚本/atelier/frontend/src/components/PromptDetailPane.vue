<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import WorkflowPicker from './WorkflowPicker.vue'
import Icon from './Icon.vue'
import WorkflowParams from './WorkflowParams.vue'
import PromptMatrixStack from './PromptMatrixStack.vue'
import TagInput from './TagInput.vue'
import QueryState from './QueryState.vue'
import type { PromptMatrixApi } from '../composables/usePromptMatrix'
import type { MatrixAlign, MatrixImage } from '../composables/useWorkflowMatrix'
import { thumbnailUrl } from '../api/client'
import { statusLabel } from '../utils/format'
import type { WorkflowValidation } from '../api/workflows'
import type { QualityOption, WorkflowCaps } from '../composables/useWorkflowCaps'
import type { WorkflowRow } from '../composables/useWorkflows'
import type { FlatCategory } from '../utils/categories'
import type { HistoryItem, JobSnapshot, PromptDetail, TagRow } from '../api/types'

/**
 * 提示词页右侧详情：出图栏、正/负向编辑器、参数 / 分类 / 标签、出图历史。
 *
 * 草稿与所有 mutation 仍由 PromptView 持有，这里只编辑传入的 draft 对象
 * 并把操作抛给父组件；图片灯箱、试跑、替换碎片等弹窗也留在父组件。
 */
const props = defineProps<{
  draft: PromptDetail | null
  /** 已选中但详情还没到：必须显示加载态，不能画成「未选择」。 */
  loading: boolean
  error: unknown
  dirty: boolean
  saving: boolean
  classifying: boolean
  generating: boolean
  workflowPath: string
  workflows: WorkflowRow[]
  quality: string
  orientation: 'portrait' | 'landscape'
  aspectRatio: string
  aspectRatios: string[]
  defaultRatio: string
  qualityOptions: QualityOption[]
  caps: WorkflowCaps
  wfValidation: WorkflowValidation | undefined
  generateError: string
  activeJob: JobSnapshot | null
  flatCats: FlatCategory[]
  tags: TagRow[]
  linkedCategoryIds: number[]
  draftTagList: string[]
  shotItems: HistoryItem[]
  /** 横评（同一提示词 × 多工作流）的完整状态与动作 */
  matrix: PromptMatrixApi
}>()

const emit = defineEmits<{
  'update:workflow-path': [value: string]
  'update:quality': [value: string]
  'update:orientation': [value: 'portrait' | 'landscape']
  'update:aspect-ratio': [value: string]
  'update:draft-tag-list': [value: string[]]
  generate: [options: { count: number; seed: number | null }]
  retry: []
  'smart-segment': []
  'replace-fragment': []
  favorite: []
  pin: []
  revert: []
  save: []
  'delete-prompt': []
  'favorite-image': [item: MatrixImage]
  'matrix-compare': [items: MatrixImage[]]
  'matrix-open-image': [payload: { items: MatrixImage[]; index: number }]
  copy: [text: string, label: string]
  rate: [rating: number]
  'auto-classify': []
  'toggle-category': [id: number]
  'open-shot': [index: number]
  reveal: [item: HistoryItem]
}>()

/** 负面提示词默认收起：空值不该占一大块；有内容时显示单行摘要。 */
const negativeExpanded = ref(false)

/** 出图张数（>1 即旧"变体"，种子依次 +1）与种子输入（空 = 沿用提示词种子/随机）。 */
const runCount = ref(1)
const seedInput = ref('')

function onGenerate() {
  // input[type=number] 在部分浏览器/测试环境里会把 v-model 值转成 number。
  const rawSeed = String(seedInput.value ?? '').trim()
  const seed = rawSeed === '' ? null : Number(rawSeed)
  if (props.matrix.enabled) {
    props.matrix.submit(seed)
    return
  }
  emit('generate', { count: runCount.value, seed })
}

function setCount(n: number) {
  runCount.value = n
  props.matrix.setCount(n)
}

/** 横评态下张数与单跑共用一组按钮，切换模式时保持同一个值。 */
watch(
  () => props.matrix.enabled,
  (on) => {
    if (on) runCount.value = props.matrix.count
  },
)

const matrixSummary = computed(() => {
  const p = props.matrix.plan
  if (!p.usable.length) return '勾选工作流后开始横评'
  return `${p.usable.length} 个工作流 × ${p.count} 张 = ${p.total} 张`
})

const alignOptions: Array<{ value: MatrixAlign; label: string }> = [
  { value: 'native', label: '各自原生档' },
  { value: 'first', label: '对齐到首个' },
  { value: 'ref', label: '对齐到 1024×1536' },
]
/** 标签为空时压成一行；展开过一次后先收起（切换条目再重置），避免边填边塌。 */
const tagsExpanded = ref(false)

const hasTags = computed(() => props.draftTagList.length > 0)

/**
 * 当前「比例 × 画质档」的真实出图尺寸。
 *
 * 提示词里存的 width/height 是历史记录，**不参与出图**（后端按档位与比例重算），
 * 把它当"分辨率"展示会让人以为换比例没生效。预演拿不到时才回落到旧字段。
 */
const storedSizeText = computed(() =>
  props.draft?.width && props.draft?.height
    ? `${props.draft.width}×${props.draft.height}`
    : '',
)

const outputSizeText = computed(() => {
  const option = props.qualityOptions.find((o) => o.value === props.quality)
  return option?.label || storedSizeText.value || '-'
})

const outputSizeHint = computed(() => {
  const stored = storedSizeText.value
  const base = `实际出图尺寸由「比例 ${props.aspectRatio || props.defaultRatio || '默认'} × 画质档 ${props.quality || '1.0×'}」决定`
  return stored ? `${base}；提示词记录的 ${stored} 只是历史值，不参与出图` : base
})

/** 已经动过标签就保持展开：否则删掉最后一个标签时输入框会在光标下消失。 */
function onTagsUpdate(value: string[]) {
  tagsExpanded.value = true
  emit('update:draft-tag-list', value)
}

watch(
  () => props.draft?.id,
  () => {
    negativeExpanded.value = false
    tagsExpanded.value = false
  },
)
</script>

<template>
  <section class="detail-pane">
    <div v-if="!draft" class="detail-state">
      <QueryState
        :loading="loading && !error"
        :error="error"
        :empty="!loading && !error"
        loading-text="正在加载提示词…"
        empty-text="选择左侧任意一条提示词"
        @retry="emit('retry')"
      />
    </div>

    <div v-else class="detail">
      <div class="detail-top">
        <div class="generate-bar" :class="{ 'matrix-on': matrix.enabled }">
          <div class="generate-settings">
            <button
              class="btn btn-sm matrix-toggle"
              :class="{ on: matrix.enabled }"
              type="button"
              :aria-pressed="matrix.enabled"
              title="同一提示词、同一种子，分别投喂多个工作流做横向对比"
              @click="matrix.setEnabled(!matrix.enabled)"
            >
              ⇄ 横评
            </button>
            <WorkflowPicker
              :model-value="workflowPath"
              :workflows="workflows"
              :multiple="matrix.enabled"
              :selected="matrix.paths"
              :unavailable="matrix.unavailable"
              @update:model-value="emit('update:workflow-path', $event)"
              @update:selected="matrix.setPaths($event)"
            />
            <label v-if="matrix.enabled" class="matrix-align">
              <span>尺寸对齐</span>
              <select
                :value="matrix.align"
                title="各工作流的档位机制不同，同一档出的尺寸并不一样"
                @change="matrix.setAlign(($event.target as HTMLSelectElement).value as MatrixAlign)"
              >
                <option v-for="opt in alignOptions" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </option>
              </select>
            </label>
            <label v-if="matrix.enabled" class="matrix-lock" title="锁定后各工作流同列用同一个种子，差异才归因于模型">
              <input v-model="matrix.lockSeed" type="checkbox" />
              同种子
            </label>
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
            <span
              v-if="workflowPath && caps.prompt && (!caps.negative || caps.negative_effective === false)"
              class="cap-hint"
              :title="caps.negative_effective === false
                ? '该工作流有负向字段，但 CFG=1，采样时不会生效'
                : '该工作流不接收负面提示词'"
            >
              {{ caps.negative_effective === false ? '负向不生效' : '不支持负面' }}
            </span>
            <span
              v-if="workflowPath && !caps.prompt"
              class="cap-hint warn"
              title="该工作流不注入提示词"
            >
              不注入提示词
            </span>
          </div>
          <div class="generate-actions">
            <button class="btn btn-sm" title="按关键词把提示词拆成【类型】结构" @click="emit('smart-segment')">
              ✂ 智能分段
            </button>
            <button
              class="btn btn-sm"
              title="只替换这条提示词里的某一类碎片，再出图"
              :disabled="!caps.prompt"
              @click="emit('replace-fragment')"
            >
              替换碎片
            </button>
            <span class="run-counts" title="出图张数；多张时种子依次 +1">
              <button
                v-for="n in [1, 2, 3, 4]"
                :key="n"
                class="btn btn-sm count-btn"
                :class="{ on: runCount === n }"
                @click="setCount(n)"
              >
                {{ n }}
              </button>
            </span>
            <input
              v-model="seedInput"
              class="seed-input"
              type="number"
              min="0"
              step="1"
              :placeholder="draft.seed ? `默认 ${draft.seed}` : '空 = 随机'"
              title="种子；留空沿用提示词保存的种子，没有则随机"
            />
            <span v-if="wfValidation && !wfValidation.valid" class="gen-error">
              工作流不可用：{{ wfValidation.error }}
            </span>
            <span v-else-if="generateError" class="gen-error">{{ generateError }}</span>
            <span v-else-if="activeJob" class="job-state" :class="activeJob?.status">
              {{ statusLabel(activeJob?.status) }} {{ activeJob?.done_count ?? 0 }}/{{ activeJob?.total ?? 1 }}
            </span>
            <span
              v-if="dirty"
              class="cap-hint"
              title="出图跑编辑框当前文本（含未保存修改），不会写回提示词库"
            >
              含未保存修改
            </span>
            <button
              class="btn btn-sm primary"
              :class="{ loading: generating || matrix.submitting }"
              :disabled="matrix.enabled
                ? matrix.submitting || !matrix.plan.usable.length || matrix.plan.overLimit
                : generating || !workflowPath || !caps.prompt"
              @click="onGenerate"
            >
              <Icon v-if="!matrix.enabled && !generating" name="play" />
              {{ matrix.enabled
                ? (matrix.submitting ? '提交中…' : `⇄ 横评出图 ${matrix.plan.total} 张`)
                : (generating ? '生成中…' : '出图') }}
            </button>
          </div>
        </div>

        <div v-if="matrix.enabled" class="matrix-plan">
          <span class="matrix-plan-count">{{ matrixSummary }}</span>
          <span
            v-for="(warn, i) in matrix.plan.warnings"
            :key="i"
            class="matrix-warn"
            :class="warn.kind"
          >
            {{ warn.text }}
          </span>
        </div>

        <div class="action-bar">
          <input v-model="draft.name" class="name-input" placeholder="未命名" />
          <span v-if="dirty" class="dirty-badge">● 已修改</span>
          <button
            class="btn btn-sm"
            :class="{ active: draft.is_favorite }"
            title="收藏"
            @click="emit('favorite')"
          >
            {{ draft.is_favorite ? '★ 已收藏' : '☆ 收藏' }}
          </button>
          <button
            class="btn btn-sm"
            :class="{ active: draft.is_pinned }"
            :title="draft.is_pinned ? '已置顶，点击取消' : '置顶这条提示词'"
            @click="emit('pin')"
          >
            <Icon name="pin" /> {{ draft.is_pinned ? '已置顶' : '置顶' }}
          </button>
          <button class="btn btn-sm" :disabled="!dirty" @click="emit('revert')">撤销</button>
          <button
            class="btn btn-sm primary"
            :disabled="!dirty || saving"
            @click="emit('save')"
          >
            {{ saving ? '保存中…' : '保存' }}
          </button>
          <button class="btn btn-sm danger" title="删除这条提示词" @click="emit('delete-prompt')">
            删除
          </button>
        </div>
      </div>

      <PromptMatrixStack
        v-if="matrix.enabled"
        :matrix="matrix"
        @compare="emit('matrix-compare', $event)"
        @open-image="emit('matrix-open-image', $event)"
        @favorite="emit('favorite-image', $event)"
      />

      <div class="detail-body">
        <main class="detail-main">
          <section class="section">
            <div class="section-head">
              <span>
                正向提示词
                <span v-if="dirty" class="dirty-badge">● 已修改</span>
              </span>
              <button class="btn btn-sm" @click="emit('copy', draft.prompt, '提示词')">复制</button>
            </div>
            <textarea v-model="draft.prompt" class="editor pos" spellcheck="false" />
          </section>

          <section class="section">
            <div class="section-head">
              <span>
                负面提示词
                <i v-if="caps.negative_effective === false" class="cap-inline warn">
                  负向不生效
                  <template v-if="typeof caps.negative_cfg === 'number'">（CFG={{ caps.negative_cfg }}）</template>
                </i>
                <i v-else-if="!caps.negative" class="cap-inline">该工作流不注入</i>
              </span>
              <div class="section-actions">
                <button
                  v-if="draft.negative_prompt"
                  class="btn btn-sm"
                  @click="emit('copy', draft.negative_prompt, '负面提示词')"
                >
                  复制
                </button>
                <button class="btn btn-sm" @click="negativeExpanded = !negativeExpanded">
                  {{ negativeExpanded ? '收起' : draft.negative_prompt ? '展开' : '＋ 添加' }}
                </button>
              </div>
            </div>
            <textarea
              v-if="negativeExpanded"
              v-model="draft.negative_prompt"
              class="editor neg"
              spellcheck="false"
              placeholder="输入负面提示词…"
            />
            <button v-else class="negative-line" @click="negativeExpanded = true">
              <span :class="{ empty: !draft.negative_prompt }">
                {{
                  draft.negative_prompt ||
                  (caps.negative_effective === false
                    ? '（空；当前工作流负向不生效，仅归档）'
                    : caps.negative
                      ? '（空）点击添加'
                      : '（空，仅归档，不参与出图）')
                }}
              </span>
            </button>
          </section>

          <section class="section">
            <div class="section-head"><span>备注</span></div>
            <input v-model="draft.note" class="note-input" placeholder="可留空" />
          </section>
        </main>

        <aside class="detail-rail">
          <div class="rail-rating">
            <span class="label">评级</span>
            <button
              v-for="n in 5"
              :key="n"
              class="star-btn"
              :class="{ on: (draft.rating ?? 0) >= n }"
              @click="emit('rate', n)"
            >
              ★
            </button>
            <span class="meta">使用 {{ draft.usage_count }} 次</span>
          </div>

          <section class="section">
            <div class="section-head"><span>参数</span></div>
            <div class="params">
              <label class="param-item">
                <span class="param-label">步数</span>
                <input
                  v-model.number="draft.steps"
                  class="param-input"
                  type="number"
                  min="1"
                  placeholder="-"
                />
              </label>
              <label class="param-item">
                <span class="param-label">CFG</span>
                <input
                  v-model.number="draft.cfg_scale"
                  class="param-input"
                  type="number"
                  step="0.1"
                  placeholder="-"
                />
              </label>
              <label class="param-item">
                <span class="param-label">采样器</span>
                <input v-model="draft.sampler" class="param-input" placeholder="-" />
              </label>
              <label class="param-item">
                <span class="param-label">种子</span>
                <input
                  v-model.number="draft.seed"
                  class="param-input"
                  type="number"
                  min="0"
                  placeholder="-"
                />
              </label>
              <div class="param-item">
                <span class="param-label">出图分辨率</span>
                <span class="param-value" :title="outputSizeHint">
                  {{ outputSizeText }}
                </span>
              </div>
              <div class="param-item">
                <span class="param-label">模型</span>
                <span class="param-value" :title="draft.model || '-'">{{ draft.model || '-' }}</span>
              </div>
            </div>
          </section>

          <section class="section">
            <div class="section-head"><span>标签</span></div>
            <TagInput
              v-if="hasTags || tagsExpanded"
              :model-value="draftTagList"
              :suggestions="tags"
              @update:model-value="onTagsUpdate"
            />
            <button v-else class="empty-line" @click="tagsExpanded = true">＋ 添加标签</button>
          </section>

          <section class="section">
            <div class="section-head">
              <span>分类（已关联 {{ draft.categories?.length ?? 0 }} 个）</span>
              <button
                class="btn btn-sm"
                :disabled="classifying"
                title="按提示词正文里的【类型】数量自动归入 组合 / 单项 / 零散"
                @click="emit('auto-classify')"
              >
                {{ classifying ? '归类中…' : '自动归类' }}
              </button>
            </div>
            <div class="cat-chips">
              <button
                v-for="cat in flatCats"
                :key="cat.id"
                class="cat-chip"
                :class="{ on: linkedCategoryIds.includes(cat.id) }"
                :style="{ '--c': cat.color }"
                :title="cat.name"
                @click="emit('toggle-category', cat.id)"
              >
                {{ cat.name }}
              </button>
              <EmptyState v-if="!flatCats.length" text="暂无分类" compact />
            </div>
          </section>

          <section class="section">
            <div class="section-head">
              <span>出图历史（{{ shotItems.length }} 张）</span>
            </div>
            <div v-if="shotItems.length" class="shot-grid">
              <div
                v-for="(shot, index) in shotItems"
                :key="shot.id"
                class="shot"
                role="button"
                tabindex="0"
                :title="`${shot.filename}\n点击查看原图`"
                @click="emit('open-shot', index)"
                @keydown.enter.prevent="emit('open-shot', index)"
              >
                <img :src="thumbnailUrl(shot, 200)" :alt="shot.filename" loading="lazy" />
                <button
                  class="shot-locate"
                  title="在资源管理器中定位"
                  @click.stop="emit('reveal', shot)"
                >
                  定位
                </button>
              </div>
            </div>
            <span v-else class="muted">这条提示词还没有出图</span>
          </section>
        </aside>
      </div>

      <div class="timestamps">
        创建 {{ draft.created_at || '未知' }}
        <span v-if="draft.updated_at && draft.updated_at !== draft.created_at">
          · 更新 {{ draft.updated_at }}
        </span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.detail-pane {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  container-type: inline-size;
}

.detail-state {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 320px;
  padding: var(--gap-xl);
}

.detail-state :deep(.query-state),
.detail-state :deep(.empty-state) {
  width: 100%;
  max-width: 560px;
}

.matrix-toggle.on {
  border-color: var(--primary);
  background: var(--primary-soft);
  color: var(--accent-link);
}

/* 横评态多了对齐 / 同种子 / 芯片，单行必然放不下：
   设置区与动作区各占一行并允许换行，避免控件互相重叠。 */
.generate-bar.matrix-on {
  flex-wrap: wrap;
  align-items: flex-start;
}

.generate-bar.matrix-on .generate-settings {
  flex: 1 1 100%;
  flex-wrap: wrap;
  align-items: flex-start;
}

.generate-bar.matrix-on .generate-actions {
  flex: 1 1 100%;
  flex-wrap: wrap;
  margin-left: 0;
}

.generate-bar.matrix-on .wf-picker {
  flex: 1 1 300px;
  max-width: 460px;
}

.matrix-align {
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
  flex: none;
  color: var(--muted);
  font-size: var(--fs-xs);
}

.matrix-align select {
  max-width: 168px;
  padding: 3px 6px;
  font-size: var(--fs-xs);
}

.matrix-lock {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: none;
  color: var(--muted);
  font-size: var(--fs-xs);
  cursor: pointer;
}

.matrix-lock input {
  width: 14px;
  height: 14px;
  accent-color: var(--primary);
}

.matrix-plan {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: var(--gap-xs) var(--gap-sm);
  padding: var(--gap-xs) 0 0;
}

.matrix-plan-count {
  font-size: var(--fs-sm);
  font-weight: 500;
}

.matrix-warn {
  padding: 1px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--muted);
  font-size: var(--fs-xs);
  line-height: var(--lh-lg);
}

.matrix-warn.warn {
  border-color: var(--warn);
  color: var(--warn);
  background: var(--warn-surface, transparent);
}

.matrix-warn.ok {
  border-color: var(--success-border);
  color: var(--success-text);
}

.matrix-warn.info {
  border-color: var(--border-strong);
}

.detail {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  padding: var(--gap-lg);
}

/* 顶部出图上下文 + 操作，固定住，长正文滚动时不用回顶部 */
.detail-top {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  padding-bottom: var(--gap-sm);
  background: var(--bg);
}

.generate-bar {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--panel);
}

/* 左边设置区先按内容撑开，放不下时由工作流名让出宽度；右边动作组整体不压缩 */
.generate-settings {
  display: flex;
  flex: 1 1 auto;
  min-width: 0;
  flex-wrap: nowrap;
  align-items: center;
  gap: var(--gap-sm);
}

.generate-actions {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: nowrap;
  align-items: center;
  gap: var(--gap-sm);
  margin-left: auto;
}

.run-counts {
  display: flex;
  gap: 3px;
}

.run-counts .count-btn.on {
  border-color: var(--primary);
  color: var(--accent-link);
}

.seed-input {
  width: 96px;
  font: inherit;
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 4px 8px;
}

/* 按钮整组不参与压缩，压缩优先发生在工作流选择器上 */
.generate-settings > .btn,
.generate-actions > .btn {
  flex: none;
  white-space: nowrap;
}

/* 这档宽度下单行放不下全部内容：先收起能力提示（下方负面提示词区有同样信息），
   把宽度留给工作流名和分辨率 */
@container (min-width: 1041px) and (max-width: 1260px) {
  .generate-settings > .cap-hint {
    display: none;
  }
}

/* 详情区不够宽时，整组动作落到下一行，而不是把几个按钮拆散 */
@container (max-width: 1040px) {
  .generate-bar,
  .generate-settings,
  .generate-actions {
    flex-wrap: wrap;
  }
}

/* 正文与元数据分栏：宽屏右栏常驻，窄屏自动落回单列 */
.detail-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: var(--gap-lg);
  align-items: start;
}

.detail-main {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  min-width: 0;
}

.detail-rail {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  min-width: 0;
  padding-left: var(--gap-lg);
  border-left: 1px solid var(--border);
}

@container (max-width: 900px) {
  .detail-body {
    grid-template-columns: 1fr;
  }

  .detail-rail {
    padding-left: 0;
    border-left: none;
  }
}

.cap-hint {
  font-size: var(--fs-xs);
  color: var(--muted);
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-pill);
  padding: 1px 7px;
  white-space: nowrap;
  flex: none;
}

.cap-hint.warn {
  color: var(--warn);
  border-color: var(--warn);
}

.gen-error {
  font-size: var(--fs-sm);
  color: var(--danger);
}

.job-state {
  font-size: var(--fs-sm);
  color: var(--muted);
}

.job-state.running,
.job-state.pending {
  color: var(--accent-link);
}

.job-state.done {
  color: var(--success);
}

.job-state.error {
  color: var(--danger);
}

.action-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-xs);
}

/* 标题输入吃掉剩余宽度，按钮保持单行不拆字 */
.action-bar > .btn {
  flex: none;
  white-space: nowrap;
}

.dirty-badge {
  flex: none;
  padding: 1px 7px;
  border: 1px solid var(--warn);
  border-radius: var(--radius-pill);
  color: var(--warn);
  font-size: var(--fs-xs);
  font-weight: 400;
  white-space: nowrap;
}

.name-input {
  flex: 1;
  min-width: 180px;
  font-size: var(--fs-lg);
  font-weight: 600;
  background: transparent;
  border: 1px solid transparent;
  padding: 4px 6px;
}

.name-input:hover,
.name-input:focus {
  border-color: var(--border);
  background: var(--panel-2);
}

.stars {
  display: flex;
  align-items: center;
  gap: 2px;
}

.rail-rating {
  display: flex;
  align-items: center;
  gap: 2px;
  font-size: var(--fs-sm);
  color: var(--muted);
}

.label {
  font-size: var(--fs-sm);
  color: var(--muted);
  margin-right: var(--gap-sm);
}

.star-btn {
  border: none;
  background: transparent;
  /* 未收藏态：深色下沿用边框色，浅色下由令牌换成可辨识的中灰。 */
  color: var(--icon-idle);
  font-size: var(--fs-lg);
  line-height: 1;
  padding: 0 1px;
}

.star-btn.on {
  color: var(--warn);
}

.meta {
  margin-left: auto;
  font-size: var(--fs-xs);
  color: var(--muted);
}

.section {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-sm);
  font-size: var(--fs-sm);
  color: var(--muted);
}

.section-actions {
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
}

.cap-inline {
  margin-left: 4px;
  font-style: normal;
  font-size: var(--fs-xs);
  color: var(--muted);
}

.cap-inline.warn {
  color: var(--warn);
}

/* 收起状态只占一行：空值不再吃掉 84px；与展开态共用「无外框 + 左侧语义色」 */
.negative-line {
  width: 100%;
  padding: 6px 0 6px var(--gap);
  text-align: left;
  background: transparent;
  border: none;
  border-left: 3px solid var(--danger);
  border-radius: 0;
  color: var(--text);
  font: inherit;
  font-size: var(--fs-sm);
}

.negative-line:hover {
  background: var(--fill-faint);
}

.negative-line span {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.negative-line .empty {
  color: var(--muted);
}

/* 正文不加外框和底色：整页只有提示词本体用左侧 3px 语义色标出 */
.editor {
  font: inherit;
  font-size: var(--fs-sm);
  color: var(--text);
  background: transparent;
  border: none;
  border-left: 3px solid var(--border-strong);
  border-radius: 0;
  padding: 4px 0 4px var(--gap);
  outline: none;
  resize: vertical;
}

/* field-sizing 让输入框跟着内容长；不支持时退化为 min-height + 手动拖拽 */
.editor.pos {
  min-height: 180px;
  field-sizing: content;
  border-left-color: var(--primary);
}

.editor.neg {
  min-height: 72px;
  max-height: 28vh;
  field-sizing: content;
  border-left-color: var(--danger);
  color: var(--danger-text-field);
}

.editor:hover,
.editor:focus {
  background: var(--fill-faint);
}

.params {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: var(--gap-sm);
}

.param-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  background: var(--panel-2);
  border-radius: var(--radius-sm);
  padding: 6px 10px;
  min-width: 0;
}

.param-label {
  font-size: var(--fs-xs);
  color: var(--muted);
}

.param-value {
  font-size: var(--fs-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.param-input {
  width: 100%;
  font: inherit;
  font-size: var(--fs-sm);
  color: var(--text);
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  padding: 1px 4px;
  outline: none;
}

.param-input:hover,
.param-input:focus {
  border-color: var(--border);
  background: var(--panel);
}

/* 备注只有一条下划线：可选项，不与正文抢视觉 */
.note-input {
  width: 100%;
  font: inherit;
  font-size: var(--fs-sm);
  color: var(--text);
  background: transparent;
  border: none;
  border-bottom: 1px solid var(--border);
  border-radius: 0;
  padding: 4px 0;
  outline: none;
}

.note-input:focus {
  border-bottom-color: var(--primary);
}

/* 无数据分区压成一行可点摘要，与「负面提示词」的收起态同一套写法 */
.empty-line {
  width: 100%;
  padding: 3px 0;
  border: none;
  background: transparent;
  color: var(--muted);
  font: inherit;
  font-size: var(--fs-sm);
  text-align: left;
  cursor: pointer;
}

.empty-line:hover {
  color: var(--text);
}

.cat-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-xs);
}

.cat-chip {
  font-size: var(--fs-xs);
  padding: 2px 9px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--border);
  background: transparent;
  color: var(--muted);
  transition: color var(--dur-fast) var(--ease), background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease);
}

.cat-chip:hover {
  border-color: var(--primary);
  color: var(--text);
}

.cat-chip.on {
  /* 分类色来自用户数据，可能是高亮度色（琥珀白字仅 2.15:1）。
     底色调暗 40%（保留色相）后 8 个默认色板白字均 ≥5.4:1；明暗两主题共用同一条护色规则。 */
  background: color-mix(in srgb, var(--c, var(--primary)) 60%, var(--mix-base-black));
  border-color: color-mix(in srgb, var(--c, var(--primary)) 60%, var(--mix-base-black));
  color: var(--on-primary);
}

.shot-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(72px, 1fr));
  gap: var(--gap-xs);
}

.shot {
  position: relative;
  display: block;
  border-radius: var(--radius-sm);
  overflow: hidden;
  border: 1px solid var(--border);
  background: var(--panel-2);
  cursor: pointer;
}

.shot-locate {
  position: absolute;
  right: 2px;
  bottom: 2px;
  padding: 0 4px;
  border: 1px solid var(--border-strong);
  border-radius: 4px;
  background: rgb(22 27 34 / 82%);
  color: var(--text);
  font-size: var(--fs-xs);
  line-height: 1.5;
  opacity: 0;
  transition: opacity var(--dur-fast) var(--ease);
}

.shot:hover .shot-locate,
.shot:focus-within .shot-locate {
  opacity: 1;
}

.shot img {
  display: block;
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
}

.shot:hover {
  border-color: var(--primary);
}

.muted {
  font-size: var(--fs-sm);
  color: var(--muted);
}

.timestamps {
  font-size: var(--fs-xs);
  color: var(--muted);
}

.btn.primary {
  border-color: var(--primary);
  background: var(--primary);
  color: rgb(255 255 255);
}

.btn.primary:disabled {
  opacity: 0.4;
}

.btn.danger {
  border-color: var(--danger);
  color: var(--danger-text-button);
}

.btn.danger:hover {
  background: var(--danger-soft);
}
</style>