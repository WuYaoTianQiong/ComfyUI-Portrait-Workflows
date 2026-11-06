<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useToast } from '../../composables/useToast'
import { withReferenceTab } from './referenceDeepLink'

/**
 * 参考图库「设置」页（施工手册 §7「设置」行 / 阶段 2.3）。
 *
 * 迁移范围与 React 版 `gallery-web/src/routes/settings.tsx` 保持一致：
 * - ComfyUI Base URL：输入即生效，**没有保存按钮**；
 * - 自动识别：与 React 版 `aiGenerator.detectComfyUi()` 逐行对齐——纯前端扫描
 *   候选地址（当前地址 → 本地同源代理 `/comfy` → 127.0.0.1:8000 → 127.0.0.1:8188），
 *   **串行**逐个请求 `/system_stats`（单次超时 8 秒），首个成功即采用；
 *   不依赖、也不新增任何后端接口；
 * - 测试连接：给出成功/失败简体中文反馈，失败按「现象 + 原因 + 下一步」三句式
 *   说明；地址为 `/comfy` 时走后端既有同源反代（`app/main.py` 的 `/comfy/{path}`），
 *   绝对地址则按 React 版行为由浏览器直连（跨源时需 ComfyUI 放行 CORS）；
 * - 重置：恢复默认地址（本地 host 为 `/comfy`，其它 host 为 `http://127.0.0.1:8000`）；
 * - 返回合成台：走 vue-router 切到 `?tab=studio`，不整页刷新。
 *
 * 明确不做：主题切换（主题在 Vue 主站顶栏）、旧生成记录导出（数据已弃）。
 *
 * 架构事实（页面上如实告知用户）：后端出图链路使用的 ComfyUI 地址来自服务端启动
 * 配置（`settings.comfyui_api`），前端无法修改；本页保存的地址只作用于浏览器侧
 * 的探测/直连。
 */

/** React `COMFY_DEV_PROXY`：本地访问时使用的同源代理前缀（见 `app/main.py` 的 `/comfy/{path:path}`）。 */
const COMFY_DEV_PROXY = '/comfy'

/** 记忆键（命名规范：`pb.` 前缀 + 版本后缀，废弃旧值时不会误伤）。 */
const STORAGE_KEY = 'pb.reference_comfy_base_url_v1'

/** 单次探测上限；与 React 版 `testComfyConnection` 的 8 秒一致。 */
const PROBE_TIMEOUT_MS = 8000

/**
 * React `isLocalDevHost()` 的平移：只有本机访问才走同源代理。
 *
 * React 版用 `window.location.hostname` 判定；同源代理能绕开 ComfyUI 的
 * CORS 白名单限制，所以在 127.0.0.1 / localhost 下永远是首选候选。
 */
function isLocalDevHost(): boolean {
  return (
    typeof window !== 'undefined' &&
    ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname)
  )
}

/** React `defaultComfyBaseUrl()`：本地走同源代理，其它 host 用 Desktop 默认端口 8000。 */
function defaultComfyBaseUrl(): string {
  return isLocalDevHost() ? COMFY_DEV_PROXY : 'http://127.0.0.1:8000'
}

/**
 * React `comfyCandidateUrls(current)` 的逐行平移。
 *
 * 顺序固定：当前输入地址 → 本地同源代理（仅本机 host）→ 127.0.0.1:8000 →
 * 127.0.0.1:8188；每项去尾部斜杠、去空值，最后去重**保序**（`Set` 保留插入序）。
 */
function comfyCandidateUrls(current: string): string[] {
  const candidates = [
    current.trim(),
    isLocalDevHost() ? defaultComfyBaseUrl() : '',
    'http://127.0.0.1:8000',
    'http://127.0.0.1:8188',
  ]
    .map((item) => item.replace(/\/+$/, ''))
    .filter(Boolean)
  return Array.from(new Set(candidates))
}

