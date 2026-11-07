<script setup lang="ts">
/**
 * 从服装库选择「人物B服装」（V2-C 第 5 槽）。
 *
 * 与 `PortraitPickerModal` 同构：只做搜索过滤与缩略图选择，
 * 选中后由页面写入 `extraCostume` 草稿并提交 `extra_costume_library/id`。
 */

import { computed, ref, watch } from 'vue'

import type { CostumeItem } from '../../../../api/reference'
import { useReferenceCostumes } from '../../../../composables/useReferenceLibrary'
import Modal from '../../../../components/Modal.vue'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'select', item: CostumeItem): void
}>()

const { items, loading, error, load } = useReferenceCostumes()
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
    title="从服装库选择（人物B服装）"
    width="min(980px, 94vw)"
    height="min(78vh, 760px)"
    @close="emit('close')"
  >
    <div class="costume-picker">
      <div class="costume-picker__bar">
        <input
          v-model="query"
          type="search"
          class="costume-picker__search"
          placeholder="搜索服装名称、分类或 ID…"
          data-testid="costume-picker-search"
        />
        <span class="costume-picker__count">
          {{ loading ? '加载中…' : `${filtered.length} / ${items.length}` }}
        </span>
      </div>

      <p v-if="error" class="costume-picker__error" role="alert">{{ error }}</p>

      <div v-else class="costume-picker__grid" data-testid="costume-picker-grid">
        <button
          v-for="item in filtered"
          :key="`${item.library ?? 'costume'}:${item.id}`"
          type="button"
          class="costume-picker__item"
          :title="`${item.服装名称} · ${item.分类}`"
          :data-testid="`costume-picker-item-${item.id}`"
          @click="emit('select', item)"
        >
          <span class="costume-picker__thumb">
            <img v-if="item.缩略图" :src="item.缩略图" :alt="item.服装名称" loading="lazy" />
          </span>
          <span class="costume-picker__name">{{ item.服装名称 }}</span>
          <span class="costume-picker__meta">
            {{ item.分类 }}<template v-if="item.library === 'costume-anime'"> · 二次元</template>
          </span>
        </button>
        <p v-if="!loading && !filtered.length" class="costume-picker__empty">
          没有匹配的服装。
        </p>
      </div>
    </div>
  </Modal>
</template>

<style scoped>
.costume-picker {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.costume-picker__bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  padding-bottom: 12px;
}

.costume-picker__search {
  flex: 1 1 260px;
  height: 38px;
  padding: 0 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel);
  color: var(--text-strong);
  font-size: 14px;
}

.costume-picker__count {
  color: var(--text-muted);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.costume-picker__error {
  color: var(--danger);
  font-size: 13px;
}

.costume-picker__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px;
  min-height: 0;
  overflow-y: auto;
  padding: 2px;
}

.costume-picker__item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  background: var(--surface-panel);
  color: var(--text-body);
  text-align: left;
  cursor: pointer;
}

.costume-picker__item:hover {
  border-color: var(--primary);
}

.costume-picker__thumb {
  display: flex;
  align-items: center;
  justify-content: center;
  aspect-ratio: 2 / 3;
  overflow: hidden;
  border-radius: 8px;
  background: var(--surface-inset);
}

.costume-picker__thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.costume-picker__name {
  overflow: hidden;
  color: var(--text-strong);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.costume-picker__meta {
  color: var(--text-muted);
  font-size: 12px;
}

.costume-picker__empty {
  grid-column: 1 / -1;
  color: var(--text-muted);
  font-size: 13px;
}
</style>
