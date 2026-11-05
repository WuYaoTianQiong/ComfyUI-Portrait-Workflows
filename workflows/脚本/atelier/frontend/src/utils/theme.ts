/**
 * 主题切换与持久化。
 *
 * 只做两件事：把 `data-theme` 写到 `<html>`（tokens.css 据此覆盖变量），
 * 以及把选择存进 localStorage。默认深色，非法值 / 读取失败一律回落到深色，
 * 避免用户本地存了脏数据后整站变成无样式状态。
 */

export type Theme = 'dark' | 'light'

/** 持久化键：带版本后缀，后续改结构时不会误读旧值。 */
export const THEME_STORAGE_KEY = 'pb.theme_v1'

export const DEFAULT_THEME: Theme = 'dark'

export function isTheme(value: unknown): value is Theme {
  return value === 'dark' || value === 'light'
}

/**
 * 读取已保存主题。localStorage 在隐私模式 / 禁用 cookie 时会抛异常，
 * 这里统一按「没存过」处理。
 */
export function readStoredTheme(): Theme {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY)
    return isTheme(stored) ? stored : DEFAULT_THEME
  } catch {
    return DEFAULT_THEME
  }
}

/** 应用到 `<html data-theme>`（不是 body：tokens 的选择器与首屏脚本都按 html 走）。 */
export function applyTheme(theme: Theme): void {
  if (typeof document === 'undefined') return
  document.documentElement.setAttribute('data-theme', theme)
}

export function persistTheme(theme: Theme): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme)
  } catch {
    // 写不进去不影响本次会话的主题，只是刷新后回到默认深色。
  }
}

/** 挂载前调用一次，避免先渲染深色再切浅色造成闪屏。 */
export function applyInitialTheme(): Theme {
  const theme = readStoredTheme()
  applyTheme(theme)
  return theme
}

export function toggledTheme(theme: Theme): Theme {
  return theme === 'dark' ? 'light' : 'dark'
}