// vitest setup：补齐测试环境的 localStorage / sessionStorage。
//
// 背景（2026-11-21，ci.ps1 首跑抓出）：vitest 2.x + happy-dom 15 的全局 localStorage
// 是一个没有 Storage 方法的空对象（getItem/setItem/removeItem 全 undefined）。
// 组件侧一直没炸是因为 useSessionState 的 readSession/writeSession 全程 try/catch
// 静默兜底——代价是 storage 相关逻辑在所有 spec 里从未真正生效过。
// TaxonomyView.spec 的用例隔离（39ad443a）直接调 removeItem 才把问题暴露出来。
//
// 这里只在环境缺方法时安装忠实桩（Map 语义，与浏览器 Storage 一致）；
// setupFiles 每个测试文件独立执行一次，等价于每个文件一个干净的"浏览器会话"。

function makeStorage(): Storage {
  const map = new Map<string, string>()
  const storage = {
    getItem: (key: string) => (map.has(key) ? (map.get(key) as string) : null),
    setItem: (key: string, value: string) => {
      map.set(String(key), String(value))
    },
    removeItem: (key: string) => {
      map.delete(key)
    },
    clear: () => {
      map.clear()
    },
    key: (index: number) => Array.from(map.keys())[index] ?? null,
  }
  Object.defineProperty(storage, 'length', { get: () => map.size })
  return storage as unknown as Storage
}

function ensureStorage(name: 'localStorage' | 'sessionStorage') {
  const current = (globalThis as Record<string, unknown>)[name] as
    | Partial<Storage>
    | undefined
  if (current && typeof current.getItem === 'function' && typeof current.removeItem === 'function') {
    return // 环境已经能用了（未来 happy-dom/vitest 修复后这里自动跳过）
  }
  Object.defineProperty(globalThis, name, {
    value: makeStorage(),
    configurable: true,
    writable: true,
  })
}

ensureStorage('localStorage')
ensureStorage('sessionStorage')
