import { describe, expect, it } from 'vitest'

import { buildQuery, thumbnailUrl, viewUrl } from './client'

describe('buildQuery', () => {
  it('空值不参与拼串', () => {
    expect(buildQuery({ a: '', b: null, c: undefined, d: 'x' })).toBe('?d=x')
  })

  it('0 与 false 必须保留 —— 它们是有效取值，不是"没填"', () => {
    // 曾经把 0 当空值丢掉，导致 missing=0 变成"不筛选"、page=0 变成缺省
    expect(buildQuery({ page: 0, missing: false })).toBe('?page=0&missing=false')
  })

  it('无参数时返回空串（避免拼出裸 "?"）', () => {
    expect(buildQuery()).toBe('')
    expect(buildQuery({ a: '' })).toBe('')
  })

  it('已有查询串时用 & 拼接', () => {
    expect(buildQuery({ a: 1 })).toBe('?a=1')
  })
})

describe('thumbnailUrl / viewUrl', () => {
  const item = {
    filename: 'abc.png',
    subfolder: 'sub',
    img_type: 'output',
    id: 7,
  }

  it('缩略图带上文件名/子目录/类型/尺寸', () => {
    const url = thumbnailUrl(item, 300)
    expect(url).toContain('/api/thumbnail?')
    expect(url).toContain('filename=abc.png')
    expect(url).toContain('subfolder=sub')
    expect(url).toContain('type=output')
    expect(url).toContain('size=300')
  })

  it('缺省子目录被省略，绝不出现 undefined / null 字面量', () => {
    // 空串会被 buildQuery 省略（后端 subfolder 缺省即 ""），但不能漏成 "undefined"
    const url = thumbnailUrl({ filename: 'a.png', subfolder: null, img_type: null, id: 1 })
    expect(url).not.toContain('undefined')
    expect(url).not.toContain('null')
    expect(url).toContain('filename=a.png')
  })

  it('原图地址不带尺寸', () => {
    const url = viewUrl({ filename: 'a.png', subfolder: '', img_type: 'output' })
    expect(url).toContain('/api/image?')
    expect(url).not.toContain('size=')
  })
})
