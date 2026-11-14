<script setup lang="ts">
import Pager from './Pager.vue'

defineProps<{
  selectedCount: number
  generating: boolean
  page: number
  totalPages: number
  pageSize: number
  selectedId: number | null
  pageSizes: number[]
}>()

defineEmits<{
  selectAll: []
  clearSelection: []
  batchFavorite: []
  batchReplace: []
  batchGenerate: []
  batchDelete: []
  'update:page': [page: number]
  'page-size-change': [size: number]
  locate: []
}>()
</script>

<template>
  <div v-if="selectedCount" class="bulk">
    <span class="bulk-count">已选 <b>{{ selectedCount }}</b> 条</span>
    <button class="btn btn-sm" @click="$emit('selectAll')">全选本页</button>
    <button class="btn btn-sm" @click="$emit('clearSelection')">取消</button>
    <span class="spacer" />
    <button class="btn btn-sm" @click="$emit('batchFavorite')">收藏</button>
    <button
      class="btn btn-sm"
      title="替换选中提示词的某一类碎片后出图"
      @click="$emit('batchReplace')"
    >
      批量替换
    </button>
    <button
      class="btn btn-sm primary"
      :class="{ loading: generating }"
      :disabled="generating"
      @click="$emit('batchGenerate')"
    >
      批量出图
    </button>
    <button class="btn btn-sm danger" @click="$emit('batchDelete')">删除</button>
  </div>

  <div class="pager-row">
    <span class="count">第 {{ page }} / {{ totalPages }} 页</span>
    <div class="pager-center">
      <Pager compact :page="page" :total-pages="totalPages" @update:page="$emit('update:page', $event)" />
      <select
        :value="pageSize"
        class="page-size"
        title="每页条数"
        @change="$emit('page-size-change', Number(($event.target as HTMLSelectElement).value))"
      >
        <option v-for="size in pageSizes" :key="size" :value="size">{{ size }} 条/页</option>
      </select>
    </div>
    <button
      class="btn btn-sm locate-btn"
      :disabled="selectedId === null"
      title="滚动到当前选中的提示词"
      @click="$emit('locate')"
    >
      定位
    </button>
  </div>
</template>

<style scoped>
.bulk {
  position: fixed;
  bottom: var(--gap-lg);
  left: 50%;
  transform: translateX(-50%);
  z-index: var(--z-modal);
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: var(--gap-sm);
  padding: var(--gap-sm) var(--gap-md);
  border-radius: var(--radius-pill);
  background: var(--panel-3);
  border: 1px solid var(--border-strong);
  box-shadow: var(--shadow);
  font-size: var(--fs-sm);
  white-space: nowrap;
}

.spacer {
  flex: 1;
}

.bulk > button {
  flex: none;
}

@media (max-width: 640px) {
  .bulk {
    width: calc(100vw - var(--gap-lg) - var(--gap-xs));
    flex-wrap: wrap;
    justify-content: center;
    border-radius: var(--radius-lg);
    white-space: normal;
  }
}

.bulk-count b {
  color: var(--accent-link);
}

.pager-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm) var(--gap);
  border-top: 1px solid var(--border);
}

.pager-row .count {
  justify-self: start;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--muted);
  font-size: var(--fs-xs);
}

.pager-center {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--gap-xs);
}

.locate-btn {
  justify-self: end;
  white-space: nowrap;
}

.page-size {
  flex: none;
  background: var(--panel-2);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 3px 4px;
  font: inherit;
  font-size: var(--fs-xs);
}
</style>
