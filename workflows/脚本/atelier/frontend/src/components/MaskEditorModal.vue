<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, shallowRef, watch } from 'vue'

import Modal from './Modal.vue'
import Icon from './Icon.vue'

/**
 * 涂抹遮罩编辑器。
 *
 * 不依赖任何后端画布能力：在目标图上直接涂，导出「白=重绘、黑=保留」的灰度 PNG，
 * 由后端把白色区域烘焙进 alpha 通道，复用工作流原生的 LoadImage MASK 链路。
 */
const props = defineProps<{
  open: boolean
  imageUrl: string
  initialMaskUrl?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'save', payload: { dataUrl: string | null }): void
}>()

const canvasEl = ref<HTMLCanvasElement | null>(null)
const wrapEl = ref<HTMLDivElement | null>(null)
const loading = ref(false)
const ready = ref(false)
const errorText = ref('')
const tool = ref<'brush' | 'eraser' | 'wand' | 'pan'>('brush')
const brushSize = ref(28)
const wandTolerance = ref(30)
const wandMode = ref<'add' | 'subtract'>('add')
const undoStack = ref<string[]>([])
const isDrawing = ref(false)
const isPanning = ref(false)

const image = shallowRef<HTMLImageElement | null>(null)
const mask = shallowRef<HTMLCanvasElement | null>(null)
const overlay = shallowRef<HTMLCanvasElement | null>(null)
const sourceData = shallowRef<ImageData | null>(null)
const view = reactive({ scale: 1, x: 0, y: 0 })
const hover = reactive({ x: 0, y: 0, show: false })

const canUndo = computed(() => undoStack.value.length > 0)

/** 指针最后一次的位置：视口坐标 + 原图坐标。 */
const cursor = { vx: 0, vy: 0, x: 0, y: 0 }
const panStart = { clientX: 0, clientY: 0 }

function ctxOf(el: HTMLCanvasElement | null) {
  return el?.getContext('2d') ?? null
}

/**
 * canvas 2d 的 fillStyle / strokeStyle 只接受具体色值，不能直接吃 CSS 变量。
 * 这里按当前主题解析一次并缓存；`data-theme` 变化时自动失效，避免 draw() 在
 * 指针移动的每一帧都调用 getComputedStyle。
 */
interface CanvasTheme {
  background: string
  mask: string
  cursor: string
}

let canvasTheme: CanvasTheme | null = null
let canvasThemeKey = ''

function resolveCanvasTheme(): CanvasTheme {
  const key = document.documentElement.getAttribute('data-theme') ?? 'dark'
  if (canvasTheme && canvasThemeKey === key) return canvasTheme
  const root = getComputedStyle(document.documentElement)
  const read = (name: string, fallback: string) => root.getPropertyValue(name).trim() || fallback
  canvasTheme = {
    background: read('--canvas-bg', 'rgb(20 20 20)'),
    mask: read('--mask-overlay', 'rgba(255, 58, 58, 0.92)'),
    cursor: read('--canvas-cursor', 'rgba(255, 255, 255, 0.85)'),
  }
  canvasThemeKey = key
  return canvasTheme
}

function loadImage(url: string): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    if (!url) {
      resolve(null)
      return
    }
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => resolve(null)
    img.src = url
  })
}

function scheduleResize() {
  requestAnimationFrame(() => {
    requestAnimationFrame(() => resize())
  })
}

function resize(): boolean {
  const canvas = canvasEl.value
  const wrap = wrapEl.value
  if (!canvas || !wrap) return false
  const width = wrap.clientWidth
  const height = wrap.clientHeight
  if (width <= 0 || height <= 0) return false
  canvas.width = width
  canvas.height = height
  const ov = overlay.value
  if (ov) {
    ov.width = width
    ov.height = height
  }
  draw()
  return true
}

