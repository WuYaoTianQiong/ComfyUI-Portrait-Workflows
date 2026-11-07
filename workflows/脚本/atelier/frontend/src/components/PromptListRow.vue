<script setup lang="ts">
import type { PromptListItem } from '../api/types'

defineProps<{
  item: PromptListItem
  active: boolean
  picked: boolean
  tags: string[]
}>()

defineEmits<{
  select: [id: number]
  toggle: [id: number]
}>()
</script>

<template>
  <div
    class="row"
    :data-id="item.id"
    :class="{ active, picked }"
    @click="$emit('select', item.id)"
  >
    <button
      class="row-check"
      :class="{ on: picked }"
      :title="picked ? '取消选择' : '选择'"
      @click.stop="$emit('toggle', item.id)"
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
      <div class="row-meta">
        <span v-if="item.steps" class="badge">{{ item.steps }}步</span>
        <span v-if="item.sampler" class="sampler">{{ item.sampler }}</span>
        <span v-for="tag in tags" :key="tag" class="tag">{{ tag }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.row {
  display: flex;
  align-items: flex-start;
  gap: var(--gap-sm);
  border-bottom: 1px solid var(--border);
  padding: var(--gap-sm) var(--gap);
  transition:
    background-color var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease);
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
  background: color-mix(in srgb, var(--primary) 8%, transparent);
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
  transition:
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.row:hover .row-check,
.row-check.on {
  border-color: var(--primary);
}

.row-check.on {
  background: var(--primary);
  color: rgb(255 255 255);
}

.row-body {
  flex: 1;
  min-width: 0;
}

.row-title {
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
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
  color: var(--warn);
}

.rating {
  margin-left: auto;
  font-size: var(--fs-xs);
  color: var(--warn);
}

.row-preview {
  font-size: var(--fs-sm);
  color: var(--muted);
  line-height: var(--lh-lg);
  margin-top: 2px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.row-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-xs);
  margin-top: 5px;
  font-size: var(--fs-xs);
}

.row-meta .badge {
  margin: 0;
  min-width: 0;
  height: auto;
  padding: 1px 6px;
  border-radius: 4px;
  background: color-mix(in srgb, var(--success) 14%, transparent);
  color: var(--success);
}

.sampler {
  color: var(--muted);
}

.row-meta .tag {
  padding: 1px 6px;
  border-radius: 4px;
  background: color-mix(in srgb, var(--primary) 12%, transparent);
  color: var(--primary);
}
</style>
