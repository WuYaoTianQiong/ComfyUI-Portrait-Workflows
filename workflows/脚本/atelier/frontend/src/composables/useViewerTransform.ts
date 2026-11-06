import { onBeforeUnmount, ref } from 'vue'

export interface ViewerCallbacks {
  /** 视图稳定后（动画结束、旋转/翻转、拖拽结束）调用，用于持久化快照。 */
  onChange?: () => void
  /** 开始拖拽时调用（灯箱用它把信息卡变淡）。 */
  onPanStart?: () => void
  /** 点击 stage 空白处；灯箱用它关闭。 */
  onStageClick?: () => void
  /** 「适应窗口」时四周预留的总边距（px），默认 48；对比弹层用更小的值。 */
  fitPadding?: number
}

interface ViewState {
  scale: number
  /** 图片中心在 stage 坐标系里的位置 */
  cx: number
  cy: number
  targetScale: number
  targetCx: number
  targetCy: number
  rafId: number | null
}

/**
 * 灯箱的缩放 / 平移 / 旋转 / 翻转 / 适应窗口。
 *
 * 用普通对象保存视图状态：动画每帧直接改 DOM style，不走响应式，
 * 避免 60fps 触发整棵组件树重渲染。只有缩放百分比和 imgLoaded 需要响应式。
 */
