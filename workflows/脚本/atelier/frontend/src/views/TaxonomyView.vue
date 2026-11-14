<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useMutation, useQuery } from '@tanstack/vue-query'

import { clearThumbnailCache } from '../api/system'
import Icon from '../components/Icon.vue'
import {
  autoClassifyAll as autoClassifyAllRequest,
  createCategory,
  createTag,
  deleteCategory,
  deleteTag,
  listCategories,
  listTags,
  updateCategory,
  updateTag,
} from '../api/taxonomy'
import EmptyState from '../components/EmptyState.vue'
import Skeleton from '../components/Skeleton.vue'
import { useToast } from '../composables/useToast'
import { useWorkflows } from '../composables/useWorkflows'
import { readSession, writeSession } from '../composables/useSessionState'
import { flattenCategories } from '../utils/categories'
import { confirmDialog, resetConfirmSkip } from '../utils/naive'
import {
  CONFIRM_PROMPTS,
  listSkippedPrompts,
  resetAllConfirmSkips,
  type ConfirmPromptMeta,
} from '../utils/confirmKeys'

/**
 * 分类与标签。
 *
 * 这两件事结构一样（列表 + 新建 + 改名 + 删除 + 配色），合并到一个页面里，
 * 用页签切换 —— 旧前端把它们散在三个弹窗里，找入口要翻半天。
 */
const toast = useToast()

const COLORS = [
  '#6366f1', '#5b8fb9', '#22c55e', '#f59e0b',
  '#ef4444', '#a855f7', '#ec4899', '#14b8a6',
]

type Panel = 'category' | 'tag' | 'workflow'

/** 会话状态：回到分类与标签页时停在上次的页签与筛选。 */
interface TaxonomySession {
  panel: Panel
  onlyUnused: boolean
}

/** 键名仍是旧页名：改字符串会让用户已存的页签选择丢失，存储键不进命名规范。 */
const SESSION_KEY = 'pb.session.manage'
const savedSession = readSession<TaxonomySession>(SESSION_KEY, {
  panel: 'category',
  onlyUnused: false,
})

const panel = ref<Panel>(savedSession.panel)

/** 用户勾过「下次不再提示」的确认框；这里可以逐条恢复，不用清 localStorage。 */
const skippedPrompts = ref<ConfirmPromptMeta[]>(listSkippedPrompts())

function restorePrompt(meta: ConfirmPromptMeta) {
  resetConfirmSkip(meta.key)
  skippedPrompts.value = listSkippedPrompts()
  toast.success(`已恢复「${meta.label}」的确认提示`)
}

function restoreAllPrompts() {
  resetAllConfirmSkips()
  skippedPrompts.value = []
  toast.success('已恢复全部确认提示')
}

const { data: catData, isFetching: catsFetching, refetch: refetchCats } = useQuery({
  queryKey: ['categories', 'taxonomy'],
  queryFn: () => listCategories({ tree: true, count_scope: 'prompt' }),
})

const flatCats = computed(() => flattenCategories(catData.value?.categories))

const visibleTags = computed(() => {
  const list = tagData.value?.tags ?? []
  return onlyUnused.value ? list.filter((t) => !t.prompt_count) : list
})

const { data: tagData, isFetching: tagsFetching, refetch: refetchTags } = useQuery({
  queryKey: ['tags', 'taxonomy'],
  queryFn: () => listTags({ count_scope: 'prompt' }),
})

const newName = ref('')
/** 只看没被任何提示词用到的标签 —— 库里有 80 多个孤儿标签，清它们时用得上。 */
const onlyUnused = ref(savedSession.onlyUnused)
const newColor = ref(COLORS[0])

watch(
  () => [panel.value, onlyUnused.value].join('|'),
  () => {
    writeSession(SESSION_KEY, {
      panel: panel.value,
      onlyUnused: onlyUnused.value,
    })
  },
)

