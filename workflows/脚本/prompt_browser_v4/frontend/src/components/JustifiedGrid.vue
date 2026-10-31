<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

/**
 * 等高行图片布局（Google Photos / Flickr 的 justified layout）。
 *
 * 每个视图都把图片塞进固定比例的框，是「裁切 / 大片留白」的根因。
 * 这里按图片真实宽高算出行高，整行铺满容器宽：
 * - 图片比例不变，不裁切；
 * - 行内没有大块空白；
 * - 最后一行不强行拉伸，按目标行高左对齐。
 *
 * 容器宽度用 ResizeObserver 跟踪；首帧宽度为 0 时先按 1200 排版，
 * 量到真实宽度后重排（测试环境没有 ResizeObserver 时也仍有内容可断言）。
 */
const props = withDefaults(
  defineProps<{
    items: any[]
    ratio: (item: any) => number
    keyOf?: (item: any) => string | number
    targetRowHeight?: number
    gap?: number
  }>(),
  { targetRowHeight: 240, gap: 8 },
)

interface Cell {
  item: any
  index: number
  key: string | number
  width: number
  height: number
}

const root = ref<HTMLElement | null>(null)
const measured = ref(0)
let observer: ResizeObserver | null = null

const availableWidth = computed(() => {
  if (measured.value > 0) return measured.value
  // 还没量到宽度（首帧 / <details> 收起 / 测试环境）时给一个保守宽度，
  // 保证有内容可渲染，量到后立即重排。
  return 1200
})

const rows = computed<Cell[][]>(() => {
  const avail = availableWidth.value
  const gap = props.gap
  const target = props.targetRowHeight
  const result: Cell[][] = []
  let current: Array<{ item: any; index: number; key: string | number; ratio: number }> = []
  let ratioSum = 0

  const flush = (justify: boolean) => {
    if (!current.length) return
    const count = current.length
    let height = justify ? (avail - gap * (count - 1)) / ratioSum : target
    height = Math.max(24, height)
    const widths = current.map((c) => Math.floor(c.ratio * height))
    if (justify) {
      const used = widths.reduce((sum, w) => sum + w, 0) + gap * (count - 1)
      // 取整会留下几像素，补给最后一个，否则整行右侧会有一条缝
      widths[count - 1] += Math.max(0, avail - used)
    }
    result.push(
      current.map((c, i) => ({
        item: c.item,
        index: c.index,
        key: c.key,
        width: widths[i],
        height: Math.floor(height),
      })),
    )
    current = []
    ratioSum = 0
  }

  props.items.forEach((item, index) => {
    // 极端长图 / 全景图限幅，避免单张把一行撑爆
    const ratio = Math.max(0.25, Math.min(4, props.ratio(item) || 0.75))
    current.push({
      item,
      index,
      key: props.keyOf ? props.keyOf(item) : index,
      ratio,
    })
    ratioSum += ratio
    if (ratioSum * target + gap * (current.length - 1) >= avail) flush(true)
  })
  flush(false)
  return result
})

onMounted(() => {
  const node = root.value
  if (!node) return
  measured.value = node.clientWidth
  if (typeof ResizeObserver === 'undefined') return
  observer = new ResizeObserver((entries) => {
    const rect = entries[0]?.contentRect
    if (rect && rect.width > 0) measured.value = Math.floor(rect.width)
  })
  observer.observe(node)
})

onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <div ref="root" class="jgrid">
    <div
      v-for="(row, rowIndex) in rows"
      :key="rowIndex"
      class="jrow"
      :style="{ gap: `${gap}px`, marginBottom: `${gap}px` }"
    >
      <div
        v-for="cell in row"
        :key="cell.key"
        class="jcell"
        :style="{ width: `${cell.width}px` }"
      >
        <slot
          :item="cell.item"
          :index="cell.index"
          :width="cell.width"
          :height="cell.height"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.jgrid {
  width: 100%;
}

.jrow {
  display: flex;
  align-items: flex-start;
  justify-content: flex-start;
}

.jcell {
  flex: none;
  min-width: 0;
}
</style>
