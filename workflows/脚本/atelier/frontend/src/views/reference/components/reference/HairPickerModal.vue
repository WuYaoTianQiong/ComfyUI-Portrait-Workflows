<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { HairItem } from '../../../../api/reference'
import { useReferenceHairs } from '../../../../composables/useReferenceLibrary'
import Modal from '../../../../components/Modal.vue'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'select', item: HairItem): void
}>()

const { items, loading, error, load } = useReferenceHairs()
const query = ref('')
const onlyUsable = ref(true)

watch(
  () => props.open,
  (open) => {
    if (open) void load()
  },
)

const filtered = computed(() => {
  const needle = query.value.trim().toLowerCase()
  return items.value.filter((item) => {
    if (onlyUsable.value && !item.可用于发型槽) return false
    if (needle && !item.检索.toLowerCase().includes(needle)) return false
    return true
  })
})
</script>

<template>
  <Modal :open="open" title="从发型库选择（第 4 槽）" width="min(980px, 94vw)" height="min(78vh, 760px)" @close="emit('close')">
    <div class="hair-picker">
      <div class="hair-picker__bar">
        <input
          v-model="query"
          type="search"
          class="hair-picker__search"
          placeholder="搜索发型名称、分区或 ID…"
          data-testid="hair-picker-search"
        />
        <label class="hair-picker__toggle">
          <input v-model="onlyUsable" type="checkbox" />
          仅显示可用于第 4 槽
        </label>
        <span class="hair-picker__count">
          {{ loading ? '加载中…' : `${filtered.length} / ${items.length}` }}
        </span>
      </div>

      <p v-if="error" class="hair-picker__error" role="alert">{{ error }}</p>

      <div v-else class="hair-picker__grid" data-testid="hair-picker-grid">
        <button
          v-for="item in filtered"
          :key="item.id"
          type="button"
          class="hair-picker__item"
          :title="`${item.标题} · ${item.分区}`"
          :data-testid="`hair-picker-item-${item.id}`"
          @click="emit('select', item)"
        >
          <span class="hair-picker__thumb">
            <img v-if="item.缩略图" :src="item.缩略图" :alt="item.标题" loading="lazy" />
          </span>
          <span class="hair-picker__name">{{ item.标题 }}</span>
          <span class="hair-picker__meta">
            {{ item.分区 }} · {{ item.可用于发型槽 ? '背面可用' : '仅正面' }}
          </span>
        </button>
        <p v-if="!loading && !filtered.length" class="hair-picker__empty">
          没有匹配的发型。关掉「仅显示可用于第 4 槽」可浏览全部。
        </p>
      </div>
    </div>
  </Modal>
</template>

<style scoped>
.hair-picker {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.hair-picker__bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  padding-bottom: 12px;
}

.hair-picker__search {
  flex: 1 1 260px;
  height: 38px;
  padding: 0 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel);
  color: var(--text-strong);
  font-size: 14px;
}

.hair-picker__toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-muted);
  font-size: 13px;
  white-space: nowrap;
}

.hair-picker__count {
  color: var(--text-muted);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.hair-picker__error {
  color: var(--danger);
  font-size: 13px;
}

.hair-picker__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px;
  min-height: 0;
  overflow-y: auto;
  padding: 2px;
}

.hair-picker__item {
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

.hair-picker__item:hover {
  border-color: var(--accent);
}

.hair-picker__thumb {
  display: block;
  aspect-ratio: 3 / 4;
  overflow: hidden;
  border-radius: 8px;
  background: var(--surface-sunken);
}

.hair-picker__thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.hair-picker__name {
  overflow: hidden;
  font-size: 13px;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hair-picker__meta {
  overflow: hidden;
  color: var(--text-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hair-picker__empty {
  grid-column: 1 / -1;
  color: var(--text-muted);
  font-size: 13px;
}
</style>