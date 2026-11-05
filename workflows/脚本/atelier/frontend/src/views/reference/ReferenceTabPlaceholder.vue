<script setup lang="ts">
import Skeleton from '../../components/Skeleton.vue'

/**
 * 页签占位骨架（阶段 1.1）。
 *
 * 五个页签共用同一套「建设中」结构：标题 + 状态徽标 + 说明 + 结构化骨架。
 * 卡片比例与间距按 §5 取值；本组件不接数据层，阶段 2–3 由各页签替换。
 */
withDefaults(
  defineProps<{
    /** 页签内容标题，如「姿势库」。 */
    title: string
    /** 一句话说明该页签将来做什么。 */
    description: string
    /** 建设进度说明（必须明确写出「建设中」）。 */
    hint: string
    /** 卡片缩略图宽高比：姿势 3/4、服装 2/3、人像 4/5（§5）。 */
    ratio?: string
    /** 三库用 grid（药丸 + 卡片），合成台 / 设置用 form（分区占位）。 */
    layout?: 'grid' | 'form'
  }>(),
  { ratio: '3 / 4', layout: 'grid' },
)
</script>

<template>
  <section class="tab-placeholder">
    <header class="tab-placeholder__head">
      <div class="tab-placeholder__title-row">
        <h2 class="tab-placeholder__title">{{ title }}</h2>
        <span class="tab-placeholder__badge">建设中</span>
      </div>
      <p class="tab-placeholder__desc">{{ description }}</p>
      <p class="tab-placeholder__hint">{{ hint }}</p>
    </header>

    <template v-if="layout === 'grid'">
      <div class="tab-placeholder__pills" aria-hidden="true">
        <span v-for="n in 5" :key="n" class="tab-placeholder__pill" />
      </div>

      <div class="tab-placeholder__grid" aria-hidden="true">
        <article v-for="n in 5" :key="n" class="tab-placeholder__card">
          <div class="tab-placeholder__thumb" :style="{ aspectRatio: ratio }">
            <Skeleton variant="block" width="100%" height="100%" radius="18px" />
          </div>
          <Skeleton width="72%" />
          <Skeleton width="46%" />
        </article>
      </div>
    </template>

    <div v-else class="tab-placeholder__form" aria-hidden="true">
      <section v-for="n in 3" :key="n" class="tab-placeholder__block">
        <Skeleton width="28%" />
        <Skeleton variant="block" width="100%" height="64px" radius="14px" />
      </section>
    </div>
  </section>
</template>

<style scoped>
.tab-placeholder {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding-bottom: 8px;
}

.tab-placeholder__head {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.tab-placeholder__title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tab-placeholder__title {
  margin: 0;
  font-size: var(--fs-xl);
  font-weight: 600;
  line-height: var(--lh-xl);
  color: var(--text);
}

.tab-placeholder__badge {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border-radius: 9999px;
  background: #262626;
  color: #fafafa;
  font-size: var(--fs-xs);
  font-weight: 500;
  line-height: 1;
}

/* 说明正文用主文字色，避免灰底灰字看不清。 */
.tab-placeholder__desc {
  margin: 0;
  font-size: var(--fs);
  line-height: 1.6;
  color: var(--text);
}

.tab-placeholder__hint {
  margin: 0;
  font-size: var(--fs-sm);
  line-height: 1.6;
  color: var(--muted);
}

/* 筛选药丸占位：高度 32px、全圆、gap 8px（§5「标签」行）。 */
.tab-placeholder__pills {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tab-placeholder__pill {
  width: 72px;
  height: 32px;
  border: 1px solid var(--border);
  border-radius: 9999px;
  background: var(--panel-2);
}

/*
 * 卡片栅格：1280px 内容宽 5 列、gap 16px；390px 视口 2 列（171px），
 * 与 §5 实测一致，不产生横向溢出。
 */
.tab-placeholder__grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 16px;
}

/* 卡片：20px 圆角 / 8px 内边距 / 深色 #262626（§5）。 */
.tab-placeholder__card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  padding: 8px;
  border-radius: 20px;
  background: #262626;
}

.tab-placeholder__thumb {
  width: 100%;
  overflow: hidden;
  border-radius: 18px;
  background: var(--panel-3);
}

/* 合成台 / 设置：分区卡 22px 圆角 / 24px 内边距（§5 补充实测项）。 */
.tab-placeholder__form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.tab-placeholder__block {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 24px;
  border-radius: 22px;
  background: #262626;
}

@media (max-width: 1100px) {
  .tab-placeholder__grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .tab-placeholder__grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 639px) {
  .tab-placeholder__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>