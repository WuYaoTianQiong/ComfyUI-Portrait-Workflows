<script setup lang="ts">
import { computed, ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'

import TagCloud from '../components/TagCloud.vue'
import { apiGet, apiPost } from '../api/client'
import { QUALITY_OPTIONS, useSettings } from '../composables/useSettings'
import { useGenerate } from '../composables/useGenerate'
import { useWorkflows } from '../composables/useWorkflows'
import type { CategoryNode, TagRow } from '../api/types'

/**
 * 碎片类型固定 8 类，与后端 `services/composition.FRAGMENT_TYPES` 一一对应。
 * 顺序即渲染顺序（人物→姿态→镜头→场景→风格），修改必须两边同时改。
 */
const FRAGMENT_TYPES = [
  '人物面部',
  '人物身材',
  '人物服饰',
  '姿态动作',
  '拍摄视角',
  '场景环境',
  '光影色调',
  '画风技术',
] as const

interface FragmentItem {
  fragment_id?: number
  prompt_id: number | null
  prompt_name: string
  type: string
  content: string
  tags: string
  source: 'prompt' | 'library'
  dup_count: number
}

const { workflowPath, quality, orientation } = useSettings()
const { busy: generating, job: activeJob, error: generateError, track } = useGenerate()
const { workflows } = useWorkflows()

// ---------------- 碎片池 ----------------

const search = ref('')
const categoryId = ref<number | null>(null)
const tagIds = ref<number[]>([])
const tagMatch = ref<'all' | 'any'>('all')

const { data: fragmentData, isFetching } = useQuery<{
  grouped: Record<string, FragmentItem[]>
  fragment_count: number
}>({
  queryKey: computed(() => [
    'composer-fragments',
    search.value.trim(),
    categoryId.value,
    tagIds.value.slice().sort((a, b) => a - b).join(','),
  ]),
  queryFn: () =>
    apiGet('/api/composer/fragments', {
      search: search.value.trim(),
      category_id: categoryId.value ?? undefined,
      tag_ids: tagIds.value.length ? tagIds.value.join(',') : undefined,
    }),
})

const grouped = computed<Record<string, FragmentItem[]>>(() => fragmentData.value?.grouped ?? {})
const fragmentTotal = computed(() => fragmentData.value?.fragment_count ?? 0)

const { data: catData } = useQuery<{ categories: CategoryNode[] }>({
  queryKey: ['categories', 'prompt'],
  queryFn: () =>
    apiGet<{ categories: CategoryNode[] }>('/api/categories', {
      tree: true,
      count_scope: 'prompt',
    }),
})

const { data: tagData } = useQuery<{ tags: TagRow[] }>({
  queryKey: ['tags', 'prompt'],
  queryFn: () => apiGet<{ tags: TagRow[] }>('/api/tags', { count_scope: 'prompt' }),
})

const flatCats = computed(() => {
  const out: Array<CategoryNode & { depth: number }> = []
  const walk = (nodes: CategoryNode[], depth: number) => {
    nodes.forEach((node) => {
      out.push({ ...node, depth })
      if (node.children?.length) walk(node.children, depth + 1)
    })
  }
  walk(catData.value?.categories ?? [], 0)
  return out
})

/** 折叠状态：默认全部展开，点标题收起。 */
const collapsed = ref<Record<string, boolean>>({})
function toggleGroup(type: string) {
  collapsed.value = { ...collapsed.value, [type]: !collapsed.value[type] }
}

/**
 * 每组默认只渲染 30 个。
 *
 * 线上碎片池有 2100+ 个（提示词碎片 × 8 类型 + 碎片库合并去重），
 * 全部铺开会产生 6000+ 个 DOM 节点，首屏和滚动都会明显发卡。
 * 想看全部再点"展开"。
 */
const PAGE_SIZE = 30
const expanded = ref<Record<string, boolean>>({})

function visibleFrags(type: string): FragmentItem[] {
  const list = grouped.value[type] ?? []
  return expanded.value[type] ? list : list.slice(0, PAGE_SIZE)
}

function expandGroup(type: string) {
  expanded.value = { ...expanded.value, [type]: true }
}

// ---------------- 画布 ----------------

/** 每个类型一个槽位；同类型只能有一个碎片（这是【类型】格式的约束）。 */
const canvas = ref<Record<string, string>>({})

const canvasTypes = computed(() => FRAGMENT_TYPES.filter((t) => canvas.value[t]))
const canvasCount = computed(() => canvasTypes.value.length)

/** 渲染成标准文本：与后端 `composition.render` 完全一致的格式。 */
const composedPrompt = computed(() =>
  FRAGMENT_TYPES.filter((t) => canvas.value[t])
    .map((t) => `【${t}】\n${canvas.value[t]}`)
    .join('\n\n'),
)

function pick(item: FragmentItem) {
  canvas.value = { ...canvas.value, [item.type]: item.content }
}

function unpick(type: string) {
  const next = { ...canvas.value }
  delete next[type]
  canvas.value = next
}

function clearCanvas() {
  canvas.value = {}
}

const negativePrompt = ref('')

// ---------------- 跑图 ----------------

/** 画布上的碎片作为"固定碎片"，其余类型由后端随机填充。 */
const randomCount = ref(4)

function fixedFragments(): Record<string, string> {
  const fixed: Record<string, string> = {}
  for (const type of canvasTypes.value) fixed[type] = canvas.value[type]
  return fixed
}

async function runOnce() {
  if (!composedPrompt.value) return
  if (!workflowPath.value) {
    alert('请先选择工作流')
    return
  }
  try {
    const result = await apiPost<{ success: boolean; job_id: number }>('/api/composer/run', {
      prompt: composedPrompt.value,
      negative_prompt: negativePrompt.value,
      workflow_path: workflowPath.value,
      quality: quality.value,
      orientation: orientation.value,
    })
    if (result.success) track(result.job_id)
  } catch (e) {
    alert(`提交失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

async function runRandom() {
  if (!workflowPath.value) {
    alert('请先选择工作流')
    return
  }
  try {
    const result = await apiPost<{ success: boolean; job_id: number }>(
      '/api/composer/batch_random_run',
      {
        count: randomCount.value,
        workflow_path: workflowPath.value,
        quality: quality.value,
        orientation: orientation.value,
        negative_prompt: negativePrompt.value,
        search: search.value.trim(),
        category_id: categoryId.value,
        tag_ids: tagIds.value.length ? tagIds.value.join(',') : null,
        fixed_fragments: fixedFragments(),
      },
    )
    if (result.success) track(result.job_id)
  } catch (e) {
    alert(`提交失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

function toggleTag(id: number) {
  const idx = tagIds.value.indexOf(id)
  if (idx >= 0) tagIds.value.splice(idx, 1)
  else tagIds.value.push(id)
}
</script>

<template>
  <div class="composer">
    <aside class="filters">
      <section class="group">
        <div class="group-head"><span>筛选</span></div>
        <input v-model="search" type="search" placeholder="搜索碎片内容…" />
      </section>

      <section class="group">
        <div class="group-head"><span>分类</span></div>
        <div class="cat-list">
          <button class="cat" :class="{ active: categoryId === null }" @click="categoryId = null">
            全部
          </button>
          <button
            v-for="cat in flatCats"
            :key="cat.id"
            class="cat"
            :class="{ active: categoryId === cat.id }"
            :style="{ paddingLeft: `${8 + cat.depth * 14}px` }"
            @click="categoryId = cat.id"
          >
            <span class="dot" :style="{ background: cat.color }" />
            <span class="cat-name">{{ cat.name }}</span>
          </button>
        </div>
      </section>

      <section class="group">
        <div class="group-head"><span>标签</span></div>
        <TagCloud
          :tags="tagData?.tags ?? []"
          :selected="tagIds"
          :match="tagMatch"
          empty-text="暂无带提示词的标签"
          @toggle="toggleTag"
          @update:match="tagMatch = $event"
        />
      </section>
    </aside>

    <section class="pool">
      <div class="pool-head">
        <span>碎片池</span>
        <span class="count">
          {{ fragmentTotal }} 个碎片<span v-if="isFetching"> · 加载中</span>
        </span>
      </div>

      <div class="pool-body">
        <div v-for="type in FRAGMENT_TYPES" :key="type" class="frag-group">
          <button class="frag-head" @click="toggleGroup(type)">
            <span class="arrow">{{ collapsed[type] ? '▸' : '▾' }}</span>
            <span class="frag-type">{{ type }}</span>
            <span class="frag-num">{{ (grouped[type] ?? []).length }}</span>
          </button>

          <div v-if="!collapsed[type]" class="frag-list">
            <button
              v-for="(item, idx) in visibleFrags(type)"
              :key="`${type}-${item.fragment_id ?? item.prompt_id}-${idx}`"
              class="frag"
              :class="{ used: canvas[type] === item.content }"
              :title="item.content"
              @click="pick(item)"
            >
              <span class="frag-text">{{ item.content }}</span>
              <span class="frag-meta">
                {{ item.source === 'library' ? '碎片库' : item.prompt_name || '提示词' }}
                <i v-if="item.dup_count > 1">×{{ item.dup_count }}</i>
              </span>
            </button>
            <button
              v-if="!expanded[type] && (grouped[type] ?? []).length > PAGE_SIZE"
              class="more"
              @click="expandGroup(type)"
            >
              展开全部 {{ (grouped[type] ?? []).length }} 个
            </button>
            <div v-if="!(grouped[type] ?? []).length" class="empty">该类型暂无碎片</div>
          </div>
        </div>
      </div>
    </section>

    <aside class="canvas-pane">
      <div class="canvas-head">
        <span>组合画布</span>
        <span class="count">{{ canvasCount }} / 8</span>
        <span class="spacer" />
        <button class="btn btn-sm" :disabled="!canvasCount" @click="clearCanvas">清空</button>
      </div>

      <div class="slots">
        <div v-for="type in FRAGMENT_TYPES" :key="type" class="slot" :class="{ filled: !!canvas[type] }">
          <span class="slot-type">{{ type }}</span>
          <template v-if="canvas[type]">
            <span class="slot-text">{{ canvas[type] }}</span>
            <button class="slot-remove" title="移除" @click="unpick(type)">✕</button>
          </template>
          <span v-else class="slot-empty">点击左侧碎片填入</span>
        </div>
      </div>

      <label class="field">
        <span>负向提示词</span>
        <textarea v-model="negativePrompt" spellcheck="false" />
      </label>

      <div class="preview">
        <div class="preview-head">预览（提交给 ComfyUI 时会自动去掉【类型】标题）</div>
        <pre>{{ composedPrompt || '（画布为空）' }}</pre>
      </div>

      <div class="actions">
        <span v-if="generateError" class="gen-error">{{ generateError }}</span>
        <span v-else-if="activeJob" class="job-state" :class="activeJob.status">
          {{ activeJob.status }} {{ activeJob.done_count ?? 0 }}/{{ activeJob.total ?? 1 }}
        </span>
        <span class="spacer" />
        <button class="btn btn-sm" :disabled="generating" @click="runRandom">
          随机组合 {{ randomCount }} 组
        </button>
        <input v-model.number="randomCount" class="count-input" type="number" min="1" max="10" />
        <button class="btn btn-sm primary" :disabled="generating || !canvasCount" @click="runOnce">
          {{ generating ? '生成中…' : '🚀 试跑' }}
        </button>
      </div>

      <div class="settings">
        <select v-model="workflowPath" class="wf-select">
          <option value="">选择工作流…</option>
          <option v-for="wf in workflows" :key="wf.path" :value="wf.path">{{ wf.name }}</option>
        </select>
        <select v-model="quality">
          <option v-for="q in QUALITY_OPTIONS" :key="q" :value="q">{{ q }}</option>
        </select>
        <button
          class="btn btn-sm"
          title="横竖屏"
          @click="orientation = orientation === 'portrait' ? 'landscape' : 'portrait'"
        >
          {{ orientation === 'portrait' ? '📱 竖' : '🖥️ 横' }}
        </button>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.composer {
  display: flex;
  height: 100%;
  min-height: 0;
}

.filters {
  width: 220px;
  flex: none;
  border-right: 1px solid var(--border);
  background: var(--panel);
  padding: var(--gap);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--gap-lg);
}

.group-head {
  font-size: var(--fs-sm);
  color: var(--muted);
  margin-bottom: var(--gap-sm);
}

.cat-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.cat {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  border: none;
  background: transparent;
  border-radius: var(--radius-sm);
  padding: 4px 8px;
  font-size: var(--fs-sm);
  text-align: left;
}

.cat:hover {
  background: var(--panel-2);
}

.cat.active {
  background: var(--primary-soft);
  color: var(--primary);
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex: none;
}

.cat-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pool {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border);
}

.pool-head {
  display: flex;
  align-items: center;
  gap: var(--gap);
  padding: var(--gap) var(--gap-lg);
  border-bottom: 1px solid var(--border);
  font-size: var(--fs-sm);
}

.count {
  color: var(--muted);
  font-size: var(--fs-xs);
}

.pool-body {
  flex: 1;
  overflow-y: auto;
  padding: var(--gap);
}

.frag-group {
  margin-bottom: var(--gap);
}

.frag-head {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  width: 100%;
  border: none;
  background: transparent;
  padding: 4px 2px;
  font-size: var(--fs-sm);
  color: var(--muted);
  border-bottom: 1px solid var(--border);
}

.frag-head:hover {
  color: var(--text);
}

.arrow {
  width: 12px;
}

.frag-type {
  font-weight: 600;
}

.frag-num {
  margin-left: auto;
  font-size: var(--fs-xs);
}

.frag-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 6px;
  padding: var(--gap-sm) 0;
}

.frag {
  display: flex;
  flex-direction: column;
  gap: 2px;
  text-align: left;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
  padding: 6px 8px;
  transition: 0.12s;
}

.frag:hover {
  border-color: var(--primary);
  background: var(--panel-3);
}

.frag.used {
  border-color: var(--primary);
  background: var(--primary-soft);
}

.frag-text {
  font-size: var(--fs-xs);
  color: var(--text);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.frag-meta {
  font-size: 10px;
  color: var(--muted);
}

.more {
  grid-column: 1 / -1;
  border: 1px dashed var(--border);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--muted);
  font-size: var(--fs-xs);
  padding: 4px;
}

.more:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.canvas-pane {
  width: 400px;
  flex: none;
  background: var(--panel);
  padding: var(--gap);
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  overflow-y: auto;
}

.canvas-head {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-size: var(--fs-sm);
}

.spacer {
  flex: 1;
}

.slots {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.slot {
  display: flex;
  align-items: flex-start;
  gap: var(--gap-sm);
  padding: 5px 8px;
  border-radius: var(--radius-sm);
  border: 1px dashed var(--border);
  font-size: var(--fs-xs);
  min-height: 30px;
}

.slot.filled {
  border-style: solid;
  border-color: var(--primary);
  background: var(--primary-soft);
}

.slot-type {
  flex: none;
  width: 56px;
  color: var(--muted);
}

.slot-text {
  flex: 1;
  color: var(--text);
  max-height: 48px;
  overflow: hidden;
}

.slot-empty {
  color: var(--border-strong);
}

.slot-remove {
  flex: none;
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: var(--fs-xs);
}

.slot-remove:hover {
  color: var(--danger);
}

.field {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  font-size: var(--fs-sm);
  color: var(--muted);
}

.field textarea {
  min-height: 52px;
  resize: vertical;
  font: inherit;
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--gap-sm);
  outline: none;
}

.preview {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.preview-head {
  padding: 4px 8px;
  font-size: 10px;
  color: var(--muted);
  background: var(--panel-2);
  border-bottom: 1px solid var(--border);
}

.preview pre {
  margin: 0;
  padding: var(--gap-sm);
  max-height: 160px;
  overflow-y: auto;
  font-size: var(--fs-xs);
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--muted);
}

.actions {
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
  font-size: var(--fs-xs);
}

.count-input {
  width: 46px;
  padding: 2px 4px;
}

.gen-error {
  color: var(--danger);
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

.settings {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
}

.wf-select {
  flex: 1;
  min-width: 0;
}

.empty {
  font-size: var(--fs-xs);
  color: var(--muted);
}
</style>