function fit() {
  const canvas = canvasEl.value
  const img = image.value
  if (!canvas || !img) return
  const scale = Math.min(canvas.width / img.naturalWidth, canvas.height / img.naturalHeight) * 0.96
  view.scale = scale
  view.x = (canvas.width - img.naturalWidth * scale) / 2
  view.y = (canvas.height - img.naturalHeight * scale) / 2
  draw()
}

function draw() {
  const canvas = canvasEl.value
  const img = image.value
  const m = mask.value
  const ov = overlay.value
  const ctx = ctxOf(canvas)
  const octx = ctxOf(ov)
  if (!canvas || !ctx || !img || !m || !ov || !octx) return
  const theme = resolveCanvasTheme()

  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  ctx.fillStyle = theme.background
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.save()
  ctx.translate(view.x, view.y)
  ctx.scale(view.scale, view.scale)
  ctx.drawImage(img, 0, 0)
  ctx.restore()

  // 遮罩染红：只按 mask 的 alpha 上色，空区域完全透明
  octx.setTransform(1, 0, 0, 1, 0, 0)
  octx.clearRect(0, 0, ov.width, ov.height)
  octx.save()
  octx.translate(view.x, view.y)
  octx.scale(view.scale, view.scale)
  octx.drawImage(m, 0, 0)
  octx.restore()
  octx.globalCompositeOperation = 'source-in'
  octx.fillStyle = theme.mask
  octx.fillRect(0, 0, ov.width, ov.height)
  octx.globalCompositeOperation = 'source-over'

  ctx.globalAlpha = 0.72
  ctx.drawImage(ov, 0, 0)
  ctx.globalAlpha = 1

  // 笔刷大小指示圈（魔棒不需要）
  if (hover.show && (tool.value === 'brush' || tool.value === 'eraser')) {
    ctx.beginPath()
    ctx.arc(hover.x, hover.y, Math.max(2, (brushSize.value * view.scale) / 2), 0, Math.PI * 2)
    ctx.strokeStyle = theme.cursor
    ctx.lineWidth = 1
    ctx.stroke()
  }
}

function toCanvasPoint(event: PointerEvent) {
  const canvas = canvasEl.value!
  const rect = canvas.getBoundingClientRect()
  const vx = (event.clientX - rect.left) * (canvas.width / rect.width)
  const vy = (event.clientY - rect.top) * (canvas.height / rect.height)
  return {
    vx,
    vy,
    x: (vx - view.x) / view.scale,
    y: (vy - view.y) / view.scale,
  }
}

function pushUndo() {
  const m = mask.value
  if (!m) return
  undoStack.value = [...undoStack.value, m.toDataURL('image/png')].slice(-8)
}

function paintDot(dot: { x: number; y: number }) {
  const m = mask.value
  const ctx = ctxOf(m)
  if (!m || !ctx) return
  ctx.fillStyle = 'white'
  ctx.globalCompositeOperation = tool.value === 'eraser' ? 'destination-out' : 'source-over'
  ctx.beginPath()
  ctx.arc(dot.x, dot.y, brushSize.value / 2, 0, Math.PI * 2)
  ctx.fill()
}

function paintSegment(
  from: { x: number; y: number },
  to: { x: number; y: number },
) {
  const m = mask.value
  const ctx = ctxOf(m)
  if (!m || !ctx) return
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  ctx.lineWidth = brushSize.value
  ctx.strokeStyle = 'white'
  ctx.globalCompositeOperation = tool.value === 'eraser' ? 'destination-out' : 'source-over'
  ctx.beginPath()
  ctx.moveTo(from.x, from.y)
  ctx.lineTo(to.x, to.y)
  ctx.stroke()
}

/**
 * 魔棒：从点击点开始，泛洪选择「颜色差在容差内且四连通」的区域。
 *
 * 颜色差按 RGB 最大通道差值计算（人对单通道偏色也敏感，比欧氏距离更直观）。
 * 选择结果直接写入遮罩：加选=白色不透明，减选=擦除 alpha。
 */
