<script setup lang="ts">
import { computed } from 'vue'

import EmptyState from '../../../components/EmptyState.vue'
import Skeleton from '../../../components/Skeleton.vue'

/**
 * 参考图库统一网格容器。
 *
 * 负责四件事：
 * - 列数：分组视图 5 列 / 单张视图 6 列（≥1024px），640/768 逐级降列，390px 下 2 列不横向溢出；
 * - 间距：`gap` 固定 16px（§5）；
 * - 状态：骨架屏、空态、错误重试；
 * - 「加载更多」按钮（§7 冻结：不用分页 Pager）：173.08 × 36px、圆角 8px、1px 边框、
 *   14px / 500、底 rgba(255,255,255,0.045)，文案带剩余数量。
 *
 * 本组件不持有数据与筛选状态，只做布局与状态呈现，卡片由插槽传入。
 */
const props = withDefaults(
  defineProps<{
    /** 分组视图 5 列 / 单张视图 6 列（大屏） */
    mode?: 'group' | 'single'
    loading?: boolean
    error?: string | null
    /** 当前结果条数（组或张） */
    total?: number
    /** 是否还有未展示的条目 */
    hasMore?: boolean
    /** 剩余数量（组或张） */
    remaining?: number
    /** 量词：「组」或「张」 */
    unit?: '组' | '张'
    emptyTitle?: string
    emptyHint?: string
    /** 加载态骨架卡片数量 */
    skeletonCount?: number
    /** 骨架缩略图比例 */
    skeletonAspect?: '3/4' | '2/3' | '4/5'
  }>(),
  {
    mode: 'group',
    loading: false,
    error: null,
    total: 0,
    hasMore: false,
    remaining: 0,
    unit: '组',
    emptyTitle: '没有找到匹配的条目',
    emptyHint: '试试更换搜索词或重置筛选条件',
    skeletonCount: 10,
    skeletonAspect: '3/4',
  },
)

const emit = defineEmits<{
  (e: 'load-more'): void
  (e: 'retry'): void
}>()

const gridClass = computed(() => (props.mode === 'single' ? 'is-single' : 'is-group'))

const moreLabel = computed(() => `加载更多（剩余 ${props.remaining} ${props.unit}）`)

const skeletonThumbStyle = computed(() => ({
  aspectRatio: props.skeletonAspect.replace('/', ' / '),
}))

/** 首屏加载（还没有任何结果）才铺骨架；追加加载时保留旧卡片。 */
const showSkeleton = computed(() => props.loading && props.total === 0)
const showBlockingError = computed(() => Boolean(props.error) && props.total === 0)
const showEmpty = computed(() => !props.loading && !showBlockingError.value && props.total === 0)
</script>

<template>
  <div class="ref-grid-wrap">
    <!-- 已有结果时刷新失败：横幅提示，不清空旧内容 -->
    <div v-if="error && total > 0" class="ref-grid__banner" role="alert">
      <span>{{ error }}</span>
      <button type="button" class="ref-grid__banner-btn" @click="emit('retry')">重试</button>
    </div>

    <div v-if="showSkeleton" class="ref-grid" :class="gridClass" aria-busy="true">
      <div v-for="n in skeletonCount" :key="`skeleton-${n}`" class="ref-skeleton">
        <div class="ref-skeleton__thumb" :style="skeletonThumbStyle">
          <Skeleton variant="block" width="100%" height="100%" radius="18px" />
        </div>
        <div class="ref-skeleton__body">
          <Skeleton :count="2" height="12px" />
          <Skeleton width="60%" height="10px" />
        </div>
      </div>
    </div>

    <div v-else-if="showBlockingError" class="ref-grid__error" role="alert">
      <p class="ref-grid__error-text">{{ error }}</p>
      <button type="button" class="ref-grid__retry" @click="emit('retry')">重新加载</button>
    </div>

    <EmptyState v-else-if="showEmpty" size="big" :text="emptyTitle" :hint="emptyHint" />

    <div v-else class="ref-grid" :class="gridClass">
      <slot />
    </div>

    <!-- 加载更多：§5 补充实测项 173.08 × 36px -->
    <div v-if="hasMore" class="ref-grid__more">
      <button type="button" class="ref-grid__more-btn" :disabled="loading" @click="emit('load-more')">
        {{ moreLabel }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.ref-grid-wrap {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

/* 网格：间距固定 16px；列数按视图与断点切换 */
.ref-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  min-width: 0;
}

@media (min-width: 640px) {
  .ref-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (min-width: 768px) {
  .ref-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}

@media (min-width: 1024px) {
  .ref-grid.is-group {
    grid-template-columns: repeat(5, minmax(0, 1fr));
  }

  .ref-grid.is-single {
    grid-template-columns: repeat(6, minmax(0, 1fr));
  }
}

/* 骨架卡片：结构同真实卡片，避免加载完成时跳版 */
.ref-skeleton {
  display: flex;
  flex-direction: column;
  padding: 8px;
  border-radius: 20px;
  background: var(--surface-card);
}

.ref-skeleton__thumb {
  position: relative;
  width: 100%;
  overflow: hidden;
  border-radius: 18px;
  background: var(--surface-raised);
}

.ref-skeleton__body {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 6px 6px;
}

/* 错误 / 重试 */
.ref-grid__banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  border: 1px solid var(--danger-border);
  border-radius: 10px;
  background: var(--danger-surface);
  color: var(--danger-text-soft);
  font-size: 12px;
}

.ref-grid__banner-btn,
.ref-grid__retry {
  flex: none;
  padding: 4px 12px;
  border: 1px solid currentColor;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  font-size: 12px;
}

.ref-grid__error {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 48px 16px;
  border: 1px solid var(--danger-border-soft);
  border-radius: 20px;
  background: var(--danger-surface-faint);
  text-align: center;
}

.ref-grid__error-text {
  margin: 0;
  color: var(--danger-text-soft);
  font-size: 13px;
  line-height: 1.6;
}

.ref-grid__more {
  display: flex;
  justify-content: center;
  padding-top: 8px;
}

/* §5 补充实测项：173.08 × 36px、圆角 8px、1px 边框、14px 500、底 rgba(255,255,255,.045) */
.ref-grid__more-btn {
  box-sizing: border-box;
  width: 173.08px;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--fill-faint);
  color: var(--text-strong);
  font-size: 14px;
  font-weight: 500;
  line-height: 1;
  white-space: nowrap;
  transition:
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease);
}

.ref-grid__more-btn:hover:not(:disabled) {
  border-color: var(--border-strong);
  background: var(--fill-soft);
}

.ref-grid__more-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (max-width: 400px) {
  /* 390px 视口：按钮不撑破内容区 */
  .ref-grid__more-btn {
    width: 100%;
    max-width: 240px;
  }
}
</style>