/** 连接测试结论：成功为绿字，失败为红字，都直接展示在按钮下方。 */
interface ProbeResult {
  kind: 'success' | 'error'
  text: string
}

/** 探测结果三态：`cancelled` 表示组件已卸载、请求被主动中止，不应再写 UI。 */
type ProbeOutcome =
  | { status: 'ok'; info: string }
  | { status: 'failed'; text: string }
  | { status: 'cancelled' }

const route = useRoute()
const router = useRouter()
const toast = useToast()

/** 窄进：把任意 JSON 值收成可安全取字段的对象。 */
function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : null
}

/** 去首尾空白与尾部斜杠；空值回落默认地址（与 React 版 `normalizeComfyBase` 一致）。 */
function normalizeBaseUrl(raw: string): string {
  const trimmed = raw.trim()
  if (!trimmed) return defaultComfyBaseUrl()
  const withoutTrailingSlash = trimmed.replace(/\/+$/, '')
  return withoutTrailingSlash || defaultComfyBaseUrl()
}

/**
 * 校验地址形态，返回三句式错误文本；合法返回 null。
 *
 * 只接受两类：以单个 `/` 开头的同源路径（如 `/comfy`）与 http(s) 绝对地址。
 * `//host` 是协议相对地址，会被浏览器当成外部域名，显式拒绝以免把探测请求
 * 发到非预期主机。
 */
