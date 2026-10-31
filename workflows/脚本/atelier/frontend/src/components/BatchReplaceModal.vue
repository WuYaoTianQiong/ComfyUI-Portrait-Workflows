<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useQuery } from '@tanstack/vue-query'

import Modal from './Modal.vue'
import { apiGet } from '../api/client'
import { FRAGMENT_TYPES } from '../constants'
import { batchReplaceSegments } from '../utils/segmentation'
import type { WorkflowCaps } from '../composables/useWorkflowCaps'

/**
 * 批量替换碎片：把提示词里某一类碎片换成同一段内容后出图。
 *
 * 候选碎片来自"所有提示词里出现过的同类碎片 + 碎片库"，所以能搜到具体那一段；
 * 范围优先用左侧已勾选，没勾选才用当前筛选全部；不写回提示词库。
 */
interface FullPromptRow {
  id: number
  name: string
  prompt: string
  seed: number | null
}

interface CandidateRow {
  fragment_id?: number
  prompt_id: number | null
  prompt_name: string
  type: string
  content: string
  source: 'prompt' | 'library'
  dup_count: number
}

const props = defineProps<{
  open: boolean
  search: string
  categoryId: number | null
  tagIds: number[]
  tagMatch: 'all' | 'any'
  selectedIds: number[]
  workflowPath: string
  quality: string
  orientation: 'portrait' | 'landscape'
  caps: WorkflowCaps
}>()

const emit = defineEmits<{
  close: []
  submit: [
    payload: {
      type: string
      items: Array<{ promptId: number; seed: number; promptOverride: string }>
    },
  ]
}>()

const targetType = ref('')
const replacement = ref('')
const fragQuery = ref('')
const promptQuery = ref('')
const selected = ref<Set<number>>(new Set())

/** 勾选优先：左侧有勾选就只看勾选项，没勾选才用当前筛选全部。 */
const scope = ref<'selected' | 'filtered'>(
  props.selectedIds.length ? 'selected' : 'filtered',
)

watch(
  () => props.open,
  (open) => {
    if (!open) return
    scope.value = props.selectedIds.length ? 'selected' : 'filtered'
    targetType.value = ''
    replacement.value = ''
    fragQuery.value = ''
    promptQuery.value = ''
    selected.value = new Set()
  },
)

const usingSelected = computed(() => scope.value === 'selected')

const { data: fullData } = useQuery<{ items: FullPromptRow[]; total: number }>({
  queryKey: computed(() =>
    usingSelected.value
      ? ['prompts-full', 'ids', props.selectedIds.slice().sort((a, b) => a - b).join(',')]
      : [
          'prompts-full',
          'filter',
          props.search.trim(),
          props.categoryId,
          props.tagIds.slice().sort((a, b) => a - b).join(','),
          props.tagMatch,
        ],
  ),
  queryFn: () =>
    usingSelected.value
      ? apiGet('/api/prompts/full', { ids: props.selectedIds.join(',') })
      : apiGet('/api/prompts/full', {
          search: props.search.trim(),
          category_id: props.categoryId ?? undefined,
          tag_ids: props.tagIds.length ? props.tagIds.join(',') : undefined,
          tag_match: props.tagMatch,
        }),
  enabled: computed(
    () => props.open && (!usingSelected.value || props.selectedIds.length > 0),
  ),
})

/** 候选 = 所有提示词里的同类碎片 + 碎片库，后端已按内容去重。 */
const { data: candidateData, isFetching: candidatesLoading } = useQuery<{
  grouped: Record<string, CandidateRow[]>
}>({
  queryKey: computed(() => ['replace-candidates', targetType.value]),
  queryFn: () =>
    apiGet('/api/composer/fragments', { fragment_type: targetType.value }),
  enabled: computed(() => props.open && !!targetType.value),
})

const candidates = computed(
  () => candidateData.value?.grouped?.[targetType.value] ?? [],
)

const filteredCandidates = computed(() => {
  const q = fragQuery.value.trim().toLowerCase()
  if (!q) return candidates.value
  return candidates.value.filter((c) =>
    `${c.content} ${c.prompt_name} ${c.type}`.toLowerCase().includes(q),
  )
})

function useCandidate(c: CandidateRow) {
  replacement.value = c.content
}

