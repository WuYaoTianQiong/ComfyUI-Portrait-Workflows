/**
 * 页面会话状态的本地持久化：筛选 / 搜索 / 页码 / 选中项 / 滚动位置。
 *
 * 与 useSettings 的区别：这些不是出图参数，而是"下次回到这个页面时，
 * 想看到上次的样子"。只写 localStorage，不进数据库。
 */
export function readSession<T extends object>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return fallback
    const saved = JSON.parse(raw) as Partial<T>
    // 字段合并：新版本新增的字段用默认值，旧存档缺字段也不会变成 undefined
    return { ...fallback, ...saved }
  } catch {
    return fallback
  }
}

export function writeSession(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* 隐私模式下 localStorage 可能不可用，忽略即可 */
  }
}
