import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { flushReferenceStudioSettings, REFERENCE_TAB_STORAGE_KEY } from '../../composables/useReferenceStudioSettings'
import { useReferenceRecipeDraft } from '../../composables/useReferenceRecipeDraft'
import ReferenceView from '../ReferenceView.vue'

/**
 * happy-dom / Node 25 的全局 localStorage 在当前运行方式下不是完整 Storage
 * （缺 clear），按仓库其它 spec 的做法补一份最小实现。
 */
const localValues = new Map<string, string>()
vi.stubGlobal('localStorage', {
  get length() {
    return localValues.size
  },
  getItem: (key: string) => localValues.get(key) ?? null,
  setItem: (key: string, value: string) => {
    localValues.set(key, value)
  },
  removeItem: (key: string) => {
    localValues.delete(key)
  },
  clear: () => {
    localValues.clear()
  },
  key: (index: number) => [...localValues.keys()][index] ?? null,
} satisfies Storage)

/**
 * 参考图库页签壳：验证 `?tab=` 双向同步、默认页与未知值回落。
 *
 * 阶段 2.3b 起默认页由「姿势库」改为「图库总览」（施工手册 §6 要求
 * `/ref-web/` → `/reference` 能承接 React 首页），本文件相应更新断言。
 *
 * 直接挂载 `ReferenceView`（路由组件本身），router 只用来提供 route / replace：
 * 这样断言不会被 App 顶栏、数据请求等无关因素干扰。
 * 首页的数据加载在测试环境会失败并渲染错误条，但页签标题与入口按钮始终存在。
 */
async function mountAt(url: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/reference', component: { template: '<div />' } }],
  })
  await router.push(url)
  await router.isReady()

  // 挂载后再 spy，避免把初始化时的 push 算进来。
  const replaceSpy = vi.spyOn(router, 'replace')
  const pushSpy = vi.spyOn(router, 'push')

  const wrapper = mount(ReferenceView, {
    global: { plugins: [router] },
  })
  await flushPromises()

  return { router, wrapper, replaceSpy, pushSpy }
}

function tabButton(wrapper: ReturnType<typeof mount>, label: string) {
  const button = wrapper.findAll('.reference-tab').find((item) => item.text() === label)
  if (!button) throw new Error(`没找到页签按钮：${label}`)
  return button
}

function activeTabLabel(wrapper: ReturnType<typeof mount>): string | undefined {
  return wrapper
    .findAll('.reference-tab')
    .find((item) => item.attributes('aria-selected') === 'true')
    ?.text()
}

const TABS = [
  { tab: 'home', label: '图库总览', title: '图库总览' },
  { tab: 'pose', label: '姿势', title: '姿势库' },
  { tab: 'costume', label: '服装', title: '服装库' },
  { tab: 'portrait', label: '人像', title: '人像库' },
  { tab: 'studio', label: '合成台', title: '合成台' },
  { tab: 'settings', label: '设置', title: '设置' },
] as const

/**
 * 每个用例都从「无记忆」状态开始：页签与三槽都会写 localStorage，
 * 不清空会让「无 tab 默认首页」等用例读到上一个用例写入的最后页签。
 */
beforeEach(() => {
  useReferenceRecipeDraft().clearDraft()
  flushReferenceStudioSettings()
  localStorage.clear()
})