watch(targetType, () => {
  fragQuery.value = ''
})

interface MatchedRow {
  id: number
  name: string
  seed: number
  oldContent: string
  replaced: string
}

/**
 * 只列出"本来就有这一片"的提示词；其余计入跳过数。
 *
 * 预览由后端算（`POST /api/composition/batch_replace`）—— `【类型】` 语法只有
 * 后端一份实现，替换也保持"其他块原样保留"的语义。一次往返算完整个范围。
 * 用递增序号丢弃过期响应：用户连续修改内容时，先发的请求可能后到。
 */
const previewRows = ref<MatchedRow[]>([])
let previewSeq = 0

watch(
  [targetType, replacement, () => fullData.value?.items],
  async () => {
    const type = targetType.value
    const text = replacement.value.trim()
    const items = fullData.value?.items ?? []
    if (!props.open || !type || !text || !items.length) {
      previewRows.value = []
      return
    }
    const seq = ++previewSeq
    try {
      const outcomes = await batchReplaceSegments(
        items.map((p) => ({ id: p.id, text: p.prompt })),
        type,
        text,
      )
      if (seq !== previewSeq) return
      previewRows.value = items.flatMap((p) => {
        const hit = outcomes.get(p.id)
        if (!hit || hit.replaced === null) return []
        return [{
          id: p.id,
          name: p.name || `#${p.id}`,
          seed: p.seed ?? 0,
          oldContent: hit.oldContent,
          replaced: hit.replaced,
        }]
      })
    } catch {
      if (seq === previewSeq) previewRows.value = []
    }
  },
  { immediate: true },
)

const matchedAll = computed<MatchedRow[]>(() => previewRows.value)

/** 列表内的检索只影响"看/批量勾选"，不影响已经选中的其他条目。 */
const visibleRows = computed<MatchedRow[]>(() => {
  const q = promptQuery.value.trim().toLowerCase()
  if (!q) return matchedAll.value
  return matchedAll.value.filter((r) =>
    `${r.name} ${r.oldContent} ${r.replaced}`.toLowerCase().includes(q),
  )
})

const totalCount = computed(() => fullData.value?.items.length ?? 0)
const skippedCount = computed(() => Math.max(0, totalCount.value - matchedAll.value.length))

/** 类型/范围/内容变化后默认全选匹配项；检索不改变已选集合。 */
watch(
  () => matchedAll.value.map((r) => r.id).join(','),
  () => {
    selected.value = new Set(matchedAll.value.map((r) => r.id))
  },
)

const selectedCount = computed(
  () => matchedAll.value.filter((r) => selected.value.has(r.id)).length,
)