function magicWand(at: { x: number; y: number }) {
  const data = sourceData.value
  const m = mask.value
  if (!data || !m) return
  const width = data.width
  const height = data.height
  const x0 = Math.floor(at.x)
  const y0 = Math.floor(at.y)
  if (x0 < 0 || y0 < 0 || x0 >= width || y0 >= height) return

  const pixels = data.data
  const origin = (y0 * width + x0) * 4
  const seedR = pixels[origin]
  const seedG = pixels[origin + 1]
  const seedB = pixels[origin + 2]
  const tolerance = wandTolerance.value

  const matches = (x: number, y: number) => {
    const p = (y * width + x) * 4
    return (
      Math.abs(pixels[p] - seedR) <= tolerance &&
      Math.abs(pixels[p + 1] - seedG) <= tolerance &&
      Math.abs(pixels[p + 2] - seedB) <= tolerance
    )
  }
  if (!matches(x0, y0)) return

  const visited = new Uint8Array(width * height)
  const selected = new Uint8Array(width * height)
  const stack: number[] = [x0, y0]

  // 扫描线泛洪：每次吃满一整行连续段，比逐像素压栈快很多
  while (stack.length) {
    const y = stack.pop() as number
    const x = stack.pop() as number
    const row = y * width
    if (visited[row + x]) continue

    let left = x
    let right = x
    while (left > 0 && !visited[row + left - 1] && matches(left - 1, y)) left -= 1
    while (right < width - 1 && !visited[row + right + 1] && matches(right + 1, y)) right += 1
    for (let i = left; i <= right; i += 1) {
      visited[row + i] = 1
      selected[row + i] = 1
    }

    for (const nextY of [y - 1, y + 1]) {
      if (nextY < 0 || nextY >= height) continue
      const nextRow = nextY * width
      let nextX = left
      while (nextX <= right) {
        while (nextX <= right && (visited[nextRow + nextX] || !matches(nextX, nextY))) {
          nextX += 1
        }
        if (nextX > right) break
        const startX = nextX
        while (nextX <= right && !visited[nextRow + nextX] && matches(nextX, nextY)) {
          nextX += 1
        }
        stack.push(startX, nextY)
      }
    }
  }

  let count = 0
  for (let i = 0; i < selected.length; i += 1) {
    if (selected[i]) count += 1
  }
  if (!count) return

  pushUndo()
  const selection = document.createElement('canvas')
  selection.width = width
  selection.height = height
  const selectionCtx = selection.getContext('2d')
  const maskCtx = ctxOf(m)
  if (!selectionCtx || !maskCtx) return

  const imageData = selectionCtx.createImageData(width, height)
  const out = imageData.data
  for (let i = 0; i < selected.length; i += 1) {
    if (!selected[i]) continue
    const p = i * 4
    out[p] = 255
    out[p + 1] = 255
    out[p + 2] = 255
    out[p + 3] = 255
  }
  selectionCtx.putImageData(imageData, 0, 0)

  maskCtx.setTransform(1, 0, 0, 1, 0, 0)
  maskCtx.globalCompositeOperation =
    wandMode.value === 'subtract' ? 'destination-out' : 'source-over'
  maskCtx.drawImage(selection, 0, 0)
  maskCtx.globalCompositeOperation = 'source-over'
  draw()
}

function onPointerDown(event: PointerEvent) {
  if (!ready.value) return
  if (event.button === 2 || event.button === 1 || tool.value === 'pan') {
    isPanning.value = true
    panStart.clientX = event.clientX
    panStart.clientY = event.clientY
    canvasEl.value?.setPointerCapture(event.pointerId)
    return
  }
  if (event.button !== 0) return
  const point = toCanvasPoint(event)
  Object.assign(cursor, point)
  if (tool.value === 'wand') {
    magicWand(point)
    return
  }
  if (tool.value === 'brush' || tool.value === 'eraser') {
    pushUndo()
    isDrawing.value = true
    paintDot(point)
    draw()
  }
  canvasEl.value?.setPointerCapture(event.pointerId)
}

