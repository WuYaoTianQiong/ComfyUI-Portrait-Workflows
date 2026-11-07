import { ref } from 'vue'
import { describe, expect, it } from 'vitest'

import { useWorkflowCaps } from './useWorkflowCaps'
import type {
  SizePreview,
  WorkflowCaps,
  WorkflowParams,
} from './useWorkflowCaps'
import type { WorkflowRow } from './useWorkflows'

/**
 * 尺寸计算已经搬到后端；这里只验证「后端预演 → 界面文案」的格式化，
 * 以及档位过滤 / 去重 / 缺省回退。预览与实际注入的一致性由
 * `tests/test_workflow_inspect.py` 逐档逐比例断言。
 */
const ALL_CAPS: WorkflowCaps = {
  prompt: true,
  negative: true,
  negative_effective: true,
  negative_cfg: null,
  quality: true,
  orientation: true,
}

const SCALE_PARAMS: WorkflowParams = {
  quality_mode: 'scale',
  orientation_mode: 'swap',
  base_width: 832,
  base_height: 1216,
  base_megapixels: 1.01,
  mp_unit: 'mp',
  post_scale: 1,
  default_ratio: '2:3',
  aspect_ratios: ['1:1', '2:3', '9:16'],
  multiple: 16,
}

const SCALE_PREVIEW: SizePreview = {
  '1.0x': {
    '2:3': {
      width: 832, height: 1216, final_width: 832, final_height: 1216,
      megapixels: 1.01, scale: 1, native: true,
    },
    '9:16': {
      width: 752, height: 1344, final_width: 752, final_height: 1344,
      megapixels: 1.01, scale: 1, native: false,
    },
  },
  '1.25x': {
    '2:3': {
      width: 1056, height: 1536, final_width: 1056, final_height: 1536,
      megapixels: 1.62, scale: 1.25, native: false,
    },
  },
}

function optionsFor(
  params: WorkflowParams,
  preview?: SizePreview,
  ratio = '',
) {
  const path = 'wf/a.json'
  const rows = ref<WorkflowRow[]>([
    { path, name: 'a', caps: ALL_CAPS, params, size_preview: preview },
  ])
  const { qualityOptions } = useWorkflowCaps(ref(path), rows, ref(ratio))
  return qualityOptions.value
}

describe('档位文案来自后端预演', () => {
  it('原生档 + 非原生比例 + 倍率档', () => {
    const options = optionsFor(SCALE_PARAMS, SCALE_PREVIEW)
    expect(options.find((o) => o.value === '1.0x')?.label)
      .toBe('原生 1.0× · 1.01MP · 832×1216')
    expect(optionsFor(SCALE_PARAMS, SCALE_PREVIEW, '9:16').find((o) => o.value === '1.0x')?.label)
      .toBe('1.0× · 1.01MP · 752×1344')
    expect(options.find((o) => o.value === '1.25x')?.label)
      .toBe('1.25× · 1.62MP · 1056×1536')
  })

  it('后置放大时标签写出成品尺寸', () => {
    const preview: SizePreview = {
      '1.0x': {
        '2:3': {
          width: 640, height: 960, final_width: 1088, final_height: 1632,
          megapixels: 0.61, scale: 1, native: true,
        },
      },
    }
    const options = optionsFor(
      { ...SCALE_PARAMS, post_scale: 1.7, base_width: 640, base_height: 960 },
      preview,
    )
    expect(options.find((o) => o.value === '1.0x')?.label)
      .toBe('原生 1.0× · 0.61MP · 640×960 → 成品 1088×1632')
  })

  it('只有像素总量的档位不写宽高', () => {
    const preview: SizePreview = {
      '1.0x': { '*': { megapixels: 1.05, scale: 1, native: true } },
    }
    const options = optionsFor(
      { quality_mode: 'megapixels', orientation_mode: 'knob', default_ratio: '9:16' },
      preview,
    )
    expect(options.find((o) => o.value === '1.0x')?.label).toBe('原生 1.0× · 1.05MP')
  })

  it('SeedVR 用真实输出分辨率，比例无关', () => {
    const preview: SizePreview = {
      '1.0x': { '*': { width: 2560, height: 4096, final_width: 2560, final_height: 4096, scale: 1 } },
    }
    const options = optionsFor(
      { quality_mode: 'seedvr', orientation_mode: 'none' },
      preview,
    )
    expect(options.find((o) => o.value === '1.0x')?.label).toBe('2560×4096')
  })
})

describe('档位过滤与回退', () => {
  it('工作流声明的档位会过滤掉低档', () => {
    const options = optionsFor(
      { ...SCALE_PARAMS, quality_tiers: ['1.25x', '1.5x', '2.0x'] },
      SCALE_PREVIEW,
    )
    expect(options.map((o) => o.value)).toEqual(['1.25x', '1.5x', '2.0x'])
  })

  it('没有尺寸旋钮的工作流不产生档位', () => {
    expect(optionsFor({ quality_mode: 'none', orientation_mode: 'none' })).toEqual([])
  })

  it('预演尚未返回时只写倍率，不隐藏控件', () => {
    const options = optionsFor(SCALE_PARAMS)
    expect(options.find((o) => o.value === '1.0x')?.label).toBe('原生 1.0×')
    expect(options.find((o) => o.value === '1.25x')?.label).toBe('1.25×')
  })

  it('相同文案只保留一档', () => {
    const preview: SizePreview = {
      '1.5x': { '2:3': { width: 2048, height: 2048, megapixels: 4.19, scale: 1.5 } },
      '2.0x': { '2:3': { width: 2048, height: 2048, megapixels: 4.19, scale: 2 } },
    }
    const options = optionsFor(SCALE_PARAMS, preview)
    const labels = options.map((o) => o.label)
    expect(new Set(labels).size).toBe(labels.length)
  })
})
