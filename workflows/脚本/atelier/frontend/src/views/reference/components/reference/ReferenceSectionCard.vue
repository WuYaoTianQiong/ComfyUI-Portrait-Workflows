<script setup lang="ts">
/**
 * 合成台分区卡。
 *
 * §5 补充实测：Section 736.66 × 226.5px、圆角 22px、内边距 24px。
 * 宽高都随内容区自适应（736.66 由 1280 内容区的 7/12 列换算得到），
 * `minHeight` 只在需要与 React 首屏高度对齐时传入。
 */

withDefaults(
  defineProps<{
    title: string
    /** 标题右侧的说明文字 */
    subtitle?: string
    /** 最小高度（px）；0 表示跟随内容 */
    minHeight?: number
  }>(),
  { subtitle: '', minHeight: 0 },
)
</script>

<template>
  <section
    class="section-card"
    :style="minHeight > 0 ? { minHeight: `${minHeight}px` } : undefined"
  >
    <header class="section-card__head">
      <h2 class="section-card__title">{{ title }}</h2>
      <span v-if="subtitle" class="section-card__subtitle">{{ subtitle }}</span>
      <div class="section-card__actions">
        <slot name="actions" />
      </div>
    </header>

    <div class="section-card__body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.section-card {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  padding: 24px;
  border-radius: 22px;
  background: #171717;
}

.section-card__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}

/* 分区标题 14px / 600（React Section title） */
.section-card__title {
  margin: 0;
  color: #fafafa;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.4;
}

.section-card__subtitle {
  color: #a1a1a1;
  font-size: 11px;
  line-height: 1.4;
}

.section-card__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-left: auto;
}

.section-card__body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

/* 390px 窄屏：内边距收窄到 16px，避免内容被挤到溢出 */
@media (max-width: 639px) {
  .section-card {
    padding: 16px;
    border-radius: 18px;
  }
}
</style>