<script setup lang="ts">
import { computed } from 'vue'

import EmptyState from '../../../components/EmptyState.vue'
import Pager from '../../../components/Pager.vue'
import Skeleton from '../../../components/Skeleton.vue'

import { PAGE_SIZES } from './poseView'

/**
 * 参考图库统一网格容器。
 *
 * 负责四件事：
 * - 列数：分组视图 5 列 / 单张视图 6 列（≥1024px），640/768 逐级降列，390px 下 2 列不横向溢出；
 * - 间距：`gap` 固定 16px（§5）；
 * - 状态：骨架屏、空态、错误重试；
 * - 底部分页条：三库统一分页（Pager + 每页条数 20/60/100/200），替代旧的「加载更多」按钮。
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
    /** 当前页码（从 1 开始） */
    page?: number
    /** 总页数（至少 1） */
    totalPages?: number
    /** 每页条数 */
    pageSize?: number
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
    page: 1,
    totalPages: 1,
    pageSize: 60,
    emptyTitle: '没有找到匹配的条目',
    emptyHint: '试试更换搜索词或重置筛选条件',
    skeletonCount: 10,
    skeletonAspect: '3/4',
  },
)

const emit = defineEmits<{
  (e: 'update:page', value: number): void
  (e: 'update:pageSize', value: number): void
  (e: 'retry'): void
}>()

const gridClass = computed(() => (props.mode === 'single' ? 'is-single' : 'is-group'))

const skeletonThumbStyle = computed(() => ({
  aspectRatio: props.skeletonAspect.replace('/', ' / '),
}))

/** 首屏加载（还没有任何结果）才铺骨架；追加加载时保留旧卡片。 */
const showSkeleton = computed(() => props.loading && props.total === 0)
const showBlockingError = computed(() => Boolean(props.error) && props.total === 0)
const showEmpty = computed(() => !props.loading && !showBlockingError.value && props.total === 0)
/** 分页条只在有结果且没有阻塞错误时出现；骨架 / 空态 / 错误分支不显示。 */
const showPager = computed(() => !showBlockingError.value && props.total > 0)

/** 每页条数下拉：`select` 的 value 是字符串，这里转成数字再回传。 */
function onPageSizeChange(event: Event): void {
  const next = Number((event.target as HTMLSelectElement).value)
  if (!Number.isFinite(next)) return
  emit('update:pageSize', next)
}
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

    <!-- 三库统一分页条：左侧页码、中间 Pager、右侧每页条数（与提示词页同款） -->
    <div v-if="showPager" class="ref-grid__pager">
      <span class="ref-grid__pager-label" data-testid="ref-grid-page-label">
        第 {{ page }} / {{ totalPages }} 页
      </span>
      <Pager compact :page="page" :total-pages="totalPages" @update:page="emit('update:page', $event)" />
      <select
        class="ref-grid__page-size"
        data-testid="ref-grid-page-size"
        title="每页条数"
        aria-label="每页条数"
        :value="pageSize"
        @change="onPageSizeChange"
      >
        <option v-for="size in PAGE_SIZES" :key="size" :value="size">{{ size }} 条/页</option>
      </select>
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

/*
 * 分页条：三列（页码 / Pager / 每页条数），与 PromptView 的 `.pager-row` 同款结构。
 * 全部用设计令牌，浅色主题下同样可读；只过渡颜色，不要 `transition: all`。
 */
.ref-grid__pager {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center;
  gap: var(--gap-sm);
  padding-top: var(--gap-sm);
  border-top: 1px solid var(--border);
}

.ref-grid__pager-label {
  justify-self: start;
  min-width: 0;
  overflow: hidden;
  color: var(--text-strong);
  font-size: var(--fs-sm);
  line-height: 1.5;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.ref-grid__page-size {
  justify-self: end;
  flex: none;
  padding: var(--gap-xs) var(--gap-sm);
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--fill-faint);
  color: var(--text-strong);
  font-family: inherit;
  font-size: var(--fs-sm);
  line-height: 1.5;
  transition:
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease);
}

.ref-grid__page-size:hover {
  border-color: var(--border-strong);
}

.ref-grid__page-size:focus-visible {
  border-color: var(--border-strong);
  outline: 2px solid var(--primary);
  outline-offset: 1px;
}

@media (max-width: 480px) {
  /* 390px 视口：页码独占一行，Pager 与每页条数分列两侧，不横向溢出 */
  .ref-grid__pager {
    grid-template-columns: minmax(0, 1fr) auto;
    row-gap: var(--gap-xs);
  }

  .ref-grid__pager-label {
    grid-column: 1 / -1;
  }
}
</style>