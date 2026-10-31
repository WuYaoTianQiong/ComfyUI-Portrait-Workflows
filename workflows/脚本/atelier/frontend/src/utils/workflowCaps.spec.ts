import { describe, expect, it } from 'vitest'

import {
  DEFAULT_CAPS,
  detectCapsFromContent,
  detectParamsFromContent,
  qualityOptionsFor,
} from './workflowCaps'

function capsOf(obj: unknown) {
  return detectCapsFromContent(JSON.stringify(obj))
}

describe('工作流能力探测', () => {
  it('API 格式文生图：提示词 / 负向 / 画质 / 横竖都支持', () => {
    const caps = capsOf({
      1: { class_type: 'CLIPTextEncode', inputs: { clip: ['4', 1], text: '正' } },
      2: { class_type: 'CLIPTextEncode', inputs: { clip: ['4', 1], text: '负' } },
      3: { class_type: 'EmptyLatentImage', inputs: { width: 832, height: 1216 } },
    })
    expect(caps).toEqual({ prompt: true, negative: true, quality: true, orientation: true })
  })

  it('方图没有横竖可分', () => {
    const caps = capsOf({
      1: { class_type: 'CLIPTextEncode', inputs: { clip: ['4', 1], text: '正' } },
      2: { class_type: 'EmptyLatentImage', inputs: { width: 1024, height: 1024 } },
    })
    expect(caps.quality).toBe(true)
    expect(caps.orientation).toBe(false)
  })

  it('尺寸由上游预设节点决定：支持横竖，但没有可缩放的字面量尺寸', () => {
    const caps = capsOf({
      1: { class_type: 'CLIPTextEncode', inputs: { clip: ['4', 1], text: '正' } },
      2: { class_type: 'EmptyLatentImage', inputs: { width: ['9', 0], height: ['9', 1] } },
      9: { class_type: 'ResolutionPresetPicker', inputs: { preset: '640x960 （2:3）' } },
    })
    expect(caps.orientation).toBe(true)
    expect(caps.quality).toBe(false)
  })

  it('超分工作流：没有提示词注入，但有画质', () => {
    const caps = capsOf({
      1: { class_type: 'SeedVR2VideoUpscaler', inputs: { resolution: 2560 } },
    })
    expect(caps).toEqual({ prompt: false, negative: false, quality: true, orientation: false })
  })

  it('UI 格式按节点类型乐观判定', () => {
    const caps = capsOf({
      nodes: [{ type: 'CLIPTextEncode' }, { type: 'EmptyLatentImage' }],
    })
    expect(caps).toEqual({ prompt: true, negative: false, quality: true, orientation: true })
  })

  it('解析失败时保持旧行为（全部可用）', () => {
    expect(detectCapsFromContent('not json')).toEqual(DEFAULT_CAPS)
  })
})

describe('画质参数与真实档位', () => {
  const paramsOf = (obj: unknown) => detectParamsFromContent(JSON.stringify(obj))

  it('字面尺寸工作流：倍率缩放后的真实像素', () => {
    const params = paramsOf({
      1: { class_type: 'EmptyLatentImage', inputs: { width: 1128, height: 2008 } },
    })
    expect(params.quality_mode).toBe('scale')
    expect(params.base_width).toBe(1128)
    expect(params.base_height).toBe(2008)

    const options = qualityOptionsFor(params)
    expect(options.find((o) => o.value === '4K')?.label).toBe('1128×2008')
    expect(options.find((o) => o.value === '6K')?.label).toBe('1410×2510')
    expect(options.find((o) => o.value === '12K')?.label).toBe('2256×4016')
  })

  it('上游 megapixels 工作流：按面积换算 MP，并保留横竖旋钮', () => {
    const params = paramsOf({
      2: { class_type: 'EmptyLatentImage', inputs: { width: ['9', 0], height: ['9', 1] } },
      9: { class_type: 'ResolutionSelector', inputs: { aspect_ratio: '9:16', megapixels: 1 } },
    })
    expect(params.quality_mode).toBe('megapixels')
    expect(params.base_megapixels).toBe(1)
    expect(params.orientation_mode).toBe('knob')

    const options = qualityOptionsFor(params)
    expect(options.find((o) => o.value === '4K')?.label).toBe('1MP')
    expect(options.find((o) => o.value === '12K')?.label).toBe('4MP')
  })

  it('超分工作流：档位写真实输出分辨率', () => {
    const params = paramsOf({
      1: { class_type: 'SeedVR2VideoUpscaler', inputs: { resolution: 2560 } },
    })
    expect(params.quality_mode).toBe('seedvr')
    expect(qualityOptionsFor(params).find((o) => o.value === '4K')?.label).toBe(
      '4K · 2560×4096',
    )
  })

  it('没有尺寸旋钮的工作流不产生画质档位', () => {
    const params = paramsOf({ 1: { class_type: 'CLIPTextEncode', inputs: {} } })
    expect(params.quality_mode).toBe('none')
    expect(qualityOptionsFor(params)).toEqual([])
  })

  it('clamp 后结果相同的档位只保留一个', () => {
    const params = paramsOf({
      1: { class_type: 'EmptyLatentImage', inputs: { width: 4096, height: 4096 } },
    })
    const options = qualityOptionsFor(params)
    expect(options.map((o) => o.value)).toEqual(['2K', '4K'])
  })
})
