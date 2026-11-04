import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

export type Theme = 'light' | 'dark' | 'system'

/** 当前存储键（atelier 口径）。 */
const STORAGE_KEY = 'atelier:theme'
/** 上游旧键：仅用于兼容读取，避免用户已有选择丢失。 */
const LEGACY_STORAGE_KEY = 'todaynew-admin:theme'
/** atelier 是固定暗色，未存过偏好时默认深色。 */
const DEFAULT_THEME: Theme = 'dark'

interface ThemeState {
  theme: Theme
  setTheme: (t: Theme) => void
}

const ThemeContext = createContext<ThemeState | null>(null)

function isTheme(value: string | null): value is Theme {
  return value === 'light' || value === 'dark' || value === 'system'
}

function readTheme(): Theme {
  try {
    // 先读新键；新键缺失或值无效时回退旧键，再回退默认深色。
    const current = localStorage.getItem(STORAGE_KEY)
    if (isTheme(current)) return current
    const legacy = localStorage.getItem(LEGACY_STORAGE_KEY)
    if (isTheme(legacy)) return legacy
  } catch {
    // 隐私模式或禁用存储时 localStorage 会抛 SecurityError，回退默认值。
  }
  return DEFAULT_THEME
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(readTheme)

  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const apply = () => {
      const dark = theme === 'dark' || (theme === 'system' && media.matches)
      document.documentElement.classList.toggle('dark', dark)
    }
    apply()
    if (theme !== 'system') return
    media.addEventListener('change', apply)
    return () => media.removeEventListener('change', apply)
  }, [theme])

  const setTheme = (t: Theme) => {
    // 先更新 UI，写入失败（存储被禁用/超配额）时至少当前会话生效。
    setThemeState(t)
    try {
      localStorage.setItem(STORAGE_KEY, t)
    } catch {
      // 忽略：主题切换不因持久化失败而中断。
    }
  }

  return <ThemeContext value={{ theme, setTheme }}>{children}</ThemeContext>
}

// oxlint-disable-next-line react/only-export-components
export function useTheme() {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme 必须在 ThemeProvider 内使用')
  return ctx
}