async function createItem() {
  const name = newName.value.trim()
  if (!name) return
  try {
    if (panel.value === 'category') {
      await createCategory(name, newColor.value)
      refetchCats()
    } else {
      await createTag(name, newColor.value)
      refetchTags()
    }
    newName.value = ''
    toast.success(`已创建「${name}」`)
  } catch (e) {
    toast.error(`创建失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

const editingId = ref<number | null>(null)
const editingName = ref('')

function startEdit(id: number, name: string) {
  editingId.value = id
  editingName.value = name
}

function cancelEdit() {
  editingId.value = null
  editingName.value = ''
}

async function saveEdit() {
  const name = editingName.value.trim()
  if (!name || editingId.value === null) {
    cancelEdit()
    return
  }
  try {
    if (panel.value === 'category') {
      await updateCategory(editingId.value, { name })
      refetchCats()
    } else {
      await updateTag(editingId.value, { name })
      refetchTags()
    }
    cancelEdit()
  } catch (e) {
    toast.error(`重命名失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

/**
 * 一键自动分类：把每条提示词按【类型】数量重新归入 组合/单项/零散。
 *
 * 后端是全量重算（331 条），单条端点在提示词详情页用。
 * 成功后分类计数会变，所以要同时失效分类与提示词两个缓存。
 */
const autoClassifyMutation = useMutation({
  mutationFn: autoClassifyAllRequest,
  onSuccess: (result) => {
    refetchCats()
    toast.success(`已重新分类，${result.reclassified} 条提示词的分类发生变化`)
  },
})

async function autoClassifyAll() {
  const ok = await confirmDialog({
    title: '自动分类',
    content: '将对所有提示词重新计算类型分类（组合 / 单项 / 零散），继续？',
    positiveText: '开始',
    negativeText: '取消',
    rememberKey: CONFIRM_PROMPTS.autoClassify.key,
  })
  if (!ok) return
  autoClassifyMutation.mutate()
}

/** 清理缩略图缓存（缩略图按 路径+mtime+尺寸 做键，下次访问自动重建）。 */
const clearThumbs = useMutation({
  mutationFn: clearThumbnailCache,
  onSuccess: (result) => {
    toast.success(`已清理 ${result.deleted} 个缩略图缓存文件`)
  },
  onError: (e) => {
    toast.error(`清理失败：${e instanceof Error ? e.message : String(e)}`)
  },
})

// ---------------- 工作流 ----------------

const {
  allWorkflows,
  hiddenPaths,
  addCustomWorkflow,
  removeCustomWorkflow,
  setHidden,
  moveWorkflow,
} = useWorkflows()

/** 隐藏的默认也列出来（带"恢复"），不然藏了就找不回来了。 */
const workflowRows = computed(() =>
  allWorkflows.value.map((w) => ({ ...w, hidden: hiddenPaths.value.includes(w.path) })),
)

async function uploadWorkflow(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  try {
    const path = await addCustomWorkflow(file)
    toast.success(`已添加自定义工作流「${path.replace('custom://', '')}」`)
  } catch (e) {
    toast.error(e instanceof Error ? e.message : String(e))
  }
  input.value = ''
}

async function removeWorkflow(path: string, name: string) {
  const ok = await confirmDialog({
    title: '删除工作流',
    content: `删除自定义工作流「${name}」吗？`,
    positiveText: '删除',
    negativeText: '取消',
  })
  if (!ok) return
  removeCustomWorkflow(path)
  toast.success('已删除')
}
async function removeItem(kind: Panel, id: number, name: string) {
  const extra = kind === 'category' ? '，并会解除它与所有提示词的关联' : ''
  const ok = await confirmDialog({
    title: '删除条目',
    content: `确定删除「${name}」吗${extra}？`,
    positiveText: '删除',
    negativeText: '取消',
  })
  if (!ok) return
  try {
    if (kind === 'category') {
      await deleteCategory(id)
      refetchCats()
    } else {
      await deleteTag(id)
      refetchTags()
    }
    toast.success(`已删除「${name}」`)
  } catch (e) {
    toast.error(`删除失败：${e instanceof Error ? e.message : String(e)}`)
  }
}
</script>
<template>
  <div class="taxonomy">
    <div class="tabs">
      <button class="btn btn-sm" :class="{ active: panel === 'category' }" @click="panel = 'category'">
        分类
      </button>
      <button class="btn btn-sm" :class="{ active: panel === 'tag' }" @click="panel = 'tag'">
        标签
      </button>
      <button class="btn btn-sm" :class="{ active: panel === 'workflow' }" @click="panel = 'workflow'">
        工作流
      </button>
      <span class="spacer" />
      <button
        class="btn btn-sm"
        :disabled="clearThumbs.isPending.value"
        title="删除所有缩略图缓存文件，下次访问时自动重建"
        @click="clearThumbs.mutate()"
      >
        {{ clearThumbs.isPending.value ? '清理中…' : '清理缩略图缓存' }}
      </button>
    </div>

    <div v-if="skippedPrompts.length" class="skipped-bar">
      <span class="skipped-label">已关闭的确认提示</span>
      <button
        v-for="p in skippedPrompts"
        :key="p.key"
        class="skipped-chip"
        :title="`恢复「${p.label}」的确认`"
        @click="restorePrompt(p)"
      >
        {{ p.label }} ×
      </button>
      <span class="spacer" />
      <button class="btn btn-sm" @click="restoreAllPrompts">全部恢复</button>
    </div>

    <div v-if="panel === 'category' || panel === 'tag'" class="creator">
      <input
        v-model="newName"
        class="name-input"
        :placeholder="panel === 'category' ? '新分类名称' : '新标签名称'"
        @keyup.enter="createItem"
      />
      <div class="swatches">
        <button
          v-for="color in COLORS"
          :key="color"
          class="swatch"
          :class="{ on: newColor === color }"
          :style="{ background: color }"
          :title="color"
          @click="newColor = color"
        />
      </div>
      <button class="btn btn-sm primary" :disabled="!newName.trim()" @click="createItem">添加</button>
      <span class="spacer" />
      <button
        v-if="panel === 'category'"
        class="btn btn-sm"
        :disabled="autoClassifyMutation.isPending.value"
        title="按提示词正文里的【类型】数量重新归入 组合 / 单项 / 零散"
        @click="autoClassifyAll"
      >
        {{ autoClassifyMutation.isPending.value ? '重新分类中…' : '一键自动分类' }}
      </button>
      <label v-if="panel === 'tag'" class="only-unused">
        <input v-model="onlyUnused" type="checkbox" />
        <span>只看未使用</span>
      </label>
    </div>

    <div class="list">
      <template v-if="panel === 'category'">
        <Skeleton v-if="catsFetching && !flatCats.length" class="list-skeleton" variant="block" :count="5" />
        <div v-for="cat in flatCats" :key="cat.id" class="row" :style="{ paddingLeft: `${8 + cat.depth * 18}px` }">
          <span class="dot" :style="{ background: cat.color }" />
          <input
            v-if="editingId === cat.id"
            v-model="editingName"
            class="inline-edit"
            @keyup.enter="saveEdit"
            @keyup.esc="cancelEdit"
            @blur="saveEdit"
          />
          <span v-else class="row-name" @click="startEdit(cat.id, cat.name)">{{ cat.name }}</span>
          <span class="count">{{ cat.prompt_count }}</span>
          <button class="icon danger" title="删除" @click="removeItem('category', cat.id, cat.name)">✕</button>
        </div>
        <EmptyState v-if="!flatCats.length && !catsFetching" text="还没有分类" hint="在上方输入名称即可创建第一个分类" />
      </template>

      <template v-else-if="panel === 'tag'">
        <Skeleton v-if="tagsFetching && !visibleTags.length" class="list-skeleton" variant="block" :count="5" />
        <div v-for="tag in visibleTags" :key="tag.id" class="row">
          <span class="dot" :style="{ background: tag.color }" />
          <input
            v-if="editingId === tag.id"
            v-model="editingName"
            class="inline-edit"
            @keyup.enter="saveEdit"
            @keyup.esc="cancelEdit"
            @blur="saveEdit"
          />
          <span v-else class="row-name" @click="startEdit(tag.id, tag.name)">{{ tag.name }}</span>
          <span class="count">{{ tag.prompt_count }}</span>
          <button class="icon danger" title="删除" @click="removeItem('tag', tag.id, tag.name)">✕</button>
        </div>
        <EmptyState
          v-if="!visibleTags.length && !tagsFetching"
          text="没有符合条件的标签"
          hint="当前只显示未被使用的标签"
          action-text="显示全部标签"
          @action="onlyUnused = false"
        />
      </template>

      <template v-else>
        <div class="wf-toolbar">
          <label class="btn btn-sm wf-upload">
            <Icon name="folder-up" /> 上传自定义工作流
            <input type="file" accept=".json,application/json" @change="uploadWorkflow" />
          </label>
          <span class="count">共 {{ workflowRows.length }} 个</span>
        </div>
        <div v-for="w in workflowRows" :key="w.path" class="wf-row" :class="{ hidden: w.hidden }">
          <span class="wf-badge" :class="{ custom: w.custom }">{{ w.custom ? '自定义' : '磁盘' }}</span>
          <span class="row-name">{{ w.name }}</span>
          <span class="spacer" />
          <button class="icon" title="上移" @click="moveWorkflow(w.path, -1)">↑</button>
          <button class="icon" title="下移" @click="moveWorkflow(w.path, 1)">↓</button>
          <button
            v-if="w.custom"
            class="icon danger"
            title="删除"
            @click="removeWorkflow(w.path, w.name)"
          >
            ✕
          </button>
          <button
            class="icon"
            :title="w.hidden ? '恢复显示' : '隐藏（从下拉里移除）'"
            @click="setHidden(w.path, !w.hidden)"
          >
            <Icon :name="w.hidden ? 'eye' : 'eye-off'" />
          </button>
        </div>
        <EmptyState v-if="!workflowRows.length" text="没有找到工作流" />
      </template>
    </div>

    <p class="hint">点名称可直接改名；计数是「挂了这个标签/分类的提示词数」。</p>
  </div>
</template>
<style scoped>
.taxonomy {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  padding: var(--gap-lg);
  gap: var(--gap);
}

.tabs {
  display: flex;
  gap: var(--gap-xs);
}

.tabs .btn {
  border-radius: var(--radius-pill);
  background: var(--panel-2);
  transition:
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.tabs .btn.active {
  border-color: var(--primary);
  background: var(--primary);
  color: var(--on-primary);
}

.skipped-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-xs);
  padding: var(--gap-xs) var(--gap-sm);
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
}

.skipped-label {
  flex: none;
  font-size: var(--fs-xs);
  color: var(--muted);
}

.skipped-chip {
  border: 1px solid var(--primary);
  background: var(--primary-soft);
  color: var(--accent-link);
  border-radius: var(--radius-pill);
  padding: 1px var(--gap-sm);
  font-size: var(--fs-xs);
}

.creator {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
}

.name-input {
  width: 240px;
}

.only-unused {
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
  font-size: var(--fs-xs);
  color: var(--muted);
  cursor: pointer;
}

.spacer {
  flex: 1;
}

.swatches {
  display: flex;
  gap: var(--gap-xs);
}

.swatch {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 2px solid transparent;
  cursor: pointer;
  padding: 0;
}

.swatch.on {
  border-color: var(--text);
}

.list {
  flex: 1;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--panel);
}

.list-skeleton {
  padding: var(--gap);
}

.row {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: 6px var(--gap);
  border-bottom: 1px solid var(--border);
  font-size: var(--fs-sm);
}

.row:last-child {
  border-bottom: none;
}

.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex: none;
}

