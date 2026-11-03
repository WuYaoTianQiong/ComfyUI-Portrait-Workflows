import { ref } from 'vue'
import { describe, expect, it } from 'vitest'

import {
  detectCapsFromContent,
  detectParamsFromContent,
  useWorkflowCaps,
} from './useWorkflowCaps'
import type { WorkflowCaps, WorkflowParams } from './useWorkflowCaps'
import type { WorkflowRow } from './useWorkflows'

/**
 * 档位是模块私有的（`qualityOptionsFor` 不再对外），只能通过 composable 观测：
 * 给一行"后端已经给出 caps/params"的工作流，取它算出来的档位。
 */
const ALL_CAPS: WorkflowCaps = {
  prompt: true,
  negative: true,
  negative_effective: true,
  negative_cfg: null,
  quality: true,
  orientation: true,
}

function optionsFor(params: WorkflowParams, ratio = '') {
  const path = 'wf/a.json'
  const rows = ref<WorkflowRow[]>([{ path, name: 'a', caps: ALL_CAPS, params }])
  const { qualityOptions } = useWorkflowCaps(ref(path), rows, ref(ratio))
  return qualityOptions.value
}

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
    expect(caps).toEqual({
      prompt: true,
      negative: true,
      negative_effective: false,
      negative_cfg: null,
      quality: true,
      orientation: true,
    })
  })

  it('方图也能在统一比例契约下切到非方图', () => {
    const caps = capsOf({
      1: { class_type: 'CLIPTextEncode', inputs: { clip: ['4', 1], text: '正' } },
      2: { class_type: 'EmptyLatentImage', inputs: { width: 1024, height: 1024 } },
    })
    expect(caps.quality).toBe(true)
    expect(caps.orientation).toBe(true)
  })

  it('尺寸由上游预设节点决定：预设档位可作为画质/比例注入', () => {
    const caps = capsOf({
      1: { class_type: 'CLIPTextEncode', inputs: { clip: ['4', 1], text: '正' } },
      2: { class_type: 'EmptyLatentImage', inputs: { width: ['9', 0], height: ['9', 1] } },
      9: { class_type: 'ResolutionPresetPicker', inputs: { preset: '640x960 （2:3）' } },
    })
    expect(caps.orientation).toBe(true)
    expect(caps.quality).toBe(true)
  })

  it('超分工作流：没有提示词注入，但有画质', () => {
    const caps = capsOf({
      1: { class_type: 'SeedVR2VideoUpscaler', inputs: { resolution: 2560 } },
    })
    expect(caps).toEqual({
      prompt: false,
      negative: false,
      negative_effective: false,
      negative_cfg: null,
      quality: true,
      orientation: false,
    })
  })

  it('UI 格式按节点类型乐观判定', () => {
    const caps = capsOf({
      nodes: [{ type: 'CLIPTextEncode' }, { type: 'EmptyLatentImage' }],
    })
    expect(caps).toEqual({
      prompt: true,
      negative: false,
      negative_effective: false,
      negative_cfg: null,
      quality: true,
      orientation: true,
    })
  })

  it('解析失败时保持旧行为（全部可用）', () => {
    expect(detectCapsFromContent('not json')).toEqual(ALL_CAPS)
  })
})

describe('负向是否真的生效', () => {
  it('Qwen：负向字段存在，但 CFG=1 时不参与采样', () => {
    const caps = capsOf({
      5: {
        class_type: 'TextEncodeQwenImage21',
        inputs: { clip: ['2', 0], prompt: '正', negative_prompt: '负' },
      },
      7: {
        class_type: 'KSampler',
        inputs: {
          model: ['4', 0], positive: ['5', 0], negative: ['5', 1],
          latent_image: ['6', 0], cfg: 1,
        },
      },
    })
    expect(caps.negative).toBe(true)
    expect(caps.negative_effective).toBe(false)
    expect(caps.negative_cfg).toBe(1)
  })

  it('ZIT：第一程 CFG=3 且负向接文本节点，第二程 CFG=1 不影响结论', () => {
    const caps = capsOf({
      7: { class_type: 'CLIPTextEncode', inputs: { clip: ['2', 0], text: '正' } },
      8: { class_type: 'CLIPTextEncode', inputs: { clip: ['2', 0], text: '负' } },
      9: {
        class_type: 'KSamplerAdvanced',
        inputs: { positive: ['7', 0], negative: ['8', 0], cfg: 3 },
      },
      11: {
        class_type: 'KSamplerAdvanced',
        inputs: { positive: ['7', 0], negative: ['8', 0], cfg: 1 },
      },
    })
    expect(caps.negative_effective).toBe(true)
    expect(caps.negative_cfg).toBe(3)
  })

  it('Flux：两个文本节点，但负向被 ConditioningZeroOut 清零', () => {
    const caps = capsOf({
      4: { class_type: 'CLIPTextEncode', inputs: { clip: ['2', 0], text: '正' } },
      5: { class_type: 'CLIPTextEncode', inputs: { clip: ['2', 0], text: '负' } },
      6: { class_type: 'ConditioningZeroOut', inputs: { conditioning: ['5', 0] } },
      11: {
        class_type: 'CFGGuider',
        inputs: { positive: ['4', 0], negative: ['6', 0], cfg: 1 },
      },
    })
    expect(caps.negative).toBe(true)
    expect(caps.negative_effective).toBe(false)
    expect(caps.negative_cfg).toBeNull()
  })

  it('Krea2/Porn：单文本节点 + 清零，没有负向通道', () => {
    const caps = capsOf({
      6: { class_type: 'CLIPTextEncode', inputs: { clip: ['2', 0], text: '正' } },
      8: { class_type: 'ConditioningZeroOut', inputs: { conditioning: ['6', 0] } },
      9: {
        class_type: 'KSamplerAdvanced',
        inputs: { positive: ['6', 0], negative: ['8', 0], cfg: 1 },
      },
    })
    expect(caps.negative).toBe(false)
    expect(caps.negative_effective).toBe(false)
    expect(caps.negative_cfg).toBeNull()
  })
})

