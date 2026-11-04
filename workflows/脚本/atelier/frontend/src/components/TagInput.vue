<script setup lang="ts">
import { computed, ref } from 'vue'

import type { TagRow } from '../api/types'

/**
 * 标签选择器：点选已有标签 + 自由输入新标签。
 *
 * 只改内存里的标签数组，由父组件写回 `prompts.tags` 文本，**保存时**由后端
 * `sync_prompt_tags()` 同步到 `entity_tags`。不直接调关联端点，是为了和
 * 「文本是唯一事实来源」的既有设计保持一致 —— 两套写入路径必然打架。
 */
const props = defineProps<{
  modelValue: string[]
  suggestions: TagRow[]
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string[]): void
}>()

const keyword = ref('')
const open = ref(false)

const selected = computed(() => new Set(props.modelValue))

/**
 * 候选：排除已选，按输入关键字过滤（不区分大小写），再按使用数降序。
 *
 * 排序很关键：库里 178 个标签里有 100mm、1128x2008 这类尺寸/参数类标签，
 * 不排序的话空输入时弹出来的全是它们，真正会用的「女性/古风/包」反而看不到。
 */
const candidates = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return props.suggestions
    .filter((t) => !selected.value.has(t.name))
    .filter((t) => !kw || t.name.toLowerCase().includes(kw))
    .slice()
    .sort((a, b) => (b.prompt_count ?? 0) - (a.prompt_count ?? 0))
    .slice(0, 12)
})

const exactExists = computed(() =>
  props.suggestions.some((t) => t.name === keyword.value.trim()),
)

function add(name: string) {
  const value = name.trim()
  if (!value || selected.value.has(value)) {
    keyword.value = ''
    return
  }
  emit('update:modelValue', [...props.modelValue, value])
  keyword.value = ''
}

function remove(name: string) {
  emit('update:modelValue', props.modelValue.filter((t) => t !== name))
}
</script>

<template>
  <div class="tag-input">
    <div class="picked">
      <span v-for="name in modelValue" :key="name" class="picked-tag">
        {{ name }}
        <button type="button" title="移除" @click="remove(name)">✕</button>
      </span>
      <span v-if="!modelValue.length" class="muted">还没有标签</span>
    </div>

    <div class="entry">
      <input
        v-model="keyword"
        type="text"
        placeholder="输入标签名，回车添加；也可以从下面直接点选"
        @focus="open = true"
        @blur="open = false"
        @keyup.enter="add(keyword)"
      />
    </div>

    <div v-if="open && candidates.length" class="candidates">
      <button
        v-for="c in candidates"
        :key="c.id"
        type="button"
        class="candidate"
        @mousedown.prevent="add(c.name)"
      >
        <span class="dot" :style="{ background: c.color }" />
        <span class="name">{{ c.name }}</span>
        <i>{{ c.prompt_count }}</i>
      </button>
    </div>

    <div v-if="open && keyword.trim() && !exactExists" class="new-hint">
      回车创建新标签「{{ keyword.trim() }}」
    </div>
  </div>
</template>

<style scoped>
.tag-input {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
}

.picked {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-xs);
  min-height: 20px;
}

.picked-tag {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-xs);
  font-size: var(--fs-xs);
  padding: 2px 6px 2px 9px;
  border-radius: var(--radius-pill);
  background: var(--primary-soft);
  border: 1px solid var(--primary);
  color: var(--primary);
}

.picked-tag button {
  border: none;
  background: transparent;
  color: inherit;
  font-size: 10px;
  padding: 0;
  line-height: 1;
  opacity: 0.7;
}

.picked-tag button:hover {
  opacity: 1;
}

.entry input {
  width: 100%;
}

.candidates {
  display: flex;
  flex-direction: column;
  max-height: 190px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
}

.candidate {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  border: none;
  background: transparent;
  padding: 4px var(--gap-sm);
  font-size: var(--fs-sm);
  text-align: left;
}

.candidate:hover {
  background: var(--panel-3);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
}

.name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.candidate i {
  font-style: normal;
  font-size: var(--fs-xs);
  color: var(--muted);
}

.new-hint {
  font-size: var(--fs-xs);
  color: var(--muted);
}

.muted {
  color: var(--muted);
  font-size: var(--fs-xs);
}
</style>
