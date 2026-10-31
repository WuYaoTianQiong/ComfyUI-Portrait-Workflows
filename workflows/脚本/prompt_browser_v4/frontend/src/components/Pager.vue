<script setup lang="ts">
/**
 * 分页器：列表页的「上一页 / 页码 / 下一页」。
 *
 * 不持有状态，页码由页面传入；翻页通过 `update:page` 回传。
 */
const props = defineProps<{ page: number; totalPages: number; compact?: boolean }>()
const emit = defineEmits<{ 'update:page': [value: number] }>()
</script>

<template>
  <div class="pager">
    <button
      class="btn btn-sm"
      :class="{ compact: props.compact }"
      :disabled="page <= 1"
      @click="emit('update:page', page - 1)"
    >
      {{ props.compact ? '‹' : '上一页' }}
    </button>
    <span class="page-num">{{ page }} / {{ totalPages }}</span>
    <button
      class="btn btn-sm"
      :class="{ compact: props.compact }"
      :disabled="page >= totalPages"
      @click="emit('update:page', page + 1)"
    >
      {{ props.compact ? '›' : '下一页' }}
    </button>
  </div>
</template>

<style scoped>
.pager {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
}

.page-num {
  font-size: var(--fs-xs);
  color: var(--muted);
}

/* 侧栏只有 380px，上一页/下一页四个字塞不下，用箭头 */
.compact {
  padding: 2px 8px;
}
</style>
