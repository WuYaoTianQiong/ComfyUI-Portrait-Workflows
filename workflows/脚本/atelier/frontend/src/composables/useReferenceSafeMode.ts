/**
 * 参考图库 18+ 安全模式（阶段 2.1，全局共享）。
 *
 * 口径逐条对齐 React `studioStore.tsx`（施工手册 §7「全局 · 18+ 安全模式」）：
 * - 键名沿用 `pose_atlas_safe_mode_v1`（缺省 **true**，即默认安全模式）与
 *   `pose_atlas_nsfw_confirmed_v1`（首次确认标记）；
 * - 首次解锁弹一次年龄确认，确认后**本浏览器不再弹**；
 * - 切回安全模式只切换显示，**不重置**确认标记 —— 下次解锁直接放行；
 * - 后端总闸 `GET /api/reference/libraries` 的 `allow_nsfw=false` 时，
 *   解锁入口置灰（`nsfwAvailable=false` / `canUnlock=false`），不再让用户做无效确认。
 *
 * 状态为模块级单例：姿势 / 服装 / 人像页签共用同一份，切页签不会重置；
 * 只有安全模式与确认标记落 localStorage，其余（弹窗开关、总闸探测结果）为内存态。
 */

import { computed, ref } from 'vue'

/** 安全模式开关；缺省 true。 */
export const SAFE_MODE_STORAGE_KEY = 'pose_atlas_safe_mode_v1'
/** 18+ 首次确认标记；写入 true 后不再弹年龄确认。 */
export const NSFW_CONFIRMED_STORAGE_KEY = 'pose_atlas_nsfw_confirmed_v1'
/** 后端总闸端点（`allow_nsfw` 唯一来源）。 */
export const REFERENCE_LIBRARIES_ENDPOINT = '/api/reference/libraries'

/** 读取 localStorage；隐私模式下访问属性本身可能抛错，统一吞掉。 */
function getStorage(): Storage | null {
  try {
    if (typeof globalThis.localStorage === 'undefined') return null
    return globalThis.localStorage
  } catch {
    return null
  }
}

/**
 * 读取安全模式。
 *
 * 缺省为 **true**（安全模式）；只有显式写入 `'false'` 才视为解锁，
 * 与 React 的 `raw === null ? true : raw !== 'false'` 一致。
 */
export function readSafeMode(): boolean {
  try {
    const raw = getStorage()?.getItem(SAFE_MODE_STORAGE_KEY)
    return raw === null || raw === undefined ? true : raw !== 'false'
  } catch {
    return true
  }
}

/** 写入安全模式；存储不可用时静默降级（本次会话仍按内存值工作）。 */
export function writeSafeMode(value: boolean): void {
  try {
    getStorage()?.setItem(SAFE_MODE_STORAGE_KEY, String(value))
  } catch {
    /* 隐私模式 / 配额不足：不阻断功能 */
  }
}

/** 读取「已年满 18 周岁」确认标记。 */
export function readNsfwConfirmed(): boolean {
  try {
    return getStorage()?.getItem(NSFW_CONFIRMED_STORAGE_KEY) === 'true'
  } catch {
    return false
  }
}

/** 写入确认标记；只写 true，撤销需要用户自行清除站点数据（与 React 一致）。 */
export function writeNsfwConfirmed(confirmed: boolean): void {
  try {
    const storage = getStorage()
    if (!storage) return
    if (confirmed) storage.setItem(NSFW_CONFIRMED_STORAGE_KEY, 'true')
    else storage.removeItem(NSFW_CONFIRMED_STORAGE_KEY)
  } catch {
    /* 存储不可用时每次解锁都会确认，功能不中断 */
  }
}

// ---------------------------------------------------------------------------
// 模块级共享状态
// ---------------------------------------------------------------------------

const safeMode = ref(readSafeMode())
const nsfwConfirmed = ref(readNsfwConfirmed())
/** 年龄确认弹窗是否打开 */
const ageGateOpen = ref(false)
/**
 * 后端总闸：`null` 表示尚未探测 / 探测失败（不据此禁用，避免误伤）；
 * `false` 表示后端明确关闭，解锁入口置灰。
 */