function validateBaseUrl(base: string): string | null {
  if (base.startsWith('/')) {
    if (base.startsWith('//')) {
      return (
        `地址无效：${base} 是协议相对地址。` +
        '原因：以 // 开头的写法会被浏览器解析成外部域名，探测请求可能发往非预期主机。' +
        '下一步：同源代理请填 /comfy，外部地址请写完整的 http:// 或 https://。'
      )
    }
    return null
  }
  if (/^https?:\/\//i.test(base)) return null
  return (
    `地址无效：${base} 不是可用的地址格式。` +
    '原因：本页只支持同源路径（如 /comfy）或 http(s):// 开头的绝对地址。' +
    '下一步：修正地址后点「测试连接」重试。'
  )
}

function readStoredBaseUrl(): string {
  try {
    if (typeof window === 'undefined') return defaultComfyBaseUrl()
    // 空字符串是有效值（用户主动清空 = 使用默认），因此不能用 `||` 兜底。
    return window.localStorage.getItem(STORAGE_KEY) ?? defaultComfyBaseUrl()
  } catch {
    // 隐私模式下读取 localStorage 可能直接抛 SecurityError
    return defaultComfyBaseUrl()
  }
}

/** 即时生效：每次输入变化都落盘，不提供保存按钮。 */
function persistBaseUrl(value: string): void {
  try {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(STORAGE_KEY, value)
  } catch {
    // 写入失败（配额/隐私模式）不回滚用户输入，本次会话仍按内存值工作
  }
}

/** 后端反代失败时返回 `{"error": "..."}`；优先展示其中的人类可读字段。 */
async function readResponseDetail(response: Response): Promise<string> {
  try {
    const text = (await response.text()).trim()
    if (!text) return ''
    let parsed: unknown = null
    try {
      parsed = JSON.parse(text)
    } catch {
      // 非 JSON（例如网关 HTML 错误页），直接用原文片段
    }
    const record = asRecord(parsed)
    const message =
      record && typeof record.error === 'string'
        ? record.error
        : record && typeof record.detail === 'string'
          ? record.detail
          : ''
    return String(message || text).slice(0, 160)
  } catch {
    return ''
  }
}

function describeHttpFailure(base: string, status: number, detail: string): string {
  const suffix = detail ? `（${detail}）` : ''
  if (status === 401 || status === 403) {
    return (
      `连接失败：${base}/system_stats 拒绝访问（HTTP ${status}）${suffix}。` +
      '原因：该地址开启了鉴权，或代理不允许浏览器直连。' +
      '下一步：在能通过鉴权的环境中测试，或改用同源代理 /comfy。'
    )
  }
  if (status === 404) {
    return (
      `连接失败：${base}/system_stats 返回 HTTP 404${suffix}。` +
      '原因：该地址下没有 ComfyUI 的 system_stats 接口，可能是端口不对或带了子路径。' +
      '下一步：填写 ComfyUI 根地址（如 http://127.0.0.1:8188）后重试。'
    )
  }
  if (status >= 500) {
    return (
      `连接失败：${base}/system_stats 返回 HTTP ${status}${suffix}。` +
      '原因：后端到 ComfyUI 的链路异常，通常是 ComfyUI 未启动或反向代理上游不可达。' +
      '下一步：启动 ComfyUI（默认 127.0.0.1:8188）后重试。'
    )
  }
  return (
    `连接失败：${base}/system_stats 返回 HTTP ${status}${suffix}。` +
    '原因：该地址可以访问，但不是可用的 ComfyUI 接口。' +
    '下一步：确认协议、地址与端口后重试。'
  )
}

function describeNetworkFailure(base: string, error: unknown, timedOut: boolean): string {
  if (timedOut) {
    return (
      `连接失败：${PROBE_TIMEOUT_MS / 1000} 秒内没有响应（${base}/system_stats）。` +
      '原因：目标端口未监听、ComfyUI 未启动，或被防火墙拦截。' +
      '下一步：确认 ComfyUI 已启动且端口正确，再点「测试连接」重试。'
    )
  }
  const reason = error instanceof Error ? error.message : String(error)
  if (base.startsWith('http')) {
    return (
      `连接失败：浏览器无法访问 ${base}（${reason}）。` +
      '原因：该地址未启动、端口被浏览器禁止，或 ComfyUI 未放行跨域（浏览器直连需要 CORS 许可）。' +
      '下一步：确认 ComfyUI 已启动；若仍失败，改用同源代理 /comfy（由后端转发，无需跨域）。'
    )
  }
  return (
    `连接失败：无法访问同源地址 ${base}（${reason}）。` +
    '原因：后端服务异常或该路径不可用。' +
    '下一步：确认后端正常运行后重试，或改用完整地址。'
  )
}

/** 从 `/system_stats` 响应组装成功文案（与 React 版展示口径一致）。 */
function describeComfy(system: Record<string, unknown>, devices: unknown): string {
  const version =
    typeof system.comfyui_version === 'string' && system.comfyui_version.trim()
      ? system.comfyui_version.trim()
      : '未知版本'
  const firstDevice = Array.isArray(devices) ? asRecord(devices[0]) : null
  const rawName = typeof firstDevice?.name === 'string' ? firstDevice.name : ''
  // ComfyUI 设备名形如 `cuda:0 NVIDIA GeForce RTX 5070 : cudaMallocAsync`，
  // 去掉前缀与后端类型后缀，只留硬件名。
  const gpu = rawName
    ? rawName.replace(/^cuda:\d+\s*/, '').replace(/\s*:\s*\w+$/, '').trim()
    : '本机设备'
  const vramTotal = typeof firstDevice?.vram_total === 'number' ? firstDevice.vram_total : 0
  const vram = vramTotal > 0 ? ` · 显存 ${(vramTotal / 1024 ** 3).toFixed(1)} GB` : ''
  return `ComfyUI ${version} · ${gpu}${vram}`
}

/**
 * 探测一个 ComfyUI 地址的 `/system_stats`（React `testComfyConnection` 的等价实现）。
 *
 * - 端点、超时（8s）与成功判定（HTTP 2xx + JSON + 顶层 `system` 字段）逐条对齐 React；
 * - `base` 为同源路径（默认 `/comfy`）时请求打到后端既有反代，不新造接口；
 * - `base` 为绝对地址时与 React 版一致由浏览器直连（跨源需 ComfyUI 放行 CORS）。
 */
async function probeComfy(base: string): Promise<ProbeOutcome> {
  const controller = new AbortController()
  activeController = controller
  let timedOut = false
  const timer = window.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, PROBE_TIMEOUT_MS)

  try {
    const response = await fetch(`${base}/system_stats`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: controller.signal,
      // 探测不应携带用户登录态，避免把凭据发给外部地址
      credentials: 'omit',
      cache: 'no-store',
    })

    if (!response.ok) {
      const detail = await readResponseDetail(response)
      return { status: 'failed', text: describeHttpFailure(base, response.status, detail) }
    }

    let payload: unknown
    try {
      payload = await response.json()
    } catch {
      return {
        status: 'failed',
        text:
          `连接失败：${base}/system_stats 的响应不是 JSON。` +
          '原因：该地址返回了网页或代理错误页，可能不是 ComfyUI 的根地址。' +
          '下一步：确认地址与端口（ComfyUI 默认 8188），不要带子路径。',
      }
    }

    const record = asRecord(payload)
    const system = asRecord(record?.system)
    if (!system) {
      return {
        status: 'failed',
        text:
          `连接失败：${base}/system_stats 返回的 JSON 不是 ComfyUI 状态格式。` +
          '原因：该地址指向了其它服务或中间代理。' +
          '下一步：填写 ComfyUI 根地址（如 http://127.0.0.1:8188）后重试。',
      }
    }

    return { status: 'ok', info: describeComfy(system, record?.devices) }
  } catch (error) {

    // 组件卸载导致的主动中止：静默放弃，不写 UI
    if (controller.signal.aborted && !timedOut) return { status: 'cancelled' }
    return { status: 'failed', text: describeNetworkFailure(base, error, timedOut) }
  } finally {
    window.clearTimeout(timer)
    if (activeController === controller) activeController = null
  }
}

