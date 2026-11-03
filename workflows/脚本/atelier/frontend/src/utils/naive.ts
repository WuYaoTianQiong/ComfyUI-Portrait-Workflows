import { defineComponent, h, ref } from 'vue'
import {
  createDiscreteApi,
  darkTheme,
  NCheckbox,
  NInput,
  type DialogApi,
  type MessageApi,
} from 'naive-ui'

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
  /**
   * 传了就显示「下次不再提示」勾选框；确认时勾选则记到 localStorage，
   * 之后同一个 key 的确认框直接放行，不再弹。破坏性操作不要传。
   */
  rememberKey?: string
}

const SKIP_KEY_PREFIX = 'pb.confirmSkip.'

/** 这个确认框是否已被用户记住「不再提示」。 */
export function isConfirmSkipped(key: string): boolean {
  try {
    return localStorage.getItem(SKIP_KEY_PREFIX + key) === '1'
  } catch {
    return false
  }
}

export function skipConfirm(key: string): void {
  try {
    localStorage.setItem(SKIP_KEY_PREFIX + key, '1')
  } catch {
    /* 隐私模式下 localStorage 不可用，忽略即可 */
  }
}

export function resetConfirmSkip(key: string): void {
  try {
    localStorage.removeItem(SKIP_KEY_PREFIX + key)
  } catch {
    /* 隐私模式下 localStorage 不可用，忽略即可 */
  }
}

const REMEMBER_LABEL = '下次不再提示（可在「分类与标签」里恢复）'

/**
 * 统一确认框。
 *
 * 生产环境走 Naive Dialog；测试/未初始化时退回原生 confirm，
 * 避免为了一个确认框去依赖 App 的 Provider 层级。
 */
export function confirmDialog(options: ConfirmOptions): Promise<boolean> {
  if (options.rememberKey && isConfirmSkipped(options.rememberKey)) {
    return Promise.resolve(true)
  }
  if (!dialogApi) {
    return Promise.resolve(
      typeof window !== 'undefined' ? window.confirm(options.content) : false,
    )
  }
  const remember = ref(false)
  // Dialog 的 content 只渲染一次：用组件包一层，勾选态才会跟着刷新
  const RememberedContent = options.rememberKey
    ? defineComponent({
        setup() {
          return () =>
            h('div', null, [
              h('div', { style: 'margin-bottom:12px;white-space:pre-line' }, options.content),
              h(
                NCheckbox,
                {
                  checked: remember.value,
                  'onUpdate:checked': (next: boolean) => {
                    remember.value = next
                  },
                },
                { default: () => REMEMBER_LABEL },
              ),
            ])
        },
      })
    : null
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
      content: RememberedContent ? () => h(RememberedContent) : options.content,
      positiveText: options.positiveText ?? '确定',
      negativeText: options.negativeText ?? '取消',
      onPositiveClick: () => {
        if (options.rememberKey && remember.value) skipConfirm(options.rememberKey)
        finish(true)
      },
      onNegativeClick: () => finish(false),
      onClose: () => finish(false),
      onMaskClick: () => finish(false),
    })
  })
}

export interface ConfirmCheckboxOptions extends ConfirmOptions {
  /** 勾选框文案，例如「同时删除磁盘上的原图文件」 */
  checkboxLabel: string
  /** 勾选框初始状态，默认不勾选（破坏性操作不预勾） */
  defaultChecked?: boolean
}

export interface ConfirmCheckboxResult {
  confirmed: boolean
  checked: boolean
}

/**
 * 带一个勾选框的确认框。
 *
 * 用于「删除记录时是否连磁盘文件一起删」这类需要用户显式表态的破坏性操作：
 * 确认按钮的语义始终是主操作，勾选框只决定额外范围，默认不勾。
 * 未初始化（测试环境）时退回原生 confirm，勾选态直接用默认值。
 */
export function confirmDialogWithCheckbox(
  options: ConfirmCheckboxOptions,
): Promise<ConfirmCheckboxResult> {
  const checked = ref(options.defaultChecked ?? false)
  if (!dialogApi) {
    const confirmed =
      typeof window !== 'undefined'
        ? window.confirm(
            `${options.content}\n\n${checked.value ? '☑' : '☐'} ${options.checkboxLabel}`,
          )
        : false
    return Promise.resolve({ confirmed, checked: checked.value })
  }
  // 用组件包一层：Dialog 的 content 渲染函数只执行一次，直接读 ref 不会跟着勾选刷新
  const ContentRenderer = defineComponent({
    setup() {
      return () =>
        h('div', null, [
          h('div', { style: 'margin-bottom:12px;white-space:pre-line' }, options.content),
          h(
            NCheckbox,
            {
              checked: checked.value,
              'onUpdate:checked': (next: boolean) => {
                checked.value = next
              },
            },
            { default: () => options.checkboxLabel },
          ),
        ])
    },
  })
  return new Promise<ConfirmCheckboxResult>((resolve) => {
    let settled = false
    const finish = (confirmed: boolean) => {
      if (settled) return
      settled = true
      // 取消时也带上当前勾选态：调用方据此决定是否记住用户的选择
      resolve({ confirmed, checked: checked.value })
    }
    const api = dialogApi!
    const open = options.type === 'info' ? api.info : api.warning
    open({
      title: options.title ?? '请确认',
      content: () => h(ContentRenderer),
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
