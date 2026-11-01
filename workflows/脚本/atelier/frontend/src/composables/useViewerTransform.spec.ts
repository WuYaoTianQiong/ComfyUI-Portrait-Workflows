import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { useViewerTransform } from './useViewerTransform'

function mountViewer() {
  const stage = document.createElement('div')
  const img = document.createElement('img')
  Object.defineProperty(stage, 'clientWidth', { value: 1000, configurable: true })
  Object.defineProperty(stage, 'clientHeight', { value: 800, configurable: true })
  Object.defineProperty(img, 'naturalWidth', { value: 1000, configurable: true })
  Object.defineProperty(img, 'naturalHeight', { value: 500, configurable: true })

  let changes = 0
  let viewer!: ReturnType<typeof useViewerTransform>
  const Test = defineComponent({
    setup() {
      const current = useViewerTransform({ onChange: () => changes++ })
      viewer = current
      current.stageEl.value = stage
      current.imgEl.value = img
      current.setNaturalSize(img)
      current.initView()
      return () => null
    },
  })
  const wrapper = mount(Test, { attachTo: document.body })
  return {
    viewer,
    wrapper,
    changes: () => changes,
  }
}

describe('useViewerTransform', () => {
  it('按窗口和图片尺寸计算适应比例，旋转后互换宽高', () => {
    const { viewer, wrapper, changes } = mountViewer()
    expect(viewer.zoomPercent.value).toBe(95)
    expect(viewer.fitMode.value).toBe(true)

    viewer.rotate90()
    expect(viewer.rotation.value).toBe(90)
    expect(viewer.zoomPercent.value).toBe(75)
    expect(changes()).toBe(1)

    viewer.reset()
    expect(viewer.rotation.value).toBe(0)
    expect(viewer.flipped.value).toBe(false)
    expect(viewer.zoomPercent.value).toBe(100)
    expect(viewer.natural.value).toEqual({ w: 0, h: 0 })
    wrapper.unmount()
  })

  it('缩放上下限', () => {
    const { viewer, wrapper } = mountViewer()
    expect(viewer.clampScale(1e9)).toBe(20)
    expect(viewer.clampScale(0)).toBe(0.05)
    wrapper.unmount()
  })

  it('点击 stage 空白触发关闭，拖拽过则不触发', () => {
    let closed = 0
    const stage = document.createElement('div')
    const img = document.createElement('img')
    Object.defineProperty(stage, 'clientWidth', { value: 1000, configurable: true })
    Object.defineProperty(stage, 'clientHeight', { value: 800, configurable: true })
    Object.defineProperty(img, 'naturalWidth', { value: 100, configurable: true })
    Object.defineProperty(img, 'naturalHeight', { value: 100, configurable: true })
    let viewer!: ReturnType<typeof useViewerTransform>
    const Test = defineComponent({
      setup() {
        const current = useViewerTransform({ onStageClick: () => closed++ })
        viewer = current
        current.stageEl.value = stage
        current.imgEl.value = img
        current.setNaturalSize(img)
        current.initView()
        return () => null
      },
    })
    const wrapper = mount(Test, { attachTo: document.body })

    viewer.onStageClick({ target: stage } as unknown as MouseEvent)
    expect(closed).toBe(1)

    viewer.onPanStart({
      button: 0,
      clientX: 10,
      clientY: 10,
      preventDefault: () => undefined,
    } as unknown as MouseEvent)
    window.dispatchEvent(new MouseEvent('mousemove', { clientX: 30, clientY: 30 }))
    window.dispatchEvent(new MouseEvent('mouseup'))
    viewer.onStageClick({ target: stage } as unknown as MouseEvent)
    expect(closed).toBe(1)
    wrapper.unmount()  })
})