const backendAllowNsfw = ref<boolean | null>(null)
const gateLoading = ref(false)
const gateError = ref<string | null>(null)

/** 解锁成功后要执行的回调（例如「解锁并切到第一个 18+ 体系」）。 */
let pendingUnlock: (() => void) | null = null
let inflightGate: Promise<void> | null = null

/** 后端是否允许 18+；未知时按「允许」处理，不阻塞既有功能。 */
const nsfwAvailable = computed(() => backendAllowNsfw.value !== false)

/** 当前是否可发起解锁（安全模式 + 后端总闸未关闭）。 */
const canUnlock = computed(() => safeMode.value && nsfwAvailable.value)

/**
 * 探测后端总闸。
 *
 * 只读、幂等；同一时刻只发一个请求（多页签同时挂载时复用）。
 * 失败只记录 `gateError`，不改变 `backendAllowNsfw` 语义上的「未知」。
 */
function loadBackendGate(): Promise<void> {
  if (inflightGate) return inflightGate
  gateLoading.value = true
  gateError.value = null
  inflightGate = (async () => {
    try {
      const response = await fetch(REFERENCE_LIBRARIES_ENDPOINT)
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const body = (await response.json()) as { allow_nsfw?: unknown }
      backendAllowNsfw.value = typeof body?.allow_nsfw === 'boolean' ? body.allow_nsfw : null
    } catch (cause) {
      gateError.value = cause instanceof Error ? cause.message : String(cause)
      backendAllowNsfw.value = null
    } finally {
      gateLoading.value = false
    }
  })().finally(() => {
    inflightGate = null
  })
  return inflightGate
}

/** 真正切到完整模式：写开关、执行回调。确认标记不在这里写。 */
function unlock(isFirstConfirmation: boolean, onUnlocked?: () => void): void {
  safeMode.value = false
  writeSafeMode(false)
  if (isFirstConfirmation) {
    nsfwConfirmed.value = true
    writeNsfwConfirmed(true)
  }
  onUnlocked?.()
}

/**
 * 请求解锁 18+。
 *
 * 返回 `true` 表示请求被接受（可能只是弹了确认框），`false` 表示后端总闸关闭被拒。
 * - 已经是完整模式：直接执行回调；
 * - 已确认过年满 18：直接解锁，不弹窗；
 * - 首次：打开年龄确认，回调暂存到 `confirmUnlock` 时执行。
 */
function requestUnlock(onUnlocked?: () => void): boolean {
  if (!safeMode.value) {
    nsfwConfirmed.value = readNsfwConfirmed()
    onUnlocked?.()
    return true
  }
  if (!nsfwAvailable.value) return false

  if (readNsfwConfirmed()) {
    nsfwConfirmed.value = true
    unlock(false, onUnlocked)
    return true
  }

  pendingUnlock = onUnlocked ?? null
  ageGateOpen.value = true
  return true
}

/** 确认年满 18：写标记、解锁、执行暂存回调。 */
function confirmUnlock(): void {
  const callback = pendingUnlock
  pendingUnlock = null
  ageGateOpen.value = false
  unlock(true, callback ?? undefined)
}

/** 取消确认：关闭弹窗，丢弃暂存回调，保持安全模式。 */
function cancelUnlock(): void {
  pendingUnlock = null
  ageGateOpen.value = false
}

/**
 * 顶栏按钮语义：安全模式 → 请求解锁；完整模式 → 切回安全模式。
 *
 * 切回安全模式**不动**确认标记（§7 冻结口径：切回不重置）。
 */
function toggleSafeMode(): void {
  if (safeMode.value) {
    requestUnlock()
    return
  }
  safeMode.value = true
  writeSafeMode(true)
}

/** 供页面 / 弹窗使用的 composable 视图。 */
export function useReferenceSafeMode() {
  return {
    safeMode,
    nsfwConfirmed,
    ageGateOpen,
    backendAllowNsfw,
    nsfwAvailable,
    canUnlock,
    gateLoading,
    gateError,
    loadBackendGate,
    requestUnlock,
    confirmUnlock,
    cancelUnlock,
    toggleSafeMode,
  }
}