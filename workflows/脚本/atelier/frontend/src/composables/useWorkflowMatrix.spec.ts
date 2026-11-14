import { describe, expect, it } from 'vitest'

import type { WorkflowRow } from '../api/workflows'
import {
  MATRIX_REF_SIZE,
  buildMatrixPlan,
  nearestTier,
  previewSize,
  resolveTier,
  seedForCell,
} from './useWorkflowMatrix'

/**
 * 夹具取自 2026-11-12 `/api/workflows` 的真实返回（节选 2:3 与 9:16）。
 * 关键事实：同一「2:3 × 1.0x」各流尺寸不同，Qwen21 根本没有 1.0x 档。
 */
function wf(
  path: string,
  sizes: Record<string, Record<string, [number, number]>>,
  extra: Partial<WorkflowRow> = {},
): WorkflowRow {
  const size_preview: WorkflowRow['size_preview'] = {}
  for (const [tier, ratios] of Object.entries(sizes)) {
    size_preview[tier] = {}
    for (const [ratio, [w, h]] of Object.entries(ratios)) {
      size_preview[tier][ratio] = { width: w, height: h }
    }
  }
  return {
    path,
    name: `${path}.json`,
    size_preview,
    caps: {
      prompt: true,
      negative: false,
      negative_effective: false,
      negative_cfg: null,
      quality: true,
      orientation: true,
    },
    params: { quality_mode: 'scale', orientation_mode: 'swap' },
    ...extra,
  }
}

const MOSS = wf('moss', {
  '0.5x': { '2:3': [512, 768], '9:16': [464, 832] },
  '1.0x': { '2:3': [1024, 1536], '9:16': [944, 1680] },
  '1.25x': { '2:3': [1280, 1920], '9:16': [1168, 2096] },
})
const MOODY = wf('moody', {
  '0.75x': { '2:3': [920, 1384] },
  '1.0x': { '2:3': [1232, 1840], '9:16': [1128, 2008] },
  '1.25x': { '2:3': [1536, 2304] },
})
const QWEN = wf(
  'qwen',
  {
    '1.25x': { '2:3': [1600, 2400], '9:16': [1472, 2608] },
    '1.5x': { '2:3': [1920, 2880] },
    '2.0x': { '2:3': [2560, 3840] },
  },
  {
    params: {
      quality_mode: 'scale',
      orientation_mode: 'swap',
      quality_tiers: ['1.25x', '1.5x', '2.0x'],
      default_quality: '1.25x',
    },
    caps: {
      prompt: true,
      negative: true,
      negative_effective: false,
      negative_cfg: 1,
      quality: true,
      orientation: true,
    },
  },
)
const EDIT = wf('edit', { '1.0x': { '2:3': [1024, 1536] } }, {
  caps: {
    prompt: false,
    negative: false,
    negative_effective: false,
    negative_cfg: null,
    quality: true,
    orientation: true,
  },
})

const ALL = [MOSS, MOODY, QWEN, EDIT]

function plan(overrides: Partial<Parameters<typeof buildMatrixPlan>[0]> = {}) {
  return buildMatrixPlan({
    workflows: ALL,
    paths: ['moss', 'moody', 'qwen'],
    ratio: '2:3',
    tier: '1.0x',
    align: 'native',
    count: 2,
    ...overrides,
  })
}

describe('resolveTier / previewSize', () => {
  it('档位可用时原样返回', () => {
    expect(resolveTier(MOSS, '1.0x')).toEqual({ tier: '1.0x', fallback: false })
  })

  it('Qwen21 没有 1.0x，回退到工作流默认档 1.25x', () => {
    expect(resolveTier(QWEN, '1.0x')).toEqual({ tier: '1.25x', fallback: true })
  })

  it('没有默认档时按倍率最接近挑', () => {
    const noDefault = wf('x', { '0.5x': { '2:3': [512, 768] }, '2.0x': { '2:3': [2048, 3072] } }, {
      params: { quality_mode: 'scale', orientation_mode: 'swap', quality_tiers: ['0.5x', '2.0x'] },
    })
    expect(resolveTier(noDefault, '0.75x').tier).toBe('0.5x')
  })

  it('尺寸读后端预演，不自己算像素', () => {
    expect(previewSize(MOODY, '1.0x', '2:3')).toEqual([1232, 1840])
    expect(previewSize(MOSS, '1.0x', '3:4')).toBeNull()
  })

  it('final_* 优先于 width/height', () => {
    const scaled = wf('s', {})
    scaled.size_preview = { '1.0x': { '2:3': { width: 512, height: 768, final_width: 1024, final_height: 1536 } } }
    expect(previewSize(scaled, '1.0x', '2:3')).toEqual([1024, 1536])
  })
})

describe('nearestTier', () => {
  it('按像素量对数距离挑最接近档', () => {
    expect(nearestTier(MOODY, '2:3', MATRIX_REF_SIZE)?.tier).toBe('0.75x')
  })

  it('最低档已经过大时只能返回该档（Qwen21 无法降到 1024×1536）', () => {
    const near = nearestTier(QWEN, '2:3', MATRIX_REF_SIZE)
    expect(near?.tier).toBe('1.25x')
    expect(near?.size).toEqual([1600, 2400])
  })

  it('该比例没有任何预演时返回 null', () => {
    expect(nearestTier(MOSS, '21:9', MATRIX_REF_SIZE)).toBeNull()
  })
})