function onPointerMove(event: PointerEvent) {
  if (!ready.value) return
  const point = toCanvasPoint(event)
  const previous = { x: cursor.x, y: cursor.y }
  Object.assign(cursor, point)
  hover.x = point.vx
  hover.y = point.vy
  hover.show = true

  if (isPanning.value) {
    view.x += event.clientX - panStart.clientX
    view.y += event.clientY - panStart.clientY
    panStart.clientX = event.clientX
    panStart.clientY = event.clientY
    draw()
    return
  }
  if (isDrawing.value) {
    paintSegment(previous, point)
    draw()
    return
  }
  draw()
}

function onPointerUp(event: PointerEvent) {
  isDrawing.value = false
  isPanning.value = false
  try {
    canvasEl.value?.releasePointerCapture(event.pointerId)
  } catch {
    /* 指针已释放 */
  }
}

function onPointerLeave() {
  hover.show = false
  draw()
}

function onWheel(event: WheelEvent) {
  event.preventDefault()
  const canvas = canvasEl.value
  if (!canvas) return
  const rect = canvas.getBoundingClientRect()
  const vx = (event.clientX - rect.left) * (canvas.width / rect.width)
  const vy = (event.clientY - rect.top) * (canvas.height / rect.height)
  const factor = event.deltaY < 0 ? 1.2 : 0.83
  const next = Math.min(8, Math.max(0.05, view.scale * factor))
  const nx = (vx - view.x) / view.scale
  const ny = (vy - view.y) / view.scale
  view.scale = next
  view.x = vx - nx * next
  view.y = vy - ny * next
  draw()
}

async function undo() {
  const m = mask.value
  const previous = undoStack.value.pop()
  if (!m || !previous) return
  undoStack.value = [...undoStack.value]
  const img = await loadImage(previous)
  const ctx = ctxOf(m)
  if (!img || !ctx) return
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.globalCompositeOperation = 'source-over'
  ctx.clearRect(0, 0, m.width, m.height)
  ctx.drawImage(img, 0, 0)
  draw()
}

function clearAll() {
  const m = mask.value
  const ctx = ctxOf(m)
  if (!m || !ctx) return
  pushUndo()
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.clearRect(0, 0, m.width, m.height)
  draw()
}

function loadInitialMask(url: string) {
  return new Promise<void>((resolve) => {
    const img = new Image()
    img.onload = () => {
      const m = mask.value
      const ctx = ctxOf(m)
      if (!m || !ctx) {
        resolve()
        return
      }
      const temp = document.createElement('canvas')
      temp.width = m.width
      temp.height = m.height
      const tctx = temp.getContext('2d')
      if (!tctx) {
        resolve()
        return
      }
      tctx.drawImage(img, 0, 0, temp.width, temp.height)
      const data = tctx.getImageData(0, 0, temp.width, temp.height).data
      let minAlpha = 255
      for (let i = 3; i < data.length; i += 4) {
        if (data[i] < minAlpha) minAlpha = data[i]
      }
      const out = ctx.createImageData(temp.width, temp.height)
      for (let i = 0; i < data.length; i += 4) {
        const r = data[i]
        const g = data[i + 1]
        const b = data[i + 2]
        const a = data[i + 3]
        // 与后端一致：有真实透明区按透明=重绘，否则按亮度白=重绘
        const paint =
          minAlpha < 255
            ? 255 - a
            : Math.round(0.299 * r + 0.587 * g + 0.114 * b)
        out.data[i] = 255
        out.data[i + 1] = 255
        out.data[i + 2] = 255
        out.data[i + 3] = paint
      }
      ctx.putImageData(out, 0, 0)
      draw()
      resolve()
    }
    img.onerror = () => resolve()
    img.src = url
  })
}