function toggle(id: number) {
  const next = new Set(selected.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selected.value = next
}

function selectVisible() {
  const next = new Set(selected.value)
  for (const row of visibleRows.value) next.add(row.id)
  selected.value = next
}

function clearVisible() {
  const next = new Set(selected.value)
  for (const row of visibleRows.value) next.delete(row.id)
  selected.value = next
}

function invertVisible() {
  const next = new Set(selected.value)
  for (const row of visibleRows.value) {
    if (next.has(row.id)) next.delete(row.id)
    else next.add(row.id)
  }
  selected.value = next
}

function submit() {
  const type = targetType.value
  if (!type || !selectedCount.value) return
  const items = matchedAll.value
    .filter((r) => selected.value.has(r.id))
    .map((r) => ({ promptId: r.id, seed: r.seed, promptOverride: r.replaced }))
  emit('submit', { type, items })
}
</script>

<template>
  <Modal
    :open="open"
    title="批量替换碎片"
    width="min(1180px, 96vw)"
    @close="emit('close')"
  >
    <div class="pane">
      <p class="intro">
        把同一类碎片换成同一段内容，再批量出图。原提示词不会被修改。
      </p>

      <div class="step-row">
        <span class="step-no">1</span>
        <span class="step-title">类型与范围</span>
        <select v-model="targetType" class="type-select">
          <option value="">选择碎片类型…</option>
          <option v-for="t in FRAGMENT_TYPES" :key="t" :value="t">【{{ t }}】</option>
        </select>

        <div class="seg">
          <button
            class="btn btn-sm"
            :class="{ on: scope === 'selected' }"
            :disabled="!selectedIds.length"
            :title="selectedIds.length ? '只替换左侧已勾选的提示词' : '左侧还没有勾选'"
            @click="scope = 'selected'"
          >
            已勾选 {{ selectedIds.length }} 条
          </button>
          <button
            class="btn btn-sm"
            :class="{ on: scope === 'filtered' }"
            title="替换当前筛选下的全部提示词"
            @click="scope = 'filtered'"
          >
            当前筛选全部
          </button>
        </div>

        <span class="count">
          <template v-if="!targetType">先选择碎片类型</template>
          <template v-else-if="!replacement.trim()">填好替换内容后显示匹配数量</template>
          <template v-else>
            范围 {{ totalCount }} 条 · 可替换 {{ matchedAll.length }} 条
            <template v-if="skippedCount"> · 跳过 {{ skippedCount }} 条</template>
          </template>
        </span>
        <span v-if="!caps.prompt" class="warn">当前工作流不注入提示词，无法替换出图</span>
      </div>

      <div class="main">
        <section class="left">
          <div class="panel-head">
            <span class="step-no">2</span>
            <span class="step-title">替换为</span>
            <span class="spacer" />
            <button
              v-if="replacement"
              class="btn btn-sm"
              title="清空替换内容"
              @click="replacement = ''"
            >
              清空
            </button>
          </div>

          <textarea
            v-model="replacement"
            class="content-input"
            spellcheck="false"
            placeholder="只替换目标【类型】块，其他块原样保留；也可以直接手写"
          />

          <div class="panel-head">
            <span>候选碎片</span>
            <span class="count">
              {{ candidates.length }} 条 · 来自提示词与碎片库
            </span>
          </div>
          <input
            v-model="fragQuery"
            class="cand-search"
            type="search"
            placeholder="搜索候选内容，例如：纤细、短发、夜景…"
          />

          <div v-if="filteredCandidates.length" class="cand-list">
            <button
              v-for="c in filteredCandidates"
              :key="`${c.source}-${c.fragment_id ?? c.prompt_id}-${c.content}`"
              class="cand-row"
              :class="{ on: c.content === replacement.trim() }"
              :title="c.content"
              @click="useCandidate(c)"
            >
              <span class="cand-content">{{ c.content }}</span>
              <span class="cand-meta">
                {{ c.source === 'library' ? '碎片库' : c.prompt_name || '提示词' }}
                <i v-if="c.dup_count > 1">×{{ c.dup_count }}</i>
              </span>
            </button>
          </div>
          <div v-else class="empty-line">
            <template v-if="!targetType">先选择碎片类型</template>
            <template v-else-if="candidatesLoading">正在读取候选碎片…</template>
            <template v-else-if="fragQuery.trim()">没有匹配的候选，可直接手写</template>
            <template v-else>这类碎片在提示词库和碎片库里都还没有，可直接手写</template>
          </div>
        </section>

        <section class="right">
          <div class="panel-head">
            <span class="step-no">3</span>
            <span class="step-title">待替换的提示词</span>
            <span class="spacer" />
            <span class="count">已选 {{ selectedCount }} / {{ matchedAll.length }}</span>
          </div>

          <div class="list-toolbar">
            <input
              v-model="promptQuery"
              class="prompt-search"
              type="search"
              placeholder="按名称或原碎片过滤"
            />
            <button class="btn btn-sm" :disabled="!visibleRows.length" @click="selectVisible">
              全选
            </button>
            <button class="btn btn-sm" :disabled="!visibleRows.length" @click="clearVisible">
              取消全选
            </button>
            <button class="btn btn-sm" :disabled="!visibleRows.length" @click="invertVisible">
              反选
            </button>
          </div>

          <div v-if="visibleRows.length" class="prompt-list">
            <label
              v-for="row in visibleRows"
              :key="row.id"
              class="row"
              :class="{ picked: selected.has(row.id) }"
              :title="row.replaced"
            >
              <input
                type="checkbox"
                :checked="selected.has(row.id)"
                @change="toggle(row.id)"
              />
              <span class="name">{{ row.name }}</span>
              <span class="old">{{ row.oldContent || '（该块为空）' }}</span>
              <span class="arrow">→</span>
              <span class="new">{{ replacement }}</span>
            </label>
          </div>
          <div v-else class="empty-line">
            <template v-if="!targetType">先选择碎片类型</template>
            <template v-else-if="!replacement.trim()">填好替换内容后，这里会列出待替换的提示词</template>
            <template v-else-if="promptQuery.trim()">没有匹配的提示词</template>
            <template v-else>这个范围里没有含【{{ targetType }}】的提示词</template>
          </div>
        </section>
      </div>
    </div>

    <template #footer>
      <span class="note">只影响本次出图，不修改提示词库</span>
      <span v-if="workflowPath" class="wf-name" :title="workflowPath">
        {{ workflowPath.split(/[\\/]/).pop() }}
      </span>
      <span class="spacer" />
      <button class="btn btn-sm" @click="emit('close')">取消</button>
      <button
        class="btn btn-sm primary"
        :disabled="!selectedCount || !caps.prompt || !workflowPath"
        @click="submit"
      >
        替换并出图 {{ selectedCount }} 条
      </button>
    </template>
  </Modal>
</template>

<style scoped>
.pane {
  box-sizing: border-box;
  padding: var(--gap) var(--gap-lg);
  display: flex;
  flex-direction: column;
  gap: var(--gap);
}

.intro {
  margin: 0;
  color: var(--muted);
  font-size: var(--fs-xs);
}

.step-row {
  display: flex;
  align-items: center;
  gap: var(--gap);
  flex-wrap: wrap;
}

.step-no,
.panel-head .step-no {
  display: inline-grid;
  place-items: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 11px;
  font-weight: 600;
  flex: none;
}

.step-title {
  font-weight: 600;
  font-size: var(--fs-sm);
  color: var(--text);
}

.type-select {
  min-width: 150px;
}

.seg {
  display: flex;
  gap: var(--gap-xs);
}

.seg .btn.on {
  border-color: var(--primary);
  background: var(--primary-soft);
  color: var(--primary);
}

.main {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  gap: var(--gap-lg);
  align-items: start;
}

.left,
.right {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
}

.panel-head {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-size: var(--fs-xs);
  color: var(--muted);
}

.content-input {
  width: 100%;
  box-sizing: border-box;
  min-height: 88px;
  max-height: 180px;
  resize: vertical;
  font: inherit;
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 5px 8px;
}

.cand-search,
.prompt-search {
  width: 100%;
  box-sizing: border-box;
}

.prompt-search {
  flex: 1 1 200px;
  min-width: 140px;
  width: auto;
}

.cand-list {
  max-height: 200px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 4px;
  background: var(--panel-2);
}

.cand-row {
  display: flex;
  flex-direction: column;
  gap: 1px;
  text-align: left;
  padding: 4px 6px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text);
}

