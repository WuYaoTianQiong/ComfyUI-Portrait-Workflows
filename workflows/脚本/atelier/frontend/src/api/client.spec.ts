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
    expect(url).toContain('/api/media/thumbnail?')
    expect(url).toContain('filename=abc.png')
    expect(url).toContain('subfolder=sub')
    expect(url).toContain('type=output')
    expect(url).toContain('size=300')
  })

  it('v 优先用内容版本，且纳秒时间戳不丢精度', () => {
    // 源文件版本是超过 2^53 的纳秒时间戳；一旦被当成 number 就再也对不上
    const nanosecondVersion = '1762345678901234567'
    const url = thumbnailUrl({ ...item, version: nanosecondVersion }, 300)
    expect(url).toContain(`v=${nanosecondVersion}`)
    expect(url).not.toContain('v=7')
  })

  it('version 缺失或空串时回落用记录 id', () => {
    expect(thumbnailUrl({ ...item, version: undefined }, 300)).toContain('v=7')
    expect(thumbnailUrl({ ...item, version: '1762345678901234567' }, 300)).toContain(
      'v=1762345678901234567',
    )
    // 后端找不到源文件时给空串：必须回落到 id，而不是让 v 被 buildQuery 吃掉
    expect(thumbnailUrl({ ...item, version: '' }, 300)).toContain('v=7')
    expect(thumbnailUrl({ ...item, version: null }, 300)).toContain('v=7')
  })

  it('既无 version 也无 id 时不出现 undefined / null 字面量', () => {
    const url = thumbnailUrl({ filename: 'a.png' }, 300)
    expect(url).not.toContain('undefined')
    expect(url).not.toContain('null')
    expect(url).not.toContain('v=')
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
    expect(url).toContain('/api/media/image?')
    expect(url).not.toContain('size=')
  })
})
