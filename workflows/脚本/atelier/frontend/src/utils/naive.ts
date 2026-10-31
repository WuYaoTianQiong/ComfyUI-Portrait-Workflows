import { defineComponent, h, ref } from 'vue'
import { createDiscreteApi, darkTheme, NInput, type DialogApi, type MessageApi } from 'naive-ui'

/**
 * Naive UI 适配层。
 *
 * 用 `createDiscreteApi` 而不是在 App 里套 Provider：
 * · 现有 `useToast()` 是模块级单例，任何组件（含深层弹窗）都能直接拿到；
 * · 测试挂载单个组件时不会初始化 Naive，自动退回原来的 ToastHost；
 * · 不需要为了 Provider 改 App 的 DOM 层级。
 *
 * 主题只覆盖主色与圆角，其余沿用项目现有的暗色变量。
 */
let messageApi: MessageApi | null = null
let dialogApi: DialogApi | null = null

export function setupNaive() {
  if (messageApi || typeof document === 'undefined') return
  const { message, dialog } = createDiscreteApi(['message', 'dialog'], {
    configProviderProps: {
      theme: darkTheme,
      themeOverrides: {
        common: {
          primaryColor: '#6366f1',
          primaryColorHover: '#7c7ff5',
          primaryColorPressed: '#5558e6',
          borderRadius: '6px',
        },
      },
    },
  })
  messageApi = message
  dialogApi = dialog
}

export function getMessageApi(): MessageApi | null {
  return messageApi
}

export interface ConfirmOptions {
  title?: string
  content: string
  positiveText?: string
  negativeText?: string
  type?: 'warning' | 'info' | 'error' | 'success'
}

/**
 * 统一确认框。
 *
 * 生产环境走 Naive Dialog；测试/未初始化时退回原生 confirm，
 * 避免为了一个确认框去依赖 App 的 Provider 层级。
 */
export function confirmDialog(options: ConfirmOptions): Promise<boolean> {
  if (!dialogApi) {
    return Promise.resolve(
      typeof window !== 'undefined' ? window.confirm(options.content) : false,
    )
  }
  return new Promise<boolean>((resolve) => {
    let settled = false
    const finish = (value: boolean) => {
      if (settled) return
      settled = true
      resolve(value)
    }
    const api = dialogApi!
    const open = options.type === 'info' ? api.info : api.warning
    open({
      title: options.title ?? '请确认',
      content: options.content,
      positiveText: options.positiveText ?? '确定',
      negativeText: options.negativeText ?? '取消',
      onPositiveClick: () => finish(true),
      onNegativeClick: () => finish(false),
      onClose: () => finish(false),
      onMaskClick: () => finish(false),
    })
  })
}

export interface InputDialogOptions {
  title?: string
  defaultValue?: string
  placeholder?: string
  positiveText?: string
  negativeText?: string
}

/** 文本输入弹窗；返回 null 表示取消。测试环境退回原生 prompt。 */
export function inputDialog(options: InputDialogOptions): Promise<string | null> {
  if (!dialogApi) {
    const result =
      typeof window !== 'undefined'
        ? window.prompt(options.title ?? '', options.defaultValue ?? '')
        : null
    return Promise.resolve(result)
  }
  const value = ref(options.defaultValue ?? '')
  // 用组件包一层：Dialog 的 content 渲染函数只执行一次，直接读 ref 不会跟着输入刷新
  const InputRenderer = defineComponent({
    setup() {
      return () =>
        h(NInput, {
          value: value.value,
          'onUpdate:value': (next: string) => {
            value.value = next
          },
          placeholder: options.placeholder ?? '',
          autofocus: true,
        })
    },
  })
  return new Promise<string | null>((resolve) => {
    let settled = false
    const finish = (next: string | null) => {
      if (settled) return
      settled = true
      resolve(next)
    }
    dialogApi!.create({
      title: options.title ?? '请输入',
      content: () => h(InputRenderer),
      positiveText: options.positiveText ?? '确定',
      negativeText: options.negativeText ?? '取消',
      onPositiveClick: () => finish(value.value.trim() || null),
      onNegativeClick: () => finish(null),
      onClose: () => finish(null),
      onMaskClick: () => finish(null),
    })
  })
}