.cand-row:hover {
  background: var(--panel-3);
}

.cand-row.on {
  border-color: var(--primary);
  background: var(--primary-soft);
}

.cand-content {
  font-size: var(--fs-xs);
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.cand-meta {
  font-size: 10px;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.list-toolbar {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  flex-wrap: wrap;
}

.prompt-list {
  max-height: 46vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 4px;
  background: var(--panel-2);
}

.empty-line {
  padding: 14px;
  color: var(--muted);
  font-size: var(--fs-xs);
}

.row {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: 4px 6px;
  border-radius: var(--radius-sm);
  font-size: var(--fs-xs);
  cursor: pointer;
}

.row:hover {
  background: var(--panel-3);
}

.row.picked {
  background: var(--primary-soft);
}

.name {
  flex: 0 0 140px;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.old,
.new {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.old {
  color: var(--muted);
  text-decoration: line-through;
}

.new {
  color: var(--primary);
}

.arrow {
  flex: none;
  color: var(--muted);
}

.count {
  color: var(--muted);
  font-size: var(--fs-xs);
  white-space: nowrap;
}

.warn {
  color: var(--warn);
  font-size: var(--fs-xs);
}

.note {
  color: var(--muted);
  font-size: var(--fs-xs);
}

.wf-name {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--muted);
  font-size: var(--fs-xs);
}

.spacer {
  flex: 1;
}

@media (max-width: 900px) {
  .main {
    grid-template-columns: 1fr;
  }

  .prompt-list {
    max-height: 38vh;
  }
}
</style>