const baseUrl = ref<string>(readStoredBaseUrl())
const probeState = ref<'idle' | 'testing'>('idle')
const probeResult = ref<ProbeResult | null>(null)
let activeController: AbortController | null = null

/** 实际参与探测/生效的地址：留空回落默认。 */
const effectiveBaseUrl = computed(() => normalizeBaseUrl(baseUrl.value))
const isTesting = computed(() => probeState.value === 'testing')
/** 默认地址随 host 变化：本机 = `/comfy`，其它 host = Desktop 默认端口 8000。 */
const defaultBaseUrl = defaultComfyBaseUrl()

watch(baseUrl, (value) => {
  persistBaseUrl(value)
  // 地址一变，上一条结论就不再适用于当前输入
  if (probeResult.value) probeResult.value = null
})

onBeforeUnmount(() => {

  activeController?.abort()
  activeController = null
})

/**
 * React `detectComfyUi()` 的逐行平移：**串行**尝试候选地址，返回第一个探测成功的
 * 地址；全部失败返回 null。候选顺序与探测参数见 `comfyCandidateUrls` / `probeComfy`。
 */
async function detectComfyUi(current: string): Promise<{ baseUrl: string; info: string } | null> {
  for (const url of comfyCandidateUrls(current)) {
    const outcome = await probeComfy(url)
    // 组件已卸载（请求被主动中止）：停止扫描，不写任何 UI
    if (outcome.status === 'cancelled') return null
    if (outcome.status === 'ok') return { baseUrl: url, info: outcome.info }
  }
  return null
}