.row-name {
  flex: 1;
  cursor: text;
  border-radius: var(--radius-sm);
  padding: 1px 4px;
}

.row-name:hover {
  background: var(--panel-3);
}

.inline-edit {
  flex: 1;
  padding: 1px 4px;
}



.wf-toolbar {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm) var(--gap);
  border-bottom: 1px solid var(--border);
}

.wf-upload {
  position: relative;
  overflow: hidden;
  cursor: pointer;
}

.wf-upload input[type='file'] {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
}

.wf-row {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: 6px var(--gap);
  border-bottom: 1px solid var(--border);
  font-size: var(--fs-sm);
}

.wf-row.hidden {
  opacity: 0.45;
}

.wf-badge {
  flex: none;
  font-size: var(--fs-xs);
  padding: 1px 5px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  color: var(--muted);
}

.wf-badge.custom {
  border-color: var(--primary);
  color: var(--accent-link);
}

.wf-row .row-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: default;
}

.wf-row .icon {
  border: none;
  background: transparent;
  color: var(--muted);
  padding: 0 4px;
  font-size: var(--fs-sm);
}

.wf-row .icon:hover {
  color: var(--accent-link);
}

.wf-row .icon.danger:hover {
  color: var(--danger);
}

.spacer {
  flex: 1;
}

.inline-edit.grow {
  flex: 1;
  min-width: 220px;
  min-height: 30px;
  height: 30px;
  resize: vertical;
  font: inherit;
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 2px var(--gap-sm);
  outline: none;
}
.count {
  color: var(--muted);
  font-size: var(--fs-xs);
}

.icon {
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: var(--fs-sm);
  padding: 0 4px;
}

.icon.danger:hover {
  color: var(--danger);
}

.btn.primary {
  border-color: var(--primary);
  background: var(--primary);
  color: var(--on-primary);
}

.btn.primary:disabled {
  opacity: 0.4;
  cursor: default;
}

.empty {
  padding: var(--gap-lg);
  text-align: center;
  color: var(--muted);
  font-size: var(--fs-sm);
}

.hint {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--muted);
}
</style>