describe('ReferenceView 六页签壳', () => {
  it.each(TABS)('?tab=$tab 直达渲染「$title」并把「$label」标为选中', async ({ tab, label, title }) => {
    const { wrapper } = await mountAt(`/reference?tab=${tab}`)

    expect(wrapper.find('.tab-placeholder__title').text()).toBe(title)
    expect(activeTabLabel(wrapper)).toBe(label)
    expect(wrapper.find('[role="tabpanel"]').exists()).toBe(true)
  })

  it('无 tab 参数时默认渲染「图库总览」，不白屏', async () => {
    const { wrapper } = await mountAt('/reference')

    expect(wrapper.find('[data-testid="reference-home"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="reference-home-title"]').text()).toBe('图库总览')
    expect(activeTabLabel(wrapper)).toBe('图库总览')
  })

  it('未知 tab 回落「图库总览」，不白屏', async () => {
    const { wrapper } = await mountAt('/reference?tab=unknown')

    expect(wrapper.find('[data-testid="reference-home"]').exists()).toBe(true)
    expect(activeTabLabel(wrapper)).toBe('图库总览')
  })

  it('重复 tab 参数取第一个合法值', async () => {
    const { wrapper } = await mountAt('/reference?tab=unknown&tab=costume')

    expect(wrapper.find('.tab-placeholder__title').text()).toBe('服装库')
  })

  it('点页签只用 replace 写回 query，不产生历史堆积', async () => {
    const { router, wrapper, replaceSpy, pushSpy } = await mountAt('/reference?tab=pose')

    await tabButton(wrapper, '服装').trigger('click')
    await flushPromises()
    await tabButton(wrapper, '人像').trigger('click')
    await flushPromises()

    expect(wrapper.find('.tab-placeholder__title').text()).toBe('人像库')
    expect(router.currentRoute.value.query.tab).toBe('portrait')
    expect(replaceSpy).toHaveBeenCalledTimes(2)
    expect(pushSpy).not.toHaveBeenCalled()
  })

  it('切换页签剔除废弃的 shell / path，保留业务 query', async () => {
    const { router, wrapper } = await mountAt('/reference?shell=vue&x=1&tab=pose')

    await tabButton(wrapper, '合成台').trigger('click')
    await flushPromises()

    const query = router.currentRoute.value.query
    expect(query).toMatchObject({ tab: 'studio', x: '1' })
    expect(query.shell).toBeUndefined()
    expect(query.path).toBeUndefined()
  })

  it('点当前页签不重复导航', async () => {
    const { wrapper, replaceSpy } = await mountAt('/reference?tab=pose')

    await tabButton(wrapper, '姿势').trigger('click')
    await flushPromises()

    expect(replaceSpy).not.toHaveBeenCalled()
  })

  it('首页三库入口与进入合成台按 ?tab= 跳转，并剔除废弃的 shell', async () => {
    const { router, wrapper } = await mountAt('/reference?shell=vue')

    await wrapper.find('[data-testid="home-entry-costume"]').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.query).toMatchObject({
      tab: 'costume',
    })
    expect(router.currentRoute.value.query.shell).toBeUndefined()

    // 回到首页，验证「进入合成台」按钮与 n/3 文案
    await router.replace('/reference?shell=vue&tab=home')
    await flushPromises()

    const studioButton = wrapper.find('[data-testid="reference-home-studio"]')
    expect(studioButton.exists()).toBe(true)
    expect(studioButton.text()).toContain('进入合成台 (0/3)')

    await studioButton.trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.query).toMatchObject({
      tab: 'studio',
    })
    expect(router.currentRoute.value.query.shell).toBeUndefined()
  })

  it('首页配方槽显示初始 n/3 计数', async () => {
    const { wrapper } = await mountAt('/reference')

    expect(wrapper.find('[data-testid="reference-home-recipe-count"]').text()).toBe('0/3')
    const slots = wrapper.findAll('[data-testid^="home-slot-"]')
    expect(slots).toHaveLength(3)
  })
})
describe('最后访问页签恢复（URL > 存储 > home）', () => {
  it('URL 有合法 tab 时优先于存储，并把该页签写回', async () => {
    localStorage.setItem(REFERENCE_TAB_STORAGE_KEY, 'costume')

    const { wrapper } = await mountAt('/reference?tab=pose')

    expect(activeTabLabel(wrapper)).toBe('姿势')
    expect(localStorage.getItem(REFERENCE_TAB_STORAGE_KEY)).toBe('pose')
  })

  it('URL 无 tab 时用存储里的最后页签', async () => {
    localStorage.setItem(REFERENCE_TAB_STORAGE_KEY, 'portrait')

    const { wrapper } = await mountAt('/reference')

    expect(activeTabLabel(wrapper)).toBe('人像')
    expect(wrapper.find('.tab-placeholder__title').text()).toBe('人像库')
  })

  it('存储值非法 / 不存在时回落图库总览', async () => {
    localStorage.setItem(REFERENCE_TAB_STORAGE_KEY, 'not-a-tab')

    const { wrapper } = await mountAt('/reference')

    expect(activeTabLabel(wrapper)).toBe('图库总览')
    expect(wrapper.find('[data-testid="reference-home"]').exists()).toBe(true)
  })

  it('点页签切换后写回存储，供下次无 tab 访问恢复', async () => {
    const { wrapper } = await mountAt('/reference?tab=home')

    await tabButton(wrapper, '设置').trigger('click')
    await flushPromises()

    expect(localStorage.getItem(REFERENCE_TAB_STORAGE_KEY)).toBe('settings')
  })
})
describe('左导航折叠（图标 rail）契约', () => {
  /** 与 ReferenceView.vue 中 NAV_COLLAPSED_STORAGE_KEY 保持一致（带版本后缀）。 */
  const NAV_COLLAPSED_STORAGE_KEY = 'pb.reference_nav_collapsed_v1'
  const ALL_TAB_LABELS = TABS.map((item) => item.label)

  function railToggle(wrapper: ReturnType<typeof mount>) {
    return wrapper.get('[data-testid="studio-rail-toggle"]')
  }

  it('点折叠按钮后进入折叠态，页签语义与当前选中态保持不变', async () => {
    const { wrapper } = await mountAt('/reference?tab=pose')

    expect(railToggle(wrapper).attributes('aria-expanded')).toBe('true')

    await railToggle(wrapper).trigger('click')
    await flushPromises()

    // 折叠 class + aria 状态 + 记忆写入
    expect(wrapper.get('.reference-page__inner').classes()).toContain('is-rail-collapsed')
    expect(railToggle(wrapper).attributes('aria-expanded')).toBe('false')
    expect(localStorage.getItem(NAV_COLLAPSED_STORAGE_KEY)).toBe('1')

    // 折叠只影响视觉，不破坏 tablist / aria-selected 语义
    expect(wrapper.find('[role="tablist"]').exists()).toBe(true)
    expect(activeTabLabel(wrapper)).toBe('姿势')
  })

  it('预置折叠记忆后挂载即为折叠态，六个页签文本仍留在 DOM', async () => {
    localStorage.setItem(NAV_COLLAPSED_STORAGE_KEY, '1')

    const { wrapper } = await mountAt('/reference?tab=costume')

    expect(wrapper.get('.reference-page__inner').classes()).toContain('is-rail-collapsed')
    expect(railToggle(wrapper).attributes('aria-expanded')).toBe('false')

    // 折叠态标签用 display:none 隐藏但节点不删，text() 仍能读到全部标签
    const labels = wrapper.findAll('.reference-tab').map((item) => item.text())
    expect(labels).toHaveLength(6)
    expect(labels).toEqual(ALL_TAB_LABELS)
    expect(activeTabLabel(wrapper)).toBe('服装')
  })

  it('折叠后再展开写回 0，且全程不触发路由导航', async () => {
    localStorage.setItem(NAV_COLLAPSED_STORAGE_KEY, '1')

    const { wrapper, replaceSpy, pushSpy } = await mountAt('/reference?tab=pose')
    expect(wrapper.get('.reference-page__inner').classes()).toContain('is-rail-collapsed')

    await railToggle(wrapper).trigger('click')
    await flushPromises()

    expect(wrapper.get('.reference-page__inner').classes()).not.toContain('is-rail-collapsed')
    expect(railToggle(wrapper).attributes('aria-expanded')).toBe('true')
    expect(localStorage.getItem(NAV_COLLAPSED_STORAGE_KEY)).toBe('0')

    // 折叠/展开是纯 UI 状态，不得产生 replace / push 导航
    expect(replaceSpy).not.toHaveBeenCalled()
    expect(pushSpy).not.toHaveBeenCalled()
  })
})