/** 自动识别：与 React `handleDetectComfy` 相同的扫描、成功/失败文案与状态互斥。 */
async function onDetect(): Promise<void> {
  // React 里「自动识别」与「测试连接」共用 testingComfy，两者互斥
  if (probeState.value === 'testing') return
  probeState.value = 'testing'
  probeResult.value = null
  try {
    const found = await detectComfyUi(effectiveBaseUrl.value)
    if (!found) {
      toast.error(
        '未找到可用的 ComfyUI（已尝试当前地址、127.0.0.1:8000、127.0.0.1:8188），请确认本机 ComfyUI 已启动。',
      )
      return
    }
    // 等价于 React 的 updateProviderConfig('comfyui', { baseUrl })：改完即生效
    baseUrl.value = found.baseUrl
    toast.success(`已识别：${found.info}（${found.baseUrl}）`)
  } finally {
    probeState.value = 'idle'
  }
}

async function onTest(): Promise<void> {
  if (probeState.value === 'testing') return
  const base = effectiveBaseUrl.value
  const invalid = validateBaseUrl(base)
  if (invalid) {
    probeResult.value = { kind: 'error', text: invalid }
    return
  }

  probeState.value = 'testing'
  probeResult.value = null
  try {
    const outcome = await probeComfy(base)
    if (outcome.status === 'cancelled') return
    // 请求期间用户改了地址：旧结论已过期，丢弃
    if (effectiveBaseUrl.value !== base) return
    probeResult.value =
      outcome.status === 'ok'
        ? { kind: 'success', text: `连接成功：${outcome.info}` }
        : { kind: 'error', text: outcome.text }
  } finally {
    probeState.value = 'idle'
  }
}

function onReset(): void {
  const fallback = defaultComfyBaseUrl()
  baseUrl.value = fallback
  probeResult.value = null
  toast.info(`已恢复默认地址 ${fallback}`)
}

/** 返回合成台：用路由切页签，剔除已废弃的 shell / path，不整页刷新。 */
function goStudio(): void {
  void router.push({
    path: route.path,
    query: withReferenceTab(route.query, 'studio'),
    hash: route.hash,
  })
}
</script>

<template>
  <section class="settings">
    <header class="settings__head">
      <div class="settings__head-text">
        <!-- 类名与 ReferenceTabPlaceholder / ReferencePosesTab 保持一致：
             既有 ReferenceView.spec 依赖该选择器 -->
        <h1 class="tab-placeholder__title settings__title">设置</h1>
        <p class="settings__desc">
          本地单人使用，仅连接本机 ComfyUI；修改即时生效，无需手动保存。
        </p>
      </div>
      <button class="btn btn-sm primary settings__back" type="button" @click="goStudio">
        返回合成台
      </button>
    </header>

    <section class="settings__section" aria-labelledby="settings-comfy-title">
      <div class="settings__section-head">
        <h2 id="settings-comfy-title" class="settings__section-title">本地 ComfyUI 连接配置</h2>
        <div class="settings__actions">
          <button class="btn btn-sm" type="button" :disabled="isTesting" @click="onDetect">
            自动识别
          </button>
          <button class="btn btn-sm" type="button" :disabled="isTesting" @click="onTest">
            {{ isTesting ? '检测中…' : '测试连接' }}
          </button>
          <button class="btn btn-sm" type="button" :disabled="isTesting" @click="onReset">
            重置
          </button>
        </div>
      </div>

      <label class="settings__field" for="settings-comfy-base-url">
        <span class="settings__label">ComfyUI 地址（Base URL）</span>
        <input
          id="settings-comfy-base-url"
          v-model="baseUrl"
          type="text"
          spellcheck="false"
          autocomplete="off"
          :placeholder="defaultBaseUrl"
          aria-describedby="settings-comfy-hint settings-comfy-current"
        />
      </label>

      <p id="settings-comfy-hint" class="settings__hint">
        留空 = 使用默认 /comfy。默认地址是后端同源反代，无跨域问题。
        直连请填完整地址，如 http://127.0.0.1:8188（便携版）或
        http://127.0.0.1:8000（Desktop 版）；直连要求 ComfyUI 放行跨域（CORS），
        不放行时请继续使用 /comfy。
      </p>
      <p id="settings-comfy-current" class="settings__hint">
        当前生效地址：<code class="settings__code">{{ effectiveBaseUrl }}</code>
      </p>


      <p
        v-if="probeResult"
        class="settings__feedback"
        :class="`is-${probeResult.kind}`"
        role="status"
        aria-live="polite"
      >
        {{ probeResult.text }}
      </p>
    </section>

    <p class="settings__note">
      此地址保存在本浏览器（键 pb.reference_comfy_base_url_v1），供前端探测 ComfyUI
      使用；后端出图链路的 ComfyUI 地址由服务端启动配置决定，本页不修改它。
    </p>
  </section>
