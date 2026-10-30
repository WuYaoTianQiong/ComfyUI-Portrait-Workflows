<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'

import TagCloud from '../components/TagCloud.vue'
import TagInput from '../components/TagInput.vue'
import MissingRunPanel from '../components/MissingRunPanel.vue'
import { apiDelete, apiGet, apiPost, apiPut } from '../api/client'
import EmptyState from '../components/EmptyState.vue'
import { QUALITY_OPTIONS, useSettings } from '../composables/useSettings'
import { useGenerate } from '../composables/useGenerate'
import { useWorkflows, useWorkflowValidation } from '../composables/useWorkflows'
import { statusLabel } from '../utils/format'
import RunTextPanel from '../components/RunTextPanel.vue'
import type { CategoryNode, PromptDetail, PromptListPage, TagRow } from '../api/types'

const { workflowPath, quality, orientation } = useSettings()
const {
  busy: generating,
  job: activeJob,
  error: generateError,
  run,
  runBatch,
} = useGenerate()

const pageSize = 50
const page = ref(1)
const search = ref('')
const categoryId = ref<number | null>(null)
const missingOpen = ref(false)
const tagIds = ref<number[]>([])
const tagMatch = ref<'all' | 'any'>('all')
const selectedId = ref<number | null>(null)

const queryClient = useQueryClient()

const listKey = computed(() => [
  'prompts',
  page.value,
  search.value.trim(),
  categoryId.value,
  tagIds.value.slice().sort((a, b) => a - b).join(','),
  tagMatch.value,
])

const { data: listData, isFetching } = useQuery<PromptListPage>({
  queryKey: listKey,
  queryFn: () =>
    apiGet<PromptListPage>('/api/prompts', {
      page: page.value,
      page_size: pageSize,
      search: search.value.trim(),
      category_id: categoryId.value ?? undefined,
      tag_ids: tagIds.value.join(','),
      tag_match: tagMatch.value,
    }),
  placeholderData: (prev) => prev,
})

const list = computed(() => listData.value?.prompts ?? [])
const total = computed(() => listData.value?.total ?? 0)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

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

const { workflows } = useWorkflows()
const textPanelOpen = ref(false)
const { data: wfValidation } = useWorkflowValidation(workflowPath)

function toggleOrientation() {
  orientation.value = orientation.value === 'portrait' ? 'landscape' : 'portrait'
}

function generate() {
  if (!draft.value) return
  run(draft.value.id, {
    workflowPath: workflowPath.value,
    quality: quality.value,
    orientation: orientation.value,
  })
}



/** 树拍平成一维，带 depth 做缩进 —— 分类层级只有两级，递归组件是过度设计。 */
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

// ---------------- 详情 ----------------

const { data: detail } = useQuery<PromptDetail>({
  queryKey: computed(() => ['prompt', selectedId.value]),
  queryFn: () => apiGet<PromptDetail>(`/api/prompts/${selectedId.value}`),
  enabled: computed(() => selectedId.value !== null),
})

const draft = ref<PromptDetail | null>(null)
watch(
  detail,
  (value) => {
    draft.value = value ? { ...value } : null
  },
  { immediate: true },
)

/** 列表变化后保证"总有一条被选中"，避免右侧空着。 */
watch(
  list,
  (items) => {
    if (!items.length) return
    if (selectedId.value === null || !items.some((it) => it.id === selectedId.value)) {
      selectedId.value = items[0].id
    }
  },
  { immediate: true },
)

const dirty = computed(() => {
  if (!draft.value || !detail.value) return false
  return (
    draft.value.name !== detail.value.name ||
    draft.value.tags !== detail.value.tags ||
    draft.value.prompt !== detail.value.prompt ||
    draft.value.negative_prompt !== detail.value.negative_prompt ||
    draft.value.note !== detail.value.note
  )
})

function invalidateAll(id: number | null) {
  queryClient.invalidateQueries({ queryKey: ['prompts'] })
  if (id !== null) queryClient.invalidateQueries({ queryKey: ['prompt', id] })
  queryClient.invalidateQueries({ queryKey: ['tags'] })
}

/**
 * 关联 / 取消关联分类。
 *
 * 分类没有文本字段，关联只存在于 prompt_categories 表，所以必须走专用端点；
 * 不像标签那样"改文本再同步"。成功后同时失效详情与列表缓存 —— 分类计数会变。
 */
