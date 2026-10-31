import { describe, expect, it } from 'vitest'

import { formatSize, resolution, shotTime, sourceLabel, statusLabel } from './format'

describe('formatSize', () => {
  it('缺体积时返回空串（不显示 0 KB）', () => {
    expect(formatSize(undefined)).toBe('')
    expect(formatSize(0)).toBe('')
  })

  it('小于 1MB 用 KB', () => {
    expect(formatSize(1024)).toBe('1 KB')
    expect(formatSize(1536)).toBe('2 KB')
  })

  it('大于等于 1MB 用 MB 并保留一位小数', () => {
    expect(formatSize(1024 * 1024)).toBe('1.0 MB')
    expect(formatSize(2.81 * 1024 * 1024)).toBe('2.8 MB')
  })
})

describe('resolution', () => {
  it('宽高齐全才输出', () => {
    expect(resolution({ width: 1128, height: 2008 })).toBe('1128×2008')
    expect(resolution({ width: null, height: 2008 })).toBe('')
    expect(resolution({ width: 1128, height: null })).toBe('')
  })
})

describe('statusLabel', () => {
  it('已知状态中文化', () => {
    expect(statusLabel('done')).toBe('完成')
    expect(statusLabel('running')).toBe('生成中')
    expect(statusLabel('error')).toBe('失败')
  })

  it('未知状态原样返回，不返回 undefined', () => {
    expect(statusLabel('weird')).toBe('weird')
    expect(statusLabel(undefined)).toBe('')
    expect(statusLabel(null)).toBe('')
  })
})

describe('shotTime', () => {
  it('优先用出图时间，回退到入库时间', () => {
    expect(shotTime({ captured_at: '2026-10-30T15:20:11', created_at: '2026-10-01T00:00:00' })).toBe(
      '2026-10-30 15:20',
    )
    expect(shotTime({ captured_at: '', created_at: '2026-10-01T00:00:00' })).toBe('2026-10-01 00:00')
  })
})

describe('sourceLabel', () => {
  it('已知来源给中文名', () => {
    expect(sourceLabel('local')).toBe('本机出图')
    expect(sourceLabel('comfyui_sync')).toBe('ComfyUI 同步')
  })

  it('未知来源原样返回', () => {
    expect(sourceLabel('brand_new')).toBe('brand_new')
  })
})