export function useViewerTransform(options: ViewerCallbacks = {}) {
  const MIN_SCALE = 0.05
  const MAX_SCALE = 20

  const stageEl = ref<HTMLElement | null>(null)
  const imgEl = ref<HTMLImageElement | null>(null)
  const stageSize = ref({ w: 0, h: 0 })
  /** 图片的自然像素尺寸（scale=1 时的基准）。 */
  const natural = ref({ w: 0, h: 0 })
  const imgLoaded = ref(false)
  /** 旋转角度（0 / 90 / 180 / 270）。 */
  const rotation = ref(0)
  const flipped = ref(false)
  /** true = 适应窗口；false = 手动缩放（1:1 按钮显示为激活）。 */
  const fitMode = ref(true)
  const zoomPercent = ref(100)

  const view: ViewState = {
    scale: 1,
    cx: 0,
    cy: 0,
    targetScale: 1,
    targetCx: 0,
    targetCy: 0,
    rafId: null,
  }

  const panning = ref(false)
  let panStart = { x: 0, y: 0, cx: 0, cy: 0 }
  /** 本次按下后是否真的拖动过：拖动过就不把 mouseup 当"点击空白"。 */
  let dragged = false

  /** 旋转 90/270 时有效宽高互换。 */
  function effectiveSize() {
    const { w, h } = natural.value
    return rotation.value % 180 === 0 ? { w, h } : { w: h, h: w }
  }

  /** "适应窗口"时的显示比例。 */
  function computeFit(): number {
    const el = stageEl.value
    const eff = effectiveSize()
    if (!el || !eff.w || !eff.h) return 1
    const pad = options.fitPadding ?? 48
    const availW = Math.max(80, el.clientWidth - pad)
    const availH = Math.max(80, el.clientHeight - pad)
    return Math.min(availW / eff.w, availH / eff.h)
  }

  /**
   * 平移边界：至少保留 15%（最小 20px）的图片在视口内，整张图不会拖丢。
   * 参数是图片中心坐标，所以边界公式是旧版 top-left 公式的等价变形。
   */
  function constrainPoint(scale: number, cx: number, cy: number) {
    const el = stageEl.value
    const eff = effectiveSize()
    if (!el || !eff.w || !eff.h) return { cx, cy }
    const cw = el.clientWidth
    const ch = el.clientHeight
    const bw = eff.w * scale
    const bh = eff.h * scale
    const keepW = Math.max(Math.min(bw, cw) * 0.15, 20)
    const keepH = Math.max(Math.min(bh, ch) * 0.15, 20)
    return {
      cx: Math.min(cw - keepW + bw / 2, Math.max(keepW - bw / 2, cx)),
      cy: Math.min(ch - keepH + bh / 2, Math.max(keepH - bh / 2, cy)),
    }
  }

  function constrainView() {
    const c = constrainPoint(view.scale, view.cx, view.cy)
    view.cx = c.cx
    view.cy = c.cy
  }

  /**
   * 应用变换。transform-origin 固定在图片中心，所以 translate 给的是
   * 「图片中心在 stage 里的坐标减去半宽/半高」；旋转与翻转都围绕中心，
   * 90° 时不会偏到角落。
   */
  function applyView() {
    const el = imgEl.value
    const { w, h } = natural.value
    if (!el || !w || !h) return
    const s = view.scale
    el.style.width = `${w}px`
    el.style.height = `${h}px`
    el.style.transform =
      `translate(${view.cx - w / 2}px, ${view.cy - h / 2}px) ` +
      `rotate(${rotation.value}deg) scale(${flipped.value ? -s : s}, ${s})`
    zoomPercent.value = Math.round(s * 100)
  }

  function cancelAnim() {
    if (view.rafId !== null) {
      cancelAnimationFrame(view.rafId)
      view.rafId = null
    }
  }

  /** 与旧版一致：0.35 的线性插值追帧，滚轮不会一格一格跳。 */
  function animate() {
    if (view.rafId !== null) return
    const LERP = 0.35
    const tick = () => {
      view.rafId = null
      const ds = view.targetScale - view.scale
      const dx = view.targetCx - view.cx
      const dy = view.targetCy - view.cy
      if (Math.abs(ds) < 0.0001 && Math.abs(dx) < 0.1 && Math.abs(dy) < 0.1) {
        view.scale = view.targetScale
        view.cx = view.targetCx
        view.cy = view.targetCy
        constrainView()
        applyView()
        options.onChange?.()
        return
      }
      view.scale += ds * LERP
      view.cx += dx * LERP
      view.cy += dy * LERP
      constrainView()
      applyView()
      view.rafId = requestAnimationFrame(tick)
    }
    view.rafId = requestAnimationFrame(tick)
  }

  function animateTo(scale: number, cx: number, cy: number) {
    const c = constrainPoint(scale, cx, cy)
    view.targetScale = scale
    view.targetCx = c.cx
    view.targetCy = c.cy
    animate()
  }

  function initView() {
    cancelAnim()
    const fit = computeFit()
    view.scale = view.targetScale = fit
    view.cx = view.targetCx = stageSize.value.w / 2
    view.cy = view.targetCy = stageSize.value.h / 2
    constrainView()
    applyView()
  }

  function syncStageSize() {
    const el = stageEl.value
    if (!el) return
    stageSize.value = { w: el.clientWidth, h: el.clientHeight }
  }

  function setNaturalSize(img: HTMLImageElement) {
    natural.value = { w: img.naturalWidth, h: img.naturalHeight }
    imgLoaded.value = true
    syncStageSize()
  }

  function clampScale(scale: number): number {
    return Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale))
  }

  /** 以 stage 内某个点为锚点缩放；不传锚点则围绕画面中心。 */
  function zoomTo(scale: number, anchorX?: number, anchorY?: number) {
    if (!natural.value.w) return
    const ax = anchorX ?? stageSize.value.w / 2
    const ay = anchorY ?? stageSize.value.h / 2
    const cur = view.scale || 1
    const next = clampScale(scale)
    const ix = (ax - view.cx) / cur
    const iy = (ay - view.cy) / cur
    fitMode.value = false
    animateTo(next, ax - ix * next, ay - iy * next)
  }

  function zoomBy(factor: number) {
    zoomTo(view.scale * factor)
  }

  function onWheel(event: WheelEvent) {
    const el = stageEl.value
    if (!el) return
    const rect = el.getBoundingClientRect()
    zoomTo(
      view.scale * Math.exp(-event.deltaY * 0.002),
      event.clientX - rect.left,
      event.clientY - rect.top,
    )
  }

  function toggleFit() {
    if (fitMode.value) {
      fitMode.value = false
      animateTo(1, stageSize.value.w / 2, stageSize.value.h / 2)
    } else {
      fitMode.value = true
      animateTo(computeFit(), stageSize.value.w / 2, stageSize.value.h / 2)
    }
  }

  function resetView() {
    rotation.value = 0
    flipped.value = false
    fitMode.value = true
    animateTo(computeFit(), stageSize.value.w / 2, stageSize.value.h / 2)
  }

  /** 旋转后按旋转后的有效宽高重算适应比例（旧版同样会重置到适应）。 */
  function rotate90() {
    rotation.value = (rotation.value + 90) % 360
    fitMode.value = true
    initView()
    options.onChange?.()
  }

  function flip() {
    flipped.value = !flipped.value
    applyView()
    options.onChange?.()
  }

  function onPanStart(event: MouseEvent) {
    if (event.button !== 0) return
    options.onPanStart?.()
    cancelAnim()
    // 停掉动画后目标必须跟当前一致，否则松手瞬间会继续追旧目标。
    view.targetScale = view.scale
    view.targetCx = view.cx
    view.targetCy = view.cy
    panStart = { x: event.clientX, y: event.clientY, cx: view.cx, cy: view.cy }
    dragged = false
    panning.value = true
    window.addEventListener('mousemove', onPanMove)
    window.addEventListener('mouseup', onPanEnd)
    event.preventDefault()
  }

  function onPanMove(event: MouseEvent) {
    if (!panning.value) return
    const dx = event.clientX - panStart.x
    const dy = event.clientY - panStart.y
    if (Math.abs(dx) + Math.abs(dy) > 4) dragged = true
    view.cx = panStart.cx + dx
    view.cy = panStart.cy + dy
    view.targetCx = view.cx
    view.targetCy = view.cy
    constrainView()
    applyView()
  }

  function onPanEnd() {
    if (!panning.value) return
    panning.value = false
    window.removeEventListener('mousemove', onPanMove)
    window.removeEventListener('mouseup', onPanEnd)
    options.onChange?.()
  }

  /** 只有点在 stage 本身的空白处才关闭；点图片 / 拖动都不关闭。 */
  function onStageClick(event: MouseEvent) {
    if (event.target !== stageEl.value) return
    if (dragged) return
    options.onStageClick?.()
  }

  /**
   * 从图片拖到信息卡再松手时，mousedown / mouseup 的目标不同，
   * 浏览器会把 click 派发到两者共同的祖先 —— 刚拖完不能算「点击空白」。
   */
  function onRootClick() {
    if (dragged) {
      dragged = false
      return
    }
    options.onStageClick?.()
  }

  /** 换图 / 关闭时清空视图状态（不影响 info/prompt 等外部状态）。 */
  function reset() {
    cancelAnim()
    natural.value = { w: 0, h: 0 }
    imgLoaded.value = false
    rotation.value = 0
    flipped.value = false
    fitMode.value = true
    zoomPercent.value = 100
  }

  onBeforeUnmount(() => {
    onPanEnd()
    cancelAnim()
  })

  return {
    stageEl,
    imgEl,
    stageSize,
    natural,
    imgLoaded,
    rotation,
    flipped,
    fitMode,
    zoomPercent,
    panning,
    view,
    computeFit,
    constrainView,
    applyView,
    cancelAnim,
    animateTo,
    initView,
    syncStageSize,
    setNaturalSize,
    zoomTo,
    zoomBy,
    clampScale,
    onWheel,
    toggleFit,
    resetView,
    rotate90,
    flip,
    onPanStart,
    onPanEnd,
    onStageClick,
    onRootClick,
    reset,
  }
}