async function setup() {
  if (!props.open) return
  loading.value = true
  ready.value = false
  errorText.value = ''
  undoStack.value = []
  image.value = null
  mask.value = null
  overlay.value = document.createElement('canvas')

  const img = await loadImage(props.imageUrl)
  if (!img) {
    errorText.value = '现象：目标图加载失败，无法涂抹。原因：图片地址无效或文件已被移动。下一步：关闭后重新从画廊或磁盘选一张图。'
    loading.value = false
    return
  }
  image.value = img
  const m = document.createElement('canvas')
  m.width = img.naturalWidth
  m.height = img.naturalHeight
  mask.value = m

  // 魔棒取样用的原图数据（只读，避免每次点击都重绘整图）
  const source = document.createElement('canvas')
  source.width = img.naturalWidth
  source.height = img.naturalHeight
  const sourceCtx = source.getContext('2d')
  sourceCtx?.drawImage(img, 0, 0)
  sourceData.value = sourceCtx ? sourceCtx.getImageData(0, 0, source.width, source.height) : null

  await nextTick()
  // 必须先把 canvas 尺寸按容器设好，再算 fit；否则会按默认 300×150 的尺寸缩放，
  // 图片看着缩在左上角，画布中心点不到图。
  for (let i = 0; i < 6; i += 1) {
    if (resize()) break
    await new Promise((resolve) => setTimeout(resolve, 50))
  }
  if (props.initialMaskUrl) {
    await loadInitialMask(props.initialMaskUrl)
  }
  fit()
  loading.value = false
  ready.value = true
}

function save() {
  const m = mask.value
  if (!m) return
  const out = document.createElement('canvas')
  out.width = m.width
  out.height = m.height
  const ctx = ctxOf(out)
  if (!ctx) return
  // 遮罩文件按「白=重绘、黑=保留」，不带 alpha，后端按亮度识别
  ctx.fillStyle = 'black'
  ctx.fillRect(0, 0, out.width, out.height)
  ctx.drawImage(m, 0, 0)
  const data = ctx.getImageData(0, 0, out.width, out.height).data
  let painted = 0
  for (let i = 0; i < data.length; i += 4) {
    if (data[i] > 8) painted += 1
  }
  emit('save', { dataUrl: painted ? out.toDataURL('image/png') : null })
}

function onKey(event: KeyboardEvent) {
  if (!props.open) return
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
    event.preventDefault()
    undo()
  }
}

watch(
  () => [props.open, props.imageUrl, props.initialMaskUrl],
  ([open]) => {
    if (open) {
      setup()
    } else {
      image.value = null
      mask.value = null
      sourceData.value = null
      undoStack.value = []
    }
  },
  { immediate: true },
)

let boundCanvas: HTMLCanvasElement | null = null

watch(
  () => props.open,
  async (open) => {
    if (open) {
      await nextTick()
      window.addEventListener('keydown', onKey)
      window.addEventListener('resize', resize)
      boundCanvas = canvasEl.value
      boundCanvas?.addEventListener('wheel', onWheel, { passive: false })
      scheduleResize()
    } else {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('resize', resize)
      boundCanvas?.removeEventListener('wheel', onWheel)
      boundCanvas = null
    }
  },
)

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('resize', resize)
  boundCanvas?.removeEventListener('wheel', onWheel)
})
</script>

