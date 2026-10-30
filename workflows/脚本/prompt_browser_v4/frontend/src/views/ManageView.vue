<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMutation, useQuery } from '@tanstack/vue-query'

import { apiDelete, apiGet, apiPost, apiPut } from '../api/client'
import EmptyState from '../components/EmptyState.vue'
import { useToast } from '../composables/useToast'
import { FRAGMENT_TYPES } from '../constants'
import type { CategoryNode, TagRow } from '../api/types'

/**
 * 分类 / 标签管理。
 *
 * 这两件事结构一样（列表 + 新建 + 改名 + 删除 + 配色），合并到一个页面里，
 * 用页签切换 —— 旧前端把它们散在三个弹窗里，找入口要翻半天。
 */
const toast = useToast()

const COLORS = [
  '#6366f1', '#5b8fb9', '#22c55e', '#f59e0b',
  '#ef4444', '#a855f7', '#ec4899', '#14b8a6',
]

type Panel = 'category' | 'tag' | 'fragment'
const panel = ref<Panel>('category')

const { data: catData, refetch: refetchCats } = useQuery<{ categories: CategoryNode[] }>({
  queryKey: ['categories', 'manage'],
  queryFn: () => apiGet('/api/categories', { tree: true, count_scope: 'prompt' }),
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

const visibleTags = computed(() => {
  const list = tagData.value?.tags ?? []
  return onlyUnused.value ? list.filter((t) => !t.prompt_count) : list
})

const { data: tagData, refetch: refetchTags } = useQuery<{ tags: TagRow[] }>({
  queryKey: ['tags', 'manage'],
  queryFn: () => apiGet('/api/tags', { count_scope: 'prompt' }),
})

const newName = ref('')
/** 只看没被任何提示词用到的标签 —— 库里有 80 多个孤儿标签，清它们时用得上。 */
const onlyUnused = ref(false)
const newColor = ref(COLORS[0])

async function createItem() {
  const name = newName.value.trim()
  if (!name) return
  try {
    if (panel.value === 'category') {
      await apiPost('/api/categories', { name, color: newColor.value })
      refetchCats()
    } else {
      await apiPost('/api/tags', { name, color: newColor.value })
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
      await apiPut(`/api/categories/${editingId.value}`, { name })
      refetchCats()
    } else {
      await apiPut(`/api/tags/${editingId.value}`, { name })
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
  mutationFn: () =>
    apiPost<{ success: boolean; reclassified: number }>('/api/categories/auto-classify'),
  onSuccess: (result) => {
    refetchCats()
    toast.success(`已重新分类，${result.reclassified} 条提示词的分类发生变化`)
  },
})

function autoClassifyAll() {
  if (!confirm('将对所有提示词重新计算类型分类（组合 / 单项 / 零散），继续？')) return
  autoClassifyMutation.mutate()
}

// ---------------- 碎片库 ----------------

interface FragmentRow {
  id: number
  name: string
  fragment_type: string
  content: string
  tags: string
  usage_count: number
}

const fragSearch = ref('')
const fragTypeFilter = ref('')

const { data: fragData, refetch: refetchFrags } = useQuery<{
  items: FragmentRow[]
  total: number
}>({
  queryKey: computed(() => ['fragments', fragSearch.value, fragTypeFilter.value]),
  queryFn: () =>
    apiGet('/api/fragments', {
      search: fragSearch.value.trim(),
      fragment_type: fragTypeFilter.value,
      page_size: 200,
    }),
})

const fragments = computed<FragmentRow[]>(() => fragData.value?.items ?? [])

const newFragType = ref<string>('人物面部')
const newFragName = ref('')
const newFragContent = ref('')


/** 清理缩略图缓存（缩略图按 路径+mtime+尺寸 做键，下次访问自动重建）。 */
const clearThumbs = useMutation({
  mutationFn: () => apiPost<{ success: boolean; deleted: number }>('/api/thumbnail/clear'),
  onSuccess: (result) => {
    toast.success(`已清理 ${result.deleted} 个缩略图缓存文件`)
  },
  onError: (e) => {
    toast.error(`清理失败：${e instanceof Error ? e.message : String(e)}`)
  },
})
async function createFragment() {
  if (!newFragContent.value.trim()) {
    toast.error('碎片内容不能为空')
    return
  }
  try {
    await apiPost('/api/fragments', {
      name: newFragName.value.trim(),
      fragment_type: newFragType.value,
      content: newFragContent.value.trim(),
      tags: '',
    })
    newFragName.value = ''
    newFragContent.value = ''
    refetchFrags()
    toast.success('已添加碎片')
  } catch (e) {
    toast.error(`添加失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

const editingFragId = ref<number | null>(null)
const editingFrag = ref({ name: '', content: '', fragment_type: '人物面部' })

function startEditFrag(f: FragmentRow) {
  editingFragId.value = f.id
  editingFrag.value = { name: f.name, content: f.content, fragment_type: f.fragment_type }
}

async function saveFrag() {
  if (editingFragId.value === null) return
  try {
    await apiPut(`/api/fragments/${editingFragId.value}`, {
      name: editingFrag.value.name,
      content: editingFrag.value.content,
      fragment_type: editingFrag.value.fragment_type,
    })
    editingFragId.value = null
    refetchFrags()
    toast.success('已保存')
  } catch (e) {
    toast.error(`保存失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

async function removeFragment(id: number, label: string) {
  if (!confirm(`确定删除碎片「${label}」吗？`)) return
  try {
    await apiDelete(`/api/fragments/${id}`)
    refetchFrags()
    toast.success('已删除')
  } catch (e) {
    toast.error(`删除失败：${e instanceof Error ? e.message : String(e)}`)
  }
}
async function removeItem(kind: Panel, id: number, name: string) {
  const extra = kind === 'category' ? '，并会解除它与所有提示词的关联' : ''
  if (!confirm(`确定删除「${name}」吗${extra}？`)) return
  try {
    if (kind === 'category') {
      await apiDelete(`/api/categories/${id}`)
      refetchCats()
    } else {
      await apiDelete(`/api/tags/${id}`)
      refetchTags()
    }
    toast.success(`已删除「${name}」`)
  } catch (e) {
    toast.error(`删除失败：${e instanceof Error ? e.message : String(e)}`)
  }
}
</script>
<template>
  <div class="manage">
    <div class="tabs">
      <button class="btn btn-sm" :class="{ active: panel === 'category' }" @click="panel = 'category'">
        分类
      </button>
      <button class="btn btn-sm" :class="{ active: panel === 'tag' }" @click="panel = 'tag'">
        标签
      </button>
      <button class="btn btn-sm" :class="{ active: panel === 'fragment' }" @click="panel = 'fragment'">
        碎片库
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

    <div v-if="panel !== 'fragment'" class="creator">
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


    <div v-else class="creator frag-tools">
      <input v-model="fragSearch" class="frag-search" placeholder="搜索碎片内容 / 名称…" />
      <select v-model="fragTypeFilter" class="frag-type-select">
        <option value="">全部类型</option>
        <option v-for="t in FRAGMENT_TYPES" :key="t" :value="t">{{ t }}</option>
      </select>
      <span class="count">{{ fragments.length }} 个</span>
    </div>

    <div v-if="panel === 'fragment'" class="creator frag-tools">
      <select v-model="newFragType" class="frag-type-select">
        <option v-for="t in FRAGMENT_TYPES" :key="t" :value="t">{{ t }}</option>
      </select>
      <input v-model="newFragName" class="frag-name-input" placeholder="名称（可选）" />
      <textarea v-model="newFragContent" class="frag-content-input" placeholder="碎片内容…" />
      <button class="btn btn-sm primary" :disabled="!newFragContent.trim()" @click="createFragment">
        添加
      </button>
    </div>
    <div class="list">
      <template v-if="panel === 'category'">
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
        <EmptyState v-if="!flatCats.length" text="还没有分类" />
      </template>

      <template v-else-if="panel === 'tag'">
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
        <EmptyState v-if="!visibleTags.length" text="没有符合条件的标签" />
      </template>

      <template v-else>
        <div v-for="f in fragments" :key="f.id" class="frag-row">
          <template v-if="editingFragId === f.id">
            <select v-model="editingFrag.fragment_type" class="frag-type-select mini">
              <option v-for="t in FRAGMENT_TYPES" :key="t" :value="t">{{ t }}</option>
            </select>
            <input v-model="editingFrag.name" class="inline-edit" placeholder="名称" />
            <textarea v-model="editingFrag.content" class="inline-edit grow" />
            <button class="btn btn-sm" @click="saveFrag">保存</button>
            <button class="btn btn-sm" @click="editingFragId = null">取消</button>
          </template>
          <template v-else>
            <span class="frag-type">{{ f.fragment_type }}</span>
            <span class="row-name" @click="startEditFrag(f)">{{ f.name || '(未命名)' }}</span>
            <span class="frag-content" :title="f.content" @click="startEditFrag(f)">{{ f.content }}</span>
            <span class="count" :title="'使用 ' + f.usage_count + ' 次'">{{ f.usage_count }}</span>
            <button class="icon danger" title="删除" @click="removeFragment(f.id, f.name || f.content.slice(0, 10))">✕</button>
          </template>
        </div>
        <EmptyState v-if="!fragments.length" text="还没有碎片" />
      </template>    </div>

    <p class="hint">
      {{
        panel === 'fragment'
          ? '点名称或内容即可编辑；计数是碎片被使用的次数。'
          : '点名称可直接改名；计数是「挂了这个标签/分类的提示词数」。'
      }}
    </p>
  </div>
</template>
<style scoped>
.manage {
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
  gap: 6px;
  font-size: var(--fs-xs);
  color: var(--muted);
  cursor: pointer;
}

.spacer {
  flex: 1;
}

.swatches {
  display: flex;
  gap: 4px;
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


.frag-tools {
  flex-wrap: wrap;
}

.frag-search {
  flex: 1;
  min-width: 160px;
}

.frag-type-select {
  width: 118px;
}

.frag-type-select.mini {
  width: 100px;
}

.frag-name-input {
  width: 160px;
}

.frag-content-input {
  flex: 1;
  min-width: 220px;
  min-height: 34px;
  height: 34px;
  resize: vertical;
  font: inherit;
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 4px var(--gap-sm);
  outline: none;
}

.frag-row {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: 6px var(--gap);
  border-bottom: 1px solid var(--border);
  font-size: var(--fs-sm);
}

.frag-type {
  flex: none;
  font-size: var(--fs-xs);
  color: var(--muted);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0 6px;
}

.frag-content {
  flex: 1;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: text;
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
  color: #fff;
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
