import { describe, expect, it } from 'vitest'

import {
  readReferenceSearch,
  referenceTabFromDeepLink,
  resolveExplicitReferencePath,
  sanitizeReferencePath,
  withReferenceTab,
} from './referenceDeepLink'

/**
 * 旧深链 `/ref-web/*` → `?tab=` 的校验与映射。
 *
 * 安全边界是本文件的重点：前缀必须是 `/ref-web` 的完整路径段，
 * 任何 `..` / `//` / `\` / `:` 都拒绝，百分号编码穿越在 URL 解析后二次拒绝。
 */
describe('sanitizeReferencePath', () => {
  it.each(['/ref-web', '/ref-web/', '/ref-web/poses', '/ref-web/poses?x=1', '/ref-web#top'])(
    '接受合法深链 %s',
    (value) => {
      expect(sanitizeReferencePath(value)).toBe(value)
    },
  )

  it.each([
    undefined,
    null,
    123,
    '',
    '   ',
    '/ref-webevil',
    '/gallery',
    '/ref-web/../etc/passwd',
    '/ref-web//poses',
    '/ref-web/poses\\..\\x',
    'http://evil.example/ref-web',
    '/ref-web/poses:8080',
  ])('拒绝非法值 %s', (value) => {
    expect(sanitizeReferencePath(value)).toBeNull()
  })

  it('重复 query 参数只取第一个', () => {
    expect(sanitizeReferencePath(['/ref-web/poses', '/ref-web/studio'])).toBe('/ref-web/poses')
    expect(sanitizeReferencePath(['/gallery', '/ref-web/studio'])).toBeNull()
  })
})

describe('resolveExplicitReferencePath', () => {
  it('保留 path + search + hash', () => {
    expect(resolveExplicitReferencePath('/ref-web/poses?x=1#h')).toBe('/ref-web/poses?x=1#h')
  })

  it('百分号编码的穿越被 URL 规范化后拒绝', () => {
    expect(resolveExplicitReferencePath('/ref-web/%2e%2e/etc/passwd')).toBeNull()
    expect(resolveExplicitReferencePath('/ref-web/%2E%2E/x')).toBeNull()
  })

  it('协议相对地址解析后不在前缀内，拒绝', () => {
    expect(resolveExplicitReferencePath('//evil.example/ref-web/poses')).toBeNull()
  })
})

describe('referenceTabFromDeepLink', () => {
  it.each([
    ['/ref-web/poses', 'pose'],
    ['/ref-web/costumes', 'costume'],
    ['/ref-web/portraits', 'portrait'],
    ['/ref-web/studio', 'studio'],
    ['/ref-web/settings', 'settings'],
  ])('%s → %s', (path, tab) => {
    expect(referenceTabFromDeepLink(path)).toBe(tab)
  })

  it.each(['/ref-web', '/ref-web/', '/ref-web/unknown', '/ref-web/poses/extra'])(
    '无对应页签时回落 null：%s',
    (path) => {
      expect(referenceTabFromDeepLink(path)).toBeNull()
    },
  )
})

describe('readReferenceSearch', () => {
  it('读取并裁剪 q', () => {
    expect(readReferenceSearch({ q: ' p1 ' })).toBe('p1')
    expect(readReferenceSearch({ q: ['atlas2k-1201', 'x'] })).toBe('atlas2k-1201')
  })

  it('缺失 / 非法值返回空串', () => {
    expect(readReferenceSearch({})).toBe('')
    expect(readReferenceSearch({ q: null })).toBe('')
  })
})

describe('withReferenceTab', () => {
  it('切页签剔除预填检索词与选图目标，保留其它 query', () => {
    const next = withReferenceTab(
      { tab: 'pose', q: 'P001', selection: 'person_b_group_pose', x: '1' },
      'costume',
    )
    expect(next).toEqual({ tab: 'costume', x: '1' })
  })
})