describe('画质参数与真实档位', () => {
  const paramsOf = (obj: unknown) => detectParamsFromContent(JSON.stringify(obj))

  it('字面尺寸工作流：默认比例 + 1.0× 保持原生尺寸', () => {
    const params = paramsOf({
      1: { class_type: 'EmptyLatentImage', inputs: { width: 832, height: 1216 } },
    })
    expect(params.default_ratio).toBe('2:3')
    expect(params.aspect_ratios).toEqual([
      '1:1', '2:3', '3:2', '3:4', '4:3', '9:16', '16:9', '21:9', '9:21',
    ])
    expect(optionsFor(params).find((o) => o.value === '4K')?.label)
      .toBe('原生 1.0× · 1.01MP · 832×1216')
    expect(optionsFor(params, '9:16').find((o) => o.value === '4K')?.label)
      .toBe('1.0× · 1.01MP · 752×1344')
  })

  it('字面尺寸工作流：倍率缩放后的真实像素', () => {
    const params = paramsOf({
      1: { class_type: 'EmptyLatentImage', inputs: { width: 1128, height: 2008 } },
    })
    expect(params.quality_mode).toBe('scale')
    expect(params.base_width).toBe(1128)
    expect(params.base_height).toBe(2008)

    const options = optionsFor(params)
    expect(options.find((o) => o.value === '4K')?.label).toBe('原生 1.0× · 2.27MP · 1128×2008')
    expect(options.find((o) => o.value === '6K')?.label).toBe('1.25× · 3.54MP · 1408×2512')
    expect(options.find((o) => o.value === '12K')?.label).toBe('2.0× · 9.06MP · 2256×4016')
  })

  it('上游 megapixels 工作流：按 MiP 换算，并保留横竖旋钮', () => {
    const params = paramsOf({
      2: { class_type: 'EmptyLatentImage', inputs: { width: ['9', 0], height: ['9', 1] } },
      9: { class_type: 'ResolutionSelector', inputs: { aspect_ratio: '9:16', megapixels: 1 } },
    })
    expect(params.quality_mode).toBe('megapixels')
    expect(params.base_megapixels).toBe(1)
    expect(params.mp_unit).toBe('mip')
    expect(params.orientation_mode).toBe('knob')

    const options = optionsFor(params)
    expect(options.find((o) => o.value === '4K')?.label).toBe('原生 1.0× · 1.05MP · 768×1368')
    expect(options.find((o) => o.value === '12K')?.label).toBe('2.0× · 4.19MP · 1536×2728')
  })

  it('后置 LatentUpscaleBy：标签写出成品尺寸', () => {
    const zit = optionsFor({
      quality_mode: 'scale',
      orientation_mode: 'knob',
      base_width: 640,
      base_height: 960,
      base_megapixels: 0.614,
      mp_unit: 'mp',
      post_scale: 1.7,
      default_ratio: '2:3',
      aspect_ratios: ['1:1', '2:3', '3:2', '3:4', '4:3', '9:16', '16:9', '21:9', '9:21'],
      multiple: 16,
    })
    expect(zit.find((o) => o.value === '4K')?.label)
      .toBe('原生 1.0× · 0.61MP · 640×960 → 成品 1088×1632')
    expect(zit.find((o) => o.value === '6K')?.label)
      .toBe('1.25× · 0.96MP · 800×1200 → 成品 1360×2040')
  })

  it('工作流声明的档位会过滤掉低档', () => {
    const params = paramsOf({
      1: { class_type: 'EmptyLatentImage', inputs: { width: 832, height: 1216 } },
    })
    params.quality_tiers = ['6K', '8K', '12K']
    expect(optionsFor(params).map((o) => o.value)).toEqual(['6K', '8K', '12K'])
  })

  it('超分工作流：档位写真实输出分辨率', () => {
    const params = paramsOf({
      1: { class_type: 'SeedVR2VideoUpscaler', inputs: { resolution: 2560 } },
    })
    expect(params.quality_mode).toBe('seedvr')
    expect(optionsFor(params).find((o) => o.value === '4K')?.label).toBe(
      '2560×4096',
    )
  })

  it('没有尺寸旋钮的工作流不产生画质档位', () => {
    const params = paramsOf({ 1: { class_type: 'CLIPTextEncode', inputs: {} } })
    expect(params.quality_mode).toBe('none')
    expect(optionsFor(params)).toEqual([])
  })

  it('每个倍率按目标 MP 重新算尺寸，标签保持唯一', () => {
    const params = paramsOf({
      1: { class_type: 'EmptyLatentImage', inputs: { width: 4096, height: 4096 } },
    })
    const options = optionsFor(params)
    expect(options.map((o) => o.value)).toEqual(['2K', '4K', '6K', '8K', '12K'])
    expect(new Set(options.map((o) => o.label)).size).toBe(options.length)
  })
})
