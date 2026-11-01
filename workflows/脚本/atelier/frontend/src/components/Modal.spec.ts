import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import Modal from './Modal.vue'

const wrappers: Array<ReturnType<typeof mount>> = []

function mountModal(open = true, title = '') {
  const wrapper = mount(Modal, { props: { open, title }, attachTo: document.body })
  wrappers.push(wrapper)
  return wrapper
}

afterEach(() => {
  for (const wrapper of wrappers.splice(0)) wrapper.unmount()
  document.body.innerHTML = ''
})

describe('Modal 弹层栈', () => {
  it('一次 Esc 只关闭最上面的一层', async () => {
    const bottom = mountModal(true, '底层')
    const top = mountModal(true, '顶层')

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(top.emitted('close')).toHaveLength(1)
    expect(bottom.emitted('close')).toBeUndefined()

    await top.setProps({ open: false })
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(bottom.emitted('close')).toHaveLength(1)
  })

  it('提供 dialog 语义', () => {
    mountModal(true, '标题')
    const panel = document.querySelector('[role="dialog"]')
    expect(panel?.getAttribute('aria-modal')).toBe('true')
    expect(panel?.getAttribute('aria-label')).toBe('标题')
  })
})