describe('buildMatrixPlan 原生档', () => {
  it('逐行给出真实尺寸，并指出尺寸不一致', () => {
    const p = plan()
    expect(p.usable.map((r) => `${r.width}×${r.height}`)).toEqual([
      '1024×1536',
      '1232×1840',
      '1600×2400',
    ])
    expect(p.warnings.some((w) => w.text.includes('原生尺寸不同'))).toBe(true)
  })

  it('Qwen21 的档位回退必须显式告知', () => {
    const p = plan()
    const qwen = p.usable.find((r) => r.path === 'qwen')
    expect(qwen?.tier).toBe('1.25x')
    expect(qwen?.tierFallback).toBe(true)
    expect(p.warnings.some((w) => w.text.includes('不支持 1.0x'))).toBe(true)
  })

  it('不注入提示词的工作流被排除并说明原因', () => {
    const p = plan({ paths: ['moss', 'edit'] })
    expect(p.usable.map((r) => r.path)).toEqual(['moss'])
    expect(p.rows.find((r) => r.path === 'edit')?.supported).toBe(false)
    expect(p.warnings.some((w) => w.text.includes('不注入提示词'))).toBe(true)
  })

  it('有图片输入槽的编辑 / 参考 / 超分类被排除（它们也注入提示词，但必须喂图）', () => {
    const inpaint = wf('inpaint', { '1.0x': { '2:3': [1024, 1536] } }, { image_slots: 1 })
    const p = buildMatrixPlan({
      workflows: [MOSS, inpaint],
      paths: ['moss', 'inpaint'],
      ratio: '2:3',
      tier: '1.0x',
      align: 'native',
      count: 1,
    })
    expect(p.usable.map((r) => r.path)).toEqual(['moss'])
    expect(p.rows.find((r) => r.path === 'inpaint')?.reason).toContain('需要 1 张输入图')
  })

  it('负向全不生效时给出提示', () => {
    const p = plan()
    expect(p.negativeEffective).toBe(0)
    expect(p.warnings.some((w) => w.text.includes('负向提示词 0 / 3 生效'))).toBe(true)
  })

  it('总数 = 可用行 × 张数', () => {
    expect(plan().total).toBe(6)
    expect(plan({ count: 4 }).total).toBe(12)
  })

  it('张数被夹在 1..4', () => {
    expect(plan({ count: 0 }).count).toBe(1)
    expect(plan({ count: 9 }).count).toBe(4)
  })

  it('超过软上限提示分批', () => {
    const p = plan({ paths: ['moss', 'moody', 'qwen'], count: 4 })
    expect(p.total).toBe(12)
    expect(p.warnings.some((w) => w.text.includes('建议分批'))).toBe(false)
    const many = Array.from({ length: 4 }, (_, i) => wf(`w${i}`, { '1.0x': { '2:3': [1024, 1536] } }))
    const p2 = buildMatrixPlan({
      workflows: many,
      paths: many.map((w) => w.path),
      ratio: '2:3',
      tier: '1.0x',
      align: 'native',
      count: 4,
    })
    expect(p2.total).toBe(16)
    expect(p2.warnings.some((w) => w.text.includes('建议分批'))).toBe(true)
  })

  it('一个流都没选时总数为 0，不产生对齐结论', () => {
    const p = plan({ paths: [] })
    expect(p.total).toBe(0)
    expect(p.usable).toHaveLength(0)
  })
})

describe('buildMatrixPlan 对齐', () => {
  it('对齐到 1024×1536 时逐流选最接近档并报偏差', () => {
    const p = plan({ align: 'ref' })
    expect(p.targetSize).toEqual([1024, 1536])
    expect(p.usable.find((r) => r.path === 'moss')?.tier).toBe('1.0x')
    expect(p.usable.find((r) => r.path === 'moody')?.tier).toBe('0.75x')
    const qwen = p.usable.find((r) => r.path === 'qwen')
    expect(qwen?.deviation).toBeGreaterThan(1)
    expect(p.warnings.some((w) => w.text.includes('仍有偏差'))).toBe(true)
  })

  it('全部落在容差内时给出「条件一致」', () => {
    const same = ['a', 'b'].map((id) => wf(id, { '1.0x': { '2:3': [1024, 1536] } }))
    const p = buildMatrixPlan({
      workflows: same,
      paths: ['a', 'b'],
      ratio: '2:3',
      tier: '1.0x',
      align: 'ref',
      count: 1,
    })
    expect(p.warnings.some((w) => w.kind === 'ok' && w.text.includes('条件一致'))).toBe(true)
  })

  it('对齐到首个：以首行原生尺寸为目标', () => {
    const p = plan({ align: 'first' })
    expect(p.targetSize).toEqual([1024, 1536])
  })

  it('对齐到首个但首行没有该比例时不设目标', () => {
    const p = plan({ align: 'first', ratio: '21:9' })
    expect(p.targetSize).toBeNull()
  })
})

describe('seedForCell', () => {
  it('锁定时列方向 +1，各工作流同列同种子', () => {
    expect(seedForCell(20261112, 0, true)).toBe(20261112)
    expect(seedForCell(20261112, 3, true)).toBe(20261115)
  })

  it('解锁时给非负随机种子', () => {
    const s = seedForCell(20261112, 0, false)
    expect(s).toBeGreaterThanOrEqual(0)
    expect(Number.isInteger(s)).toBe(true)
  })

  it('负基准种子被夹到 0', () => {
    expect(seedForCell(-5, 0, true)).toBe(0)
  })
})
