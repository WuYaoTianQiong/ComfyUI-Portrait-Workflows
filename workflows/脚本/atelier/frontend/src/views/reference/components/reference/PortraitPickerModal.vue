<script setup lang="ts">
/**
 * 从人像库选择「人物B身份参考图」（v2-A 第 4 槽）。
 *
 * 与 `HairPickerModal` 的差异：
 * - 数据源换成 portrait 库，提交 `extra_library=portrait`；
 * - 没有「背面可用」这类可用性开关（人像库条目都能作为身份图）；
 * - 仅做搜索过滤，选中后由页面写入第 4 槽草稿。
 */

import { computed, ref, watch } from 'vue'

import type { PortraitItem } from '../../../../api/reference'
import { useReferencePortraits } from '../../../../composables/useReferenceLibrary'
import Modal from '../../../../components/Modal.vue'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'select', item: PortraitItem): void
}>()

const { items, loading, error, load } = useReferencePortraits()
const query = ref('')

watch(
  () => props.open,
  (open) => {
    if (open) void load()
  },
)

const filtered = computed(() => {
  const needle = query.value.trim().toLowerCase()
  if (!needle) return items.value
  return items.value.filter((item) => item.检索.toLowerCase().includes(needle))
})
</script>

<template>
  <Modal
    :open="open"
    title="从人像库选择（人物B身份参考）"
    width="min(980px, 94vw)"
    height="min(78vh, 760px)"
    @close="emit('close')"
  >
    <div class="portrait-picker">
      <div class="portrait-picker__bar">
        <input
          v-model="query"
          type="search"
          class="portrait-picker__search"
          placeholder="搜索人像标题、分区或 ID…"
          data-testid="portrait-picker-search"
        />
        <span class="portrait-picker__count">
          {{ loading ? '加载中…' : `${filtered.length} / ${items.length}` }}
        </span>
      </div>

      <p v-if="error" class="portrait-picker__error" role="alert">{{ error }}</p>

      <div v-else class="portrait-picker__grid" data-testid="portrait-picker-grid">
        <button
          v-for="item in filtered"
          :key="item.id"
          type="button"
          class="portrait-picker__item"
          :title="`${item.标题} · ${item.分区}`"
          :data-testid="`portrait-picker-item-${item.id}`"
          @click="emit('select', item)"
        >
          <span class="portrait-picker__thumb">
            <img v-if="item.缩略图" :src="item.缩略图" :alt="item.标题" loading="lazy" />
          </span>
          <span class="portrait-picker__name">{{ item.标题 }}</span>
          <span class="portrait-picker__meta">
            {{ item.分区 }}<template v-if="item.精选"> · 精选</template>
          </span>
        </button>
        <p v-if="!loading && !filtered.length" class="portrait-picker__empty">
          没有匹配的人像。
        </p>
      </div>
    </div>
  </Modal>
</template>

<style scoped>
.portrait-picker {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.portrait-picker__bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  padding-bottom: 12px;
}

.portrait-picker__search {
  flex: 1 1 260px;
  height: 38px;
  padding: 0 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel);
  color: var(--text-strong);
  font-size: 14px;
}

.portrait-picker__count {
  color: var(--text-muted);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.portrait-picker__error {
  color: var(--danger);
  font-size: 13px;
}

.portrait-picker__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px;
  min-height: 0;
  overflow-y: auto;
  padding: 2px;
}

.portrait-picker__item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 6px;
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  background: var(--surface-panel);
  color: var(--text-strong);
  text-align: left;
  cursor: pointer;
}

.portrait-picker__item:hover {
  border-color: var(--accent);
}

.portrait-picker__thumb {
  display: block;
  aspect-ratio: 3 / 4;
  overflow: hidden;
  border-radius: 8px;
  background: var(--surface-sunken);
}

.portrait-picker__thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.portrait-picker__name {
  overflow: hidden;
  font-size: 13px;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.portrait-picker__meta {
  overflow: hidden;
  color: var(--text-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.portrait-picker__empty {
  grid-column: 1 / -1;
  color: var(--text-muted);
  font-size: 13px;
}
</style>
