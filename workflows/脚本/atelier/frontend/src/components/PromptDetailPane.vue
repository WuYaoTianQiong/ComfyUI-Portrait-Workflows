<script setup lang="ts">
import { ref, watch } from 'vue'

import WorkflowPicker from './WorkflowPicker.vue'
import WorkflowParams from './WorkflowParams.vue'
import TagInput from './TagInput.vue'
import EmptyState from './EmptyState.vue'
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
}>()

const emit = defineEmits<{
  'update:workflow-path': [value: string]
  'update:quality': [value: string]
  'update:orientation': [value: 'portrait' | 'landscape']
  'update:aspect-ratio': [value: string]
  'update:draft-tag-list': [value: string[]]
  generate: []
  'smart-segment': []
  'replace-fragment': []
  trial: []
  favorite: []
  pin: []
  revert: []
  save: []
  'delete-prompt': []
  copy: [text: string, label: string]
  rate: [rating: number]
  'auto-classify': []
  'toggle-category': [id: number]
  'open-shot': [index: number]
  reveal: [item: HistoryItem]
}>()

/** 负面提示词默认收起：空值不该占一大块；有内容时显示单行摘要。 */
const negativeExpanded = ref(false)

watch(
  () => props.draft?.id,
  () => {
    negativeExpanded.value = false
  },
)
</script>

<template>
  <section class="detail-pane">
    <EmptyState v-if="!draft" size="big" text="选择左侧任意一条提示词" />

    <div v-else class="detail">
      <div class="detail-top">
        <div class="generate-bar">
          <div class="generate-settings">
            <WorkflowPicker
              :model-value="workflowPath"
              :workflows="workflows"
              @update:model-value="emit('update:workflow-path', $event)"
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
            <button
              class="btn btn-sm"
              title="用当前草稿试跑，不写回提示词库"
              :disabled="!caps.prompt"
              @click="emit('trial')"
            >
              🧪 试跑
            </button>
            <button
              class="btn btn-sm"
              title="同一条提示词换种子出多张变体"
              :disabled="!caps.prompt"
              @click="emit('trial')"
            >
              🎲 变体
            </button>
            <span v-if="wfValidation && !wfValidation.valid" class="gen-error">
              工作流不可用：{{ wfValidation.error }}
            </span>
            <span v-else-if="generateError" class="gen-error">{{ generateError }}</span>
            <span v-else-if="activeJob" class="job-state" :class="activeJob?.status">
              {{ statusLabel(activeJob?.status) }} {{ activeJob?.done_count ?? 0 }}/{{ activeJob?.total ?? 1 }}
            </span>
            <button
              class="btn btn-sm primary"
              :class="{ loading: generating }"
              :disabled="generating || !workflowPath || !caps.prompt"
              @click="emit('generate')"
            >
              {{ generating ? '生成中…' : '🚀 出图' }}
            </button>
          </div>
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
            {{ draft.is_pinned ? '📌 已置顶' : '📌 置顶' }}
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
              <span class="param-label">分辨率</span>
              <span class="param-value">
                {{ draft.width && draft.height ? `${draft.width}×${draft.height}` : '-' }}
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
              :model-value="draftTagList"
              :suggestions="tags"
              @update:model-value="emit('update:draft-tag-list', $event)"
            />
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
  color: var(--primary);
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

/* 收起状态只占一行：空值不再吃掉 84px */
.negative-line {
  width: 100%;
  padding: 8px 10px;
  text-align: left;
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-left: 3px solid var(--danger);
  border-radius: var(--radius-sm);
  color: var(--text);
  font: inherit;
  font-size: var(--fs-sm);
}

.negative-line:hover {
  border-color: var(--primary);
  border-left-color: var(--danger);
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

.editor {
  font: inherit;
  font-size: var(--fs-sm);
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--gap-sm);
  outline: none;
  resize: vertical;
}

/* field-sizing 让输入框跟着内容长；不支持时退化为 min-height + 手动拖拽 */
.editor.pos {
  min-height: 180px;
  field-sizing: content;
  border-left: 3px solid var(--primary);
}

.editor.neg {
  min-height: 72px;
  max-height: 28vh;
  field-sizing: content;
  border-left: 3px solid var(--danger);
  color: var(--danger-text-field);
}

.editor:focus {
  border-color: var(--primary);
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

.note-input {
  width: 100%;
  font: inherit;
  font-size: var(--fs-sm);
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--gap-sm);
  outline: none;
}

.note-input:focus {
  border-color: var(--primary);
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
  transition: 0.12s;
}

.cat-chip:hover {
  border-color: var(--primary);
  color: var(--text);
}

.cat-chip.on {
  background: var(--c, var(--primary));
  border-color: var(--c, var(--primary));
  color: var(--on-primary);
}

/**
 * 浅色主题：分类色来自用户数据，可能是高亮度色，
 * 白字只有 2.15:1。把底色调暗 40%（保留色相）后，8 个默认色板上的白字
 * 均回到 5.4:1 以上。深色主题不命中此规则，外观不变。
 */
:root[data-theme='light'] .cat-chip.on {
  background: color-mix(in srgb, var(--c, var(--primary)) 60%, var(--mix-base-black));
  border-color: color-mix(in srgb, var(--c, var(--primary)) 60%, var(--mix-base-black));
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
  font-size: 10px;
  line-height: 1.5;
  opacity: 0;
  transition: 0.12s;
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