<template>
  <Modal
    :open="open"
    title="涂抹遮罩"
    width="min(1120px, 94vw)"
    height="min(88vh, 920px)"
    @close="emit('close')"
  >
    <div class="mask-editor">
      <div class="toolbar">
        <button class="btn btn-sm" :class="{ active: tool === 'brush' }" @click="tool = 'brush'">
          <Icon name="paintbrush" /> 画笔
        </button>
        <button class="btn btn-sm" :class="{ active: tool === 'eraser' }" @click="tool = 'eraser'">
          <Icon name="eraser" /> 橡皮
        </button>
        <button class="btn btn-sm" :class="{ active: tool === 'wand' }" @click="tool = 'wand'">
          <Icon name="wand-2" /> 魔棒
        </button>
        <button class="btn btn-sm" :class="{ active: tool === 'pan' }" @click="tool = 'pan'">
          <Icon name="hand" /> 平移
        </button>
        <label v-if="tool !== 'wand'" class="size">
          粗细
          <input v-model.number="brushSize" type="range" min="4" max="160" step="2" />
          <b>{{ brushSize }}</b>
        </label>
        <label v-else class="size">
          容差
          <input v-model.number="wandTolerance" type="range" min="0" max="120" step="2" />
          <b>{{ wandTolerance }}</b>
        </label>
        <div v-if="tool === 'wand'" class="seg-wand">
          <button class="btn btn-sm" :class="{ active: wandMode === 'add' }" @click="wandMode = 'add'">
            加选
          </button>
          <button
            class="btn btn-sm"
            :class="{ active: wandMode === 'subtract' }"
            @click="wandMode = 'subtract'"
          >
            减选
          </button>
        </div>
        <button class="btn btn-sm" @click="fit">适应</button>
        <button class="btn btn-sm" :disabled="!canUndo" @click="undo">撤销</button>
        <button class="btn btn-sm" @click="clearAll">清空</button>
        <span class="spacer" />
        <span class="hint">
          {{
            tool === 'wand'
              ? '魔棒：点击颜色相近的连续区域；可切加选/减选'
              : '滚轮缩放 · 右键/平移工具拖动画布 · Ctrl+Z 撤销'
          }}
        </span>
      </div>

      <div ref="wrapEl" class="canvas-wrap">
        <canvas
          ref="canvasEl"
          class="paint-canvas"
          :class="{ panning: tool === 'pan', wand: tool === 'wand' }"
          @pointerdown="onPointerDown"
          @pointermove="onPointerMove"
          @pointerup="onPointerUp"
          @pointercancel="onPointerUp"
          @pointerleave="onPointerLeave"
          @contextmenu.prevent
        />
        <div v-if="errorText" class="canvas-tip">{{ errorText }}</div>
        <div v-else-if="loading" class="canvas-tip">加载中…</div>
      </div>
    </div>

    <template #footer>
      <span class="hint">白色涂抹区域 = 要改；不涂 = 整图重绘</span>
      <span class="spacer" />
      <button class="btn btn-sm" @click="emit('close')">取消</button>
      <button class="btn btn-sm primary" :disabled="loading || !!errorText" @click="save">
        保存遮罩
      </button>
    </template>
  </Modal>
</template>

<style scoped>
.btn {
  transition:
    color var(--dur-fast) var(--ease),
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease);
}

.mask-editor {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
  padding: var(--gap-sm) var(--gap);
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}

.toolbar .btn.active {
  border-color: var(--primary);
  color: var(--primary);
}

.seg-wand {
  display: flex;
  gap: var(--gap-xs);
}

.size {
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
  font-size: var(--fs-xs);
  color: var(--muted);
}

.size input {
  width: 110px;
}

.size b {
  width: 28px;
  text-align: right;
  color: var(--text);
}

.spacer {
  flex: 1;
}

.hint {
  font-size: var(--fs-xs);
  color: var(--muted);
}

.canvas-wrap {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  background: var(--bg);
}

.paint-canvas {
  width: 100%;
  height: 100%;
  display: block;
  cursor: crosshair;
  touch-action: none;
}

.paint-canvas.panning {
  cursor: grab;
}

.paint-canvas.wand {
  cursor: cell;
}

.canvas-tip {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--muted);
  font-size: var(--fs-sm);
}

.btn.primary {
  border-color: var(--primary);
  background: var(--primary);
  color: white;
  transition:
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease);
}

.btn.primary:disabled {
  opacity: 0.4;
  cursor: default;
}
</style>
