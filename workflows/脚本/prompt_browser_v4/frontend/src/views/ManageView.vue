<script setup lang="ts">
import { computed, ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'

import { apiDelete, apiGet, apiPost, apiPut } from '../api/client'
import { useToast } from '../composables/useToast'
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

type Panel = 'category' | 'tag'
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
    </div>

    <div class="creator">
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
      <label v-if="panel === 'tag'" class="only-unused">
        <input v-model="onlyUnused" type="checkbox" />
        <span>只看未使用</span>
      </label>
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
        <div v-if="!flatCats.length" class="empty">还没有分类</div>
      </template>

      <template v-else>
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
        <div v-if="!visibleTags.length" class="empty">没有符合条件的标签</div>
      </template>
    </div>

    <p class="hint">点名称可直接改名；计数是「挂了这个标签/分类的提示词数」。</p>
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