const categoryMutation = useMutation({
  mutationFn: (payload: { catId: number; attach: boolean }) =>
    payload.attach
      ? apiPost(`/api/categories/${payload.catId}/prompts/${selectedId.value}`)
      : apiDelete(`/api/categories/${payload.catId}/prompts/${selectedId.value}`),
  onSuccess: () => {
    if (selectedId.value !== null) {
      queryClient.invalidateQueries({ queryKey: ['prompt', selectedId.value] })
    }
    queryClient.invalidateQueries({ queryKey: ['prompts'] })
    queryClient.invalidateQueries({ queryKey: ['categories'] })
  },
})

function isLinked(catId: number): boolean {
  return (detail.value?.categories ?? []).some((c) => c.id === catId)
}

function toggleCategory(catId: number) {
  if (selectedId.value === null) return
  categoryMutation.mutate({ catId, attach: !isLinked(catId) })
}
/**
 * 标签数组 ↔ `prompts.tags` 文本互转。
 *
 * 拆分规则必须与后端 `services/taxonomy.split_tags` 一致：只按中英文逗号与分号拆，
 * **不拆空格** —— 库里有 "Moody Photography" 这种带空格的标签，拆开就是两个垃圾标签。
 */
function splitTagText(text: string): string[] {
  return text
    .split(/[,，;；]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

const draftTagList = computed<string[]>({
  get: () => splitTagText(draft.value?.tags ?? ''),
  set: (list: string[]) => {
    if (draft.value) draft.value.tags = list.join(',')
  },
})
/** 单条自动归类：按提示词正文里的【类型】数量归入 组合/单项/零散。 */
const autoClassifyMutation = useMutation({
  mutationFn: (id: number) => apiPost(`/api/categories/auto-classify/${id}`),
  onSuccess: () => {
    if (selectedId.value !== null) {
      queryClient.invalidateQueries({ queryKey: ['prompt', selectedId.value] })
    }
    queryClient.invalidateQueries({ queryKey: ['prompts'] })
    queryClient.invalidateQueries({ queryKey: ['categories'] })
  },
})

function autoClassifyOne() {
  if (selectedId.value === null) return
  autoClassifyMutation.mutate(selectedId.value)
}
const saveMutation = useMutation({
  mutationFn: (payload: Partial<PromptDetail>) =>
    apiPut<{ success: boolean }>(`/api/prompts/${selectedId.value}`, payload),
  onSuccess: () => invalidateAll(selectedId.value),
})

function save() {
  if (!draft.value) return
  saveMutation.mutate({
    name: draft.value.name,
    tags: draft.value.tags,
    prompt: draft.value.prompt,
    negative_prompt: draft.value.negative_prompt,
    note: draft.value.note,
  })
}

function revert() {
  draft.value = detail.value ? { ...detail.value } : null
}

const favoriteMutation = useMutation({
  mutationFn: () => apiPost(`/api/prompts/${selectedId.value}/favorite`),
  onSuccess: () => invalidateAll(selectedId.value),
})

const pinMutation = useMutation({
  mutationFn: () => apiPost(`/api/prompts/${selectedId.value}/pin`),
  onSuccess: () => invalidateAll(selectedId.value),
})

const rateMutation = useMutation({
  mutationFn: (rating: number) =>
    apiPost(`/api/prompts/${selectedId.value}/rate`, undefined, { rating }),
  onSuccess: () => invalidateAll(selectedId.value),
})

// ---------------- 多选与批量 ----------------

const selectedIds = ref<Set<number>>(new Set())
const selectedCount = computed(() => selectedIds.value.size)
const allOnPageSelected = computed(
  () => list.value.length > 0 && list.value.every((it) => selectedIds.value.has(it.id)),
)

function toggleSelect(id: number) {
  if (selectedIds.value.has(id)) selectedIds.value.delete(id)
  else selectedIds.value.add(id)
  selectedIds.value = new Set(selectedIds.value)
}

function selectAllOnPage() {
  selectedIds.value = new Set(list.value.map((it) => it.id))
}

function clearSelection() {
  selectedIds.value = new Set()
}

const batchFavoriteMutation = useMutation({
  mutationFn: (ids: number[]) =>
    apiPost<{ success: boolean }>('/api/prompts/batch_favorite', { ids }, { favorite: true }),
  onSuccess: () => {
    clearSelection()
    queryClient.invalidateQueries({ queryKey: ['prompts'] })
  },
})

const batchDeleteMutation = useMutation({
  mutationFn: (ids: number[]) =>
    apiPost<{ success: boolean; deleted: number }>('/api/prompts/batch_delete', { ids }),
  onSuccess: () => {
    clearSelection()
    queryClient.invalidateQueries({ queryKey: ['prompts'] })
    queryClient.invalidateQueries({ queryKey: ['history'] })
    queryClient.invalidateQueries({ queryKey: ['tags'] })
  },
})

function batchFavorite() {
  if (!selectedIds.value.size) return
  batchFavoriteMutation.mutate(Array.from(selectedIds.value))
}

function batchDelete() {
  const ids = Array.from(selectedIds.value)
  if (!ids.length) return
  if (!confirm(`确定删除选中的 ${ids.length} 条提示词吗？\n\n出图记录会保留在画廊（只解除关联），不会一起删除。`)) return
  batchDeleteMutation.mutate(ids)
}

function batchGenerate() {
  const ids = Array.from(selectedIds.value)
  if (!ids.length) return
  if (!confirm(`用「${workflowPath.value.split('\\').pop() || '未选择'}」出图 ${ids.length} 张？（画质 ${quality.value}）`)) return
  runBatch(ids, {
    workflowPath: workflowPath.value,
    quality: quality.value,
    orientation: orientation.value,
  })
}

// ---------------- 导入 / 导出 ----------------

const fileInput = ref<HTMLInputElement | null>(null)
const importMessage = ref('')

function exportPrompts() {
  window.open('/api/prompts/export', '_blank')
}

const importMutation = useMutation({
  mutationFn: (prompts: unknown[]) =>
    apiPost<{ success: boolean; imported: number; message: string }>('/api/prompts/import', {
      prompts,
    }),
  onSuccess: (result) => {
    importMessage.value = result.message
    queryClient.invalidateQueries({ queryKey: ['prompts'] })
    queryClient.invalidateQueries({ queryKey: ['tags'] })
    queryClient.invalidateQueries({ queryKey: ['categories'] })
  },
})

async function onImportFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  importMessage.value = ''
  try {
    const parsed = JSON.parse(await file.text())
    const rows = Array.isArray(parsed) ? parsed : parsed.prompts
    if (!Array.isArray(rows) || !rows.length) {
      importMessage.value = '文件里没有找到 prompts 数组'
      return
    }
    importMutation.mutate(rows)
  } catch (e) {
    importMessage.value = `解析失败：${e instanceof Error ? e.message : String(e)}`
  }
}

// ---------------- 筛选 ----------------

function selectCategory(id: number | null) {
  categoryId.value = id
  page.value = 1
}

function toggleTag(id: number) {
  const idx = tagIds.value.indexOf(id)
  if (idx >= 0) tagIds.value.splice(idx, 1)
  else tagIds.value.push(id)
  page.value = 1
}

function clearFilters() {
  search.value = ''
  categoryId.value = null
  tagIds.value = []
  tagMatch.value = 'all'
  page.value = 1
}
</script>

<template>
  <div class="prompt-page">
    <aside class="filters">
      <section class="group">
        <div class="group-head">
          <span>分类</span>
          <button class="btn btn-sm" @click="selectCategory(null)">全部</button>
        </div>
        <div class="cat-list">
          <button
            v-for="cat in flatCats"
            :key="cat.id"
            class="cat"
            :class="{ active: categoryId === cat.id }"
            :style="{ paddingLeft: `${8 + cat.depth * 14}px` }"
            @click="selectCategory(cat.id)"
          >
            <span class="dot" :style="{ background: cat.color }" />
            <span class="cat-name">{{ cat.name }}</span>
            <i>{{ cat.prompt_count }}</i>
          </button>
          <EmptyState v-if="!flatCats.length" text="暂无分类" />
        </div>
      </section>

      <section class="group">
        <div class="group-head">
          <span>标签</span>
          <button
            v-if="tagIds.length"
            class="btn btn-sm"
            @click="tagIds = []; page = 1"
          >
            清空 ({{ tagIds.length }})
          </button>
        </div>
        <TagCloud
          :tags="tagData?.tags ?? []"
          :selected="tagIds"
          :match="tagMatch"
          empty-text="暂无带提示词的标签"
          @toggle="toggleTag"
          @update:match="(m) => { tagMatch = m; page = 1 }"
        />
      </section>

      <button class="btn btn-sm full" @click="clearFilters">清除全部筛选</button>
    </aside>

    <section class="list-pane">
      <div class="list-head">
        <input
          v-model="search"
          class="search"
          type="search"
          placeholder="搜索名称 / 内容 / 标签…"
          @input="page = 1"
        />
        <span class="count">{{ total }} 条<span v-if="isFetching"> · 加载中</span></span>
      </div>

      <div class="list-tools">
        <button class="btn btn-sm" @click="allOnPageSelected ? clearSelection() : selectAllOnPage()">
          {{ allOnPageSelected ? '取消本页' : '全选本页' }}
        </button>
        <span v-if="importMessage" class="import-msg">{{ importMessage }}</span>
        <span class="spacer" />
        <button class="btn btn-sm" title="导出全部提示词为 JSON" @click="exportPrompts">导出</button>
        <button class="btn btn-sm" title="从 JSON 导入提示词" @click="fileInput?.click()">导入</button>
        <button
          class="btn btn-sm"
          title="给「有提示词但没出图」的条目补图"
          @click="missingOpen = true"
        >
          补跑缺图
        </button>
        <input
          ref="fileInput"
          type="file"
          accept="application/json,.json"
          hidden
          @change="onImportFile"
        />
      </div>

      <div v-if="selectedCount" class="bulk">
        <span class="bulk-count">已选 <b>{{ selectedCount }}</b> 条</span>
        <button class="btn btn-sm" @click="selectAllOnPage">全选本页</button>
        <button class="btn btn-sm" @click="clearSelection">取消</button>
        <span class="spacer" />
        <button class="btn btn-sm" @click="batchFavorite">收藏</button>
        <button class="btn btn-sm primary" :disabled="generating" @click="batchGenerate">批量出图</button>
        <button class="btn btn-sm danger" @click="batchDelete">删除</button>
      </div>

      <div class="list">
        <div
          v-for="item in list"
          :key="item.id"
          class="row"
          :class="{ active: selectedId === item.id, picked: selectedIds.has(item.id) }"
          @click="selectedId = item.id"
        >
          <button
            class="row-check"
            :class="{ on: selectedIds.has(item.id) }"
            :title="selectedIds.has(item.id) ? '取消选择' : '选择'"
            @click.stop="toggleSelect(item.id)"
          >
            ✓
          </button>
          <div class="row-body">
            <div class="row-title">
              <span v-if="item.is_pinned" class="pin" title="置顶">📌</span>
              <span v-if="item.is_favorite" class="star" title="收藏">★</span>
              <span class="name">{{ item.name || `#${item.id}` }}</span>
              <span v-if="item.rating" class="rating">{{ '★'.repeat(item.rating) }}</span>
            </div>
            <div class="row-preview">{{ item.prompt_preview }}</div>
            <div v-if="item.tags" class="row-tags">{{ item.tags }}</div>
          </div>
        </div>

        <EmptyState v-if="!list.length && !isFetching" size="big" text="没有符合条件的提示词" />
      </div>

      <div class="pager">
        <button class="btn btn-sm" :disabled="page <= 1" @click="page--">上一页</button>
        <span class="page-num">{{ page }} / {{ totalPages }}</span>
        <button class="btn btn-sm" :disabled="page >= totalPages" @click="page++">下一页</button>
      </div>
    </section>

    <section class="detail-pane">
      <EmptyState v-if="!draft" size="big" text="选择左侧任意一条提示词" />

      <div v-else class="detail">
        <div class="generate-bar">
          <select v-model="workflowPath" class="wf-select" title="工作流">
            <option value="">选择工作流…</option>
            <option v-for="wf in workflows" :key="wf.path" :value="wf.path">
              {{ wf.name }}
            </option>
          </select>
          <select v-model="quality" title="画质">
            <option v-for="q in QUALITY_OPTIONS" :key="q" :value="q">{{ q }}</option>
          </select>
          <button class="btn btn-sm" title="横竖屏" @click="toggleOrientation">
            {{ orientation === 'portrait' ? '📱 竖' : '🖥️ 横' }}
          </button>
          <span class="spacer" />
            <span v-if="wfValidation && !wfValidation.valid" class="gen-error">
              工作流不可用：{{ wfValidation.error }}
            </span>
            <span v-else-if="generateError" class="gen-error">{{ generateError }}</span>
          <span v-else-if="activeJob" class="job-state" :class="activeJob?.status">
            {{ statusLabel(activeJob?.status) }} {{ activeJob?.done_count ?? 0 }}/{{ activeJob?.total ?? 1 }}
          </span>
          <button
            class="btn btn-sm"
            title="临时改一下提示词直接出图，不写回提示词库"
            @click="textPanelOpen = true"
          >
            ✎ 改文本跑
          </button>
          <button class="btn btn-sm primary" :disabled="generating || !workflowPath" @click="generate">
            {{ generating ? '生成中…' : '🚀 出图' }}
          </button>
        </div>

        <header class="detail-head">
          <input v-model="draft.name" class="name-input" placeholder="未命名" />
          <button
            class="btn btn-sm"
            :class="{ active: draft.is_favorite }"
            title="收藏"
            @click="favoriteMutation.mutate()"
          >
            {{ draft.is_favorite ? '★ 已收藏' : '☆ 收藏' }}
          </button>
          <button
            class="btn btn-sm"
            :class="{ active: draft.is_pinned }"
            title="置顶"
            @click="pinMutation.mutate()"
          >
            📌
          </button>
        </header>

        <div class="stars">
          <span class="label">评级</span>
          <button
            v-for="n in 5"
            :key="n"
            class="star-btn"
            :class="{ on: (draft.rating ?? 0) >= n }"
            @click="rateMutation.mutate(n)"
          >
            ★
          </button>
          <span class="meta">使用 {{ draft.usage_count }} 次 · 更新 {{ draft.updated_at.slice(0, 16) }}</span>
        </div>
        <div class="field">
          <span>标签（点选已有标签或直接输入新的，保存后同步到标签库）</span>
          <TagInput
            v-model="draftTagList"
            :suggestions="tagData?.tags ?? []"
          />
        </div>

        <div class="field">
          <span class="field-head">
            分类（点一下关联 / 取消）
            <button
              class="btn btn-sm"
              :disabled="autoClassifyMutation.isPending.value"
              title="按提示词正文里的【类型】数量自动归入 组合 / 单项 / 零散"
              @click="autoClassifyOne"
            >
              {{ autoClassifyMutation.isPending.value ? '归类中…' : '自动归类' }}
            </button>
          </span>
          <div class="cat-chips">
            <button
              v-for="cat in flatCats"
              :key="cat.id"
              class="cat-chip"
              :class="{ on: isLinked(cat.id) }"
              :style="{ '--c': cat.color }"
              :title="cat.name"
              @click="toggleCategory(cat.id)"
            >
              {{ cat.name }}
            </button>
            <EmptyState v-if="!flatCats.length" text="暂无分类" compact />
          </div>
        </div>
        <label class="field grow">
          <span>正向提示词</span>
          <textarea v-model="draft.prompt" spellcheck="false" />
        </label>

        <label class="field">
          <span>负向提示词</span>
          <textarea v-model="draft.negative_prompt" spellcheck="false" class="small" />
        </label>

        <label class="field">
          <span>备注</span>
          <input v-model="draft.note" />
        </label>

        <footer class="detail-foot">
          <span v-if="dirty" class="dirty">有未保存的修改</span>
          <span v-else class="saved">已保存</span>
          <span class="spacer" />
          <button class="btn btn-sm" :disabled="!dirty" @click="revert">撤销</button>
          <button class="btn btn-sm primary" :disabled="!dirty || saveMutation.isPending.value" @click="save">
            {{ saveMutation.isPending.value ? '保存中…' : '保存' }}
          </button>
        </footer>
      </div>
    </section>
    <MissingRunPanel :open="missingOpen" @close="missingOpen = false" />
    <RunTextPanel
      :open="textPanelOpen"
      :prompt="draft?.prompt ?? ''"
      :negative-prompt="draft?.negative_prompt ?? ''"
      :prompt-id="draft?.id ?? null"
      @close="textPanelOpen = false"
    />
  </div>
</template>

<style scoped>
.prompt-page {
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
  display: flex;
  align-items: center;
  justify-content: space-between;
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

.cat i {
  font-style: normal;
  font-size: var(--fs-xs);
  color: var(--muted);
}

.full {
  width: 100%;
}

.list-pane {
  width: 340px;
  flex: none;
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.list-head {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap);
  border-bottom: 1px solid var(--border);
}

.search {
  flex: 1;
  min-width: 0;
}

.count {
  font-size: var(--fs-xs);
  color: var(--muted);
  white-space: nowrap;
}

.list {
  flex: 1;
  overflow-y: auto;
}

.list-tools {
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
  padding: 0 var(--gap) var(--gap-sm);
  border-bottom: 1px solid var(--border);
}

.import-msg {
  font-size: var(--fs-xs);
  color: var(--primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 批量操作条：浮在页面底部居中。
   放在 340px 的列表栏里会被挤成竖排文字，这里让它脱离文档流、宽度自适应。 */
.bulk {
  position: fixed;
  bottom: 22px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 50;
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm) var(--gap-lg);
  border-radius: 999px;
  background: var(--panel-3);
  border: 1px solid var(--border-strong);
  box-shadow: var(--shadow);
  font-size: var(--fs-sm);
  white-space: nowrap;
}

.bulk > button {
  flex: none;
}

.bulk-count b {
  color: var(--primary);
}

.btn.primary {
  border-color: var(--primary);
  background: var(--primary);
  color: #fff;
}

.btn.primary:disabled {
  opacity: 0.4;
}

.btn.danger {
  border-color: var(--danger);
  color: #fecaca;
}

.btn.danger:hover {
  background: var(--danger-soft);
}

.row {
  display: flex;
  align-items: flex-start;
  gap: var(--gap-sm);
  border-bottom: 1px solid var(--border);
  padding: var(--gap-sm) var(--gap);
  transition: 0.1s;
  cursor: pointer;
}

.row:hover {
  background: var(--panel-2);
}

.row.active {
  background: var(--primary-soft);
  box-shadow: inset 2px 0 0 var(--primary);
}

.row.picked {
  background: rgba(99, 102, 241, 0.08);
}

.row-check {
  flex: none;
  width: 18px;
  height: 18px;
  margin-top: 2px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  border: 1px solid var(--border-strong);
  background: transparent;
  color: transparent;
  font-size: var(--fs-xs);
  transition: 0.12s;
}

.row:hover .row-check,
.row-check.on {
  border-color: var(--primary);
}

.row-check.on {
  background: var(--primary);
  color: #fff;
}

.row-body {
  flex: 1;
  min-width: 0;
}

.row-title {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--fs-sm);
  font-weight: 600;
}

.name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pin,
.star {
  font-size: var(--fs-xs);
  color: #fbbf24;
}

.rating {
  margin-left: auto;
  font-size: var(--fs-xs);
  color: #fbbf24;
}

.row-preview {
  font-size: var(--fs-xs);
  color: var(--muted);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-tags {
  font-size: var(--fs-xs);
  color: var(--primary);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm);
  border-top: 1px solid var(--border);
}

.page-num {
  font-size: var(--fs-sm);
  color: var(--muted);
}

.detail-pane {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
}

.detail {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  padding: var(--gap-lg);
  height: 100%;
}

.generate-bar {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--panel);
}

.wf-select {
  flex: 1;
  min-width: 0;
  max-width: 340px;
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

.detail-head {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
}

.name-input {
  flex: 1;
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

.label {
  font-size: var(--fs-sm);
  color: var(--muted);
  margin-right: var(--gap-sm);
}

.star-btn {
  border: none;
  background: transparent;
  color: var(--border-strong);
  font-size: var(--fs-lg);
  line-height: 1;
  padding: 0 1px;
}

.star-btn.on {
  color: #fbbf24;
}

.meta {
  margin-left: auto;
  font-size: var(--fs-xs);
  color: var(--muted);
}

.field {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  font-size: var(--fs-sm);
  color: var(--muted);
}

.field.grow {
  flex: 1;
  min-height: 0;
}

.field-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-sm);
}

.cat-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.cat-chip {
  font-size: var(--fs-xs);
  padding: 2px 9px;
  border-radius: 999px;
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
  color: #fff;
}
.field textarea {
  flex: 1;
  min-height: 120px;
  resize: vertical;
  font: inherit;
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--gap-sm);
  outline: none;
}

.field textarea.small {
  min-height: 64px;
}

.field textarea:focus {
  border-color: var(--primary);
}

.field input {
  background: var(--panel-2);
}

.detail-foot {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding-top: var(--gap-sm);
  border-top: 1px solid var(--border);
  font-size: var(--fs-sm);
}

.dirty {
  color: var(--warn);
}

.saved {
  color: var(--muted);
}

.spacer {
  flex: 1;
}

.empty {
  font-size: var(--fs-sm);
  color: var(--muted);
}

.empty.big {
  padding: 60px;
  text-align: center;
}
</style>