</template>

<style scoped>
.settings {
  display: flex;
  flex-direction: column;
  gap: var(--gap-md);
  padding-bottom: var(--gap-sm);
}

.settings__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--gap);
  flex-wrap: wrap;
}

.settings__head-text {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  min-width: 0;
}

.settings__title {
  margin: 0;
  font-size: var(--fs-xl);
  font-weight: 600;
  line-height: var(--lh-xl);
  color: var(--text);
}

.settings__desc {
  margin: 0;
  font-size: var(--fs);
  line-height: var(--lh-md);
  color: var(--text);
}

.settings__back {
  flex: none;
}

.btn.primary {
  border-color: var(--primary);
  background: var(--primary);
  color: var(--on-primary);
}

.btn.primary:disabled {
  opacity: 0.4;
}

/* 分区卡：22px 圆角 / 24px 内边距 / 底 var(--surface-panel)（施工手册 §5 补充实测项）。 */
.settings__section {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  /* 24px 是 §5 实测值；不能换成 --gap-lg（该令牌为 20px） */
  padding: 24px;
  border-radius: 22px;
  background: var(--surface-panel);
}

.settings__section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap);
  flex-wrap: wrap;
}

.settings__section-title {
  margin: 0;
  font-size: var(--fs-lg);
  font-weight: 600;
  line-height: var(--lh-lg);
  color: var(--text);
}

.settings__actions {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  flex-wrap: wrap;
}

.settings__field {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  min-width: 0;
}

/* 标签与正文用主文字色，不用灰色小字压暗层级。 */
.settings__label {
  font-size: var(--fs-sm);
  font-weight: 500;
  color: var(--text);
}

.settings__field input {
  width: 100%;
  min-width: 0;
  font: inherit;
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--gap-sm);
  outline: none;
}

.settings__field input:focus {
  border-color: var(--primary);
}

.settings__hint {
  margin: 0;
  font-size: var(--fs-sm);
  line-height: var(--lh-sm);
  color: var(--muted);
  overflow-wrap: anywhere;
}

.settings__code {
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  background: var(--panel-2);
  color: var(--text);
  font-size: var(--fs-sm);
  overflow-wrap: anywhere;
}

/* 连接结果：成功/失败都给出足够对比度，避免"灰底灰字"看不清。 */
.settings__feedback {
  margin: 0;
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: var(--radius);
  font-size: var(--fs-sm);
  line-height: var(--lh-sm);
  overflow-wrap: anywhere;
}

.settings__feedback.is-success {
  border-color: var(--success-border);
  background: var(--success-surface);
  color: var(--success-text);
}

.settings__feedback.is-error {
  border-color: var(--danger-border-soft);
  background: var(--danger-surface);
  color: var(--danger-text);
}

.settings__note {
  margin: 0;
  font-size: var(--fs-sm);
  line-height: var(--lh-sm);
  color: var(--text);
  overflow-wrap: anywhere;
}

/* 窄屏：压缩分区内边距，按钮换行，避免 390px 出现横向溢出。 */
@media (max-width: 639px) {
  .settings__section {
    padding: var(--gap-md);
    border-radius: var(--radius-lg);
  }

  .settings__head {
    flex-direction: column;
    align-items: stretch;
  }

  .settings__back {
    align-self: flex-start;
  }
}
</style>