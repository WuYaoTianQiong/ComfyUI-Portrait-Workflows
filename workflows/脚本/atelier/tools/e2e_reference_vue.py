#!/usr/bin/env python3
"""参考图库 Vue 版关键路径 E2E 验收脚本（施工手册阶段 4.2）。

覆盖《参考图库_React转Vue统一迁移_施工手册_20261105.md》§8 的 G1–G10。
阶段 3 多选升级后追加 G11「合成台交互」8 项，并扩写 G7「批量组合 / 上限 100 /
空槽提交 / 非 studio 400 / caps 过滤」8 项（见文件内 2026-11-05 增补注释）。
G9 深链组与 G10「产物不含 ref-web」在阶段 4.3 + 4.4（删除 React 子应用、
建立 `/ref-web` → `/reference?tab=` 的 301/302 重定向）之后转正，不再 SKIP；
G9 另补了 query 传递、前缀边界与路径穿越 3 条边界断言（见 §6 实现注意）。

**2026-11-06 已知失效项**：合成台工作流按视觉评分治理后，Flux 系
（`PornMaster_Flux2Klein9B_三图/四图`）已归档到 `历史工作流/未采用/`。
本脚本 G7 的「尺寸档 / 上限 100 / 降级确认框」与 G11 的同名断言都靠它构造
（唯一 caps 支持 quality 且不可裁剪的工作流），因此**这三类断言目前会超时失败**。
保留代码是为了工作流恢复时直接可用；当前跑 G7/G11 请只看其余项。
恢复条件：再引入一个 `caps.quality=true` 或 `input_count > 非空槽且不可裁剪` 的工作流。

**另外**：G7「extra 越界拒绝」用例也会失败 —— 所有现行工作流的 `slots` 都不含 `extra`，
前端已隐藏第 4 张上传入口（`supportsExtraSlot`），页面上没有 `input[type="file"]` 可操作。
恢复条件：把声明 `slots` 含 `extra` 的工作流放回 `图库专用工作流/`。

设计约束（§9 R5）：
- 只用语义选择器：文本、role、aria-label、data-testid；
  不使用 #root、React 类名或构建产物里的 hash 类名；
- 所有断言都输出「期望 / 实测」，便于复核；
- SKIP 必须写明原因，绝不把未执行项写成 PASS（§0 铁律 8）。

用法：
    python tools/e2e_reference_vue.py
    python tools/e2e_reference_vue.py --base http://127.0.0.1:8656
    python tools/e2e_reference_vue.py --only G1,G2
    python tools/e2e_reference_vue.py --only G7,G11 --live-submit

`--live-submit` 默认关闭：打开后 G7 会额外真实提交 1 组（1 张图），
用于验证「前端 → 后端 → 轮询 → 结果图」链路；其余断言仍走 mock。

退出码：
    0  没有 FAIL（允许 SKIP）
    1  存在 FAIL
    2  环境或参数错误（缺 Playwright、--only 分组名非法）
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

if hasattr(sys.stdout, "reconfigure"):
    # Windows 控制台默认 GBK，直接打印中文会抛 UnicodeEncodeError。
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


try:
    from playwright.sync_api import (
        Browser,
        BrowserContext,
        Page,
        Route,
        TimeoutError as PlaywrightTimeoutError,
        sync_playwright,
    )
except ImportError:  # pragma: no cover - 环境错误分支
    print(
        "缺少 Playwright 依赖。原因：当前 Python 解释器无法导入 playwright。"
        "下一步：用项目约定的 Python 执行 `pip install playwright`，"
        "并运行 `python -m playwright install chromium` 后重试。"
    )
    raise SystemExit(2)


# 本脚本位于 脚本/atelier/tools/，PROJECT_ROOT 需上溯三级取到 workflows/ 根
# （tools → atelier → 脚本 → workflows）；下文的 web/ 构建产物断言与
# 文档/日志 截图目录都以它为基准解析，勿随脚本搬迁改动层级。
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BASE = "http://127.0.0.1:8656"
SCREENSHOT_DIR = PROJECT_ROOT / "文档" / "日志" / "refvue-e2e-20261105"

# 四库标识；与 /api/reference/items 的 library 参数一致。
LIBRARIES = ("pose", "costume", "costume-anime", "portrait")

# 18+ 相关存储键（与 useReferenceSafeMode.ts 一致）。
SAFE_MODE_KEY = "pose_atlas_safe_mode_v1"
NSFW_CONFIRMED_KEY = "pose_atlas_nsfw_confirmed_v1"
SHELL_STORAGE_KEY = "pb.reference_shell_v2"

# 1×1 透明 PNG，用于触发第 4 张上传（不落盘、不提交真实任务）。
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
    "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

# 页面初始化脚本：包裹 fetch 统计 /api/reference/items 的分页、并发与条目数。
# 放在 init script 里而不是监听 response 事件，是因为同步 API 的事件回调里
# 读取 response.json() 会阻塞渲染线程，容易拖慢首屏。
INSTRUMENT_JS = r"""
(() => {
  const state = {
    inflight: {},
    peaks: {},
    totals: {},
    pageSizes: {},
    pages: {},
    idSets: {},
    errors: [],
  };
  window.__REF_E2E__ = state;
  const originalFetch = window.fetch;
  window.fetch = async function (input, init) {
    const rawUrl = typeof input === 'string' ? input : (input && input.url) || '';
    if (!rawUrl.includes('/api/reference/items') || rawUrl.includes('/image')) {
      return originalFetch.apply(this, arguments);
    }
    let url;
    try {
      url = new URL(rawUrl, window.location.origin);
    } catch (error) {
      return originalFetch.apply(this, arguments);
    }
    const library = url.searchParams.get('library') || '';
    const page = Number(url.searchParams.get('page') || 0);
    const pageSize = Number(url.searchParams.get('page_size') || 0);
    state.inflight[library] = (state.inflight[library] || 0) + 1;
    state.peaks[library] = Math.max(state.peaks[library] || 0, state.inflight[library]);
    state.pages[library] = state.pages[library] || {};
    state.pages[library][page] = pageSize;
    state.pageSizes[library] = pageSize;
    try {
      const response = await originalFetch.apply(this, arguments);
      try {
        const payload = await response.clone().json();
        if (payload && Array.isArray(payload.items)) {
          state.totals[library] = Number(payload.total) || 0;
          state.idSets[library] = state.idSets[library] || {};
          for (const item of payload.items) {
            if (item && item.id) state.idSets[library][item.id] = true;
          }
        }
      } catch (error) {
        state.errors.push(String(error));
      }
      return response;
    } finally {
      state.inflight[library] -= 1;
    }
  };
})();
"""


# ---------------------------------------------------------------------------
# 结果记录
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    """一条断言的执行结果。status ∈ {PASS, FAIL, SKIP}。"""

    group: str
    name: str
    status: str
    expected: str
    actual: str


@dataclass
class Recorder:
    """收集断言结果并负责最终统计。"""

    only: set[str] | None = None
    results: list[CheckResult] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    #: 是否允许真实提交（默认关闭；全量验收时由 --live-submit 显式打开）。
    live_submit: bool = False

    def enabled(self, group: str) -> bool:
        return self.only is None or group in self.only

    def check(
        self,
        group: str,
        name: str,
        ok: bool,
        expected: str,
        actual: str,
    ) -> bool:
        if not self.enabled(group):
            return False
        result = CheckResult(
            group=group,
            name=name,
            status="PASS" if ok else "FAIL",
            expected=expected,
            actual=actual,
        )
        self.results.append(result)
        self._print(result)
        return ok

    def skip(self, group: str, name: str, expected: str, reason: str) -> None:
        if not self.enabled(group):
            return
        result = CheckResult(
            group=group,
            name=name,
            status="SKIP",
            expected=expected,
            actual=f"未验证：{reason}",
        )
        self.results.append(result)
        self._print(result)

    def fail(self, group: str, name: str, expected: str, actual: str) -> None:
        self.check(group, name, False, expected, actual)

    def _print(self, result: CheckResult) -> None:
        print(
            f"[{result.status}] {result.group} | {result.name} "
            f"| 期望={result.expected} | 实测={result.actual}"
        )

    def summary(self) -> tuple[int, int, int]:
        passed = sum(1 for item in self.results if item.status == "PASS")
        failed = sum(1 for item in self.results if item.status == "FAIL")
        skipped = sum(1 for item in self.results if item.status == "SKIP")
        print()
        print("=" * 78)
        for group in group_order(self.results):
            items = [item for item in self.results if item.group == group]
            p = sum(1 for item in items if item.status == "PASS")
            f = sum(1 for item in items if item.status == "FAIL")
            s = sum(1 for item in items if item.status == "SKIP")
            print(f"{group:<4} 合计 {len(items):>2}  PASS {p:>2}  FAIL {f:>2}  SKIP {s:>2}")
        print("-" * 78)
        print(f"总计 {len(self.results)} 项：PASS {passed} / FAIL {failed} / SKIP {skipped}")
        if self.screenshots:
            print("截图：")
            for path in self.screenshots:
                print(f"  - {path}")
        print("=" * 78)
        return passed, failed, skipped


def group_order(results: Iterable[CheckResult]) -> list[str]:
    """按 G1..G10 的数字顺序排列分组，避免字典插入顺序受执行顺序影响。"""
    groups = {item.group for item in results}
    return sorted(groups, key=lambda value: int(value[1:]) if value[1:].isdigit() else 99)


# ---------------------------------------------------------------------------
# 浏览器会话封装
# ---------------------------------------------------------------------------


class BrowserSession:
    """一个 browser + 一个 context + 一个 page 的轻量封装。"""

    def __init__(self, browser: Browser, base: str, recorder: Recorder) -> None:
        self.browser = browser
        self.base = base.rstrip("/")
        self.recorder = recorder
        self.context: BrowserContext | None = None
        self.page: Page = None  # type: ignore[assignment]

    def open(
        self,
        *,
        viewport: dict[str, int] | None = None,
        init_script: bool = False,
        routes: Iterable[tuple[str, Callable[[Route], None]]] | None = None,
    ) -> Page:
        self.context = self.browser.new_context(
            viewport=viewport or {"width": 1440, "height": 900},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        if init_script:
            self.context.add_init_script(script=INSTRUMENT_JS)
        if routes:
            for pattern, handler in routes:
                self.context.route(pattern, handler)
        self.page = self.context.new_page()
        self.page.set_default_timeout(30_000)
        return self.page

    def close(self) -> None:
        if self.context is not None:
            self.context.close()
            self.context = None

    def url(self, path: str) -> str:
        return f"{self.base}{path}"

    def goto(
        self,
        path: str,
        *,
        wait_selector: str | None = None,
        timeout: int = 60_000,
        wait_until: str = "domcontentloaded",
    ) -> tuple[int, str]:
        """打开页面并返回 (HTTP 状态码, 最终 URL)。"""
        response = self.page.goto(self.url(path), wait_until=wait_until, timeout=timeout)
        status = response.status if response is not None else 0
        if wait_selector:
            self.page.wait_for_selector(wait_selector, state="visible", timeout=timeout)
        return status, self.page.url

    def shoot(self, name: str) -> str:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SCREENSHOT_DIR / f"{name}.png"
        try:
            self.page.screenshot(path=str(path), full_page=False)
        except Exception:  # 截图失败不应让验收中断
            return ""
        self.recorder.screenshots.append(str(path))
        return str(path)


def api_json(base: str, path: str, timeout: float = 20.0) -> dict:
    """直接请求后端 API（脚本侧取期望值，不依赖页面）。"""
    url = f"{base.rstrip('/')}{path}"
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def fetch_all_reference_items(base: str, library: str, timeout: float = 20.0) -> list[dict]:
    """按 200/页拉取某库全部条目，供断言按真实数据统计，不写死数量。"""
    first = api_json(base, f"/api/reference/items?library={library}&page=1&page_size=200", timeout)
    items = list(first.get("items") or [])
    total = int(first.get("total") or 0)
    page_count = (total + 199) // 200
    for page in range(2, page_count + 1):
        payload = api_json(
            base,
            f"/api/reference/items?library={library}&page={page}&page_size=200",
            timeout,
        )
        items.extend(payload.get("items") or [])
    return items


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """禁止 urllib 自动跟随重定向，便于断言 301/302 的状态码与 Location。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401, ANN001
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirectHandler)


def probe_redirect(base: str, path: str, timeout: float = 20.0) -> tuple[int, str]:
    """请求后端且不跟随重定向，返回 (状态码, Location 的 path+query)。

    非重定向响应返回空 Location；网络错误返回 (0, "")，由调用方记 FAIL。
    """
    try:
        with _NO_REDIRECT_OPENER.open(f"{base.rstrip('/')}{path}", timeout=timeout) as response:
            return response.status, ""
    except urllib.error.HTTPError as error:
        location = error.headers.get("Location") or ""
        parsed = urllib.parse.urlsplit(location)
        target = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        return error.code, target
    except urllib.error.URLError:
        return 0, ""


def text_of(page: Page, selector: str) -> str:
    locator = page.locator(selector)
    if locator.count() == 0:
        return ""
    try:
        return locator.first.inner_text().strip()
    except Exception:
        return ""


def attr_all(page: Page, selector: str, attribute: str) -> list[str]:
    return page.locator(selector).evaluate_all(
        "(nodes, name) => nodes.map((node) => node.getAttribute(name) || '')",
        attribute,
    )


def wait_for_items_loaded(page: Page, library: str, timeout: int = 90_000) -> None:
    """等待某库所有分页请求完成且去重条目数达到后端 total。"""
    page.wait_for_function(
        """(library) => {
            const state = window.__REF_E2E__;
            if (!state || typeof state.totals[library] !== 'number') return false;
            const unique = Object.keys(state.idSets[library] || {}).length;
            return unique >= state.totals[library] && !(state.inflight[library] > 0);
        }""",
        arg=library,
        timeout=timeout,
    )


def instrument_snapshot(page: Page) -> dict:
    return page.evaluate(
        """() => {
            const state = window.__REF_E2E__;
            if (!state) return { peaks: {}, counts: {}, totals: {}, pageSizes: {} };
            const counts = {};
            for (const key of Object.keys(state.idSets || {})) {
                counts[key] = Object.keys(state.idSets[key]).length;
            }
            return {
                peaks: state.peaks || {},
                counts,
                totals: state.totals || {},
                pageSizes: state.pageSizes || {},
                pages: state.pages || {},
                errors: state.errors || [],
            };
        }"""
    )


def click_tab(page: Page, label: str) -> None:
    """点击参考图库二级导航里的页签（按 role=tab + 文案）。"""
    page.get_by_role("tab", name=label, exact=True).click()
    page.wait_for_timeout(300)


def open_first_card_lightbox(page: Page, card_testid: str) -> bool:
    """点卡片缩略图打开灯箱；缩略图是 role=button + aria-label「查看大图：…」。"""
    card = page.locator(f'[data-testid="{card_testid}"]').first
    trigger = card.locator('[role="button"][aria-label^="查看大图"]')
    if trigger.count() == 0:
        return False
    trigger.first.click()
    try:
        page.wait_for_selector('[data-testid="reference-lightbox"]', state="visible", timeout=10_000)
    except PlaywrightTimeoutError:
        return False
    return True


def close_lightbox(page: Page) -> None:
    close = page.locator('[data-testid="lightbox-close"]')
    if close.count() > 0:
        try:
            close.first.click()
        except Exception:
            page.keyboard.press("Escape")
    page.wait_for_timeout(200)


def ensure_vue_studio(page: Page, base: str) -> None:
    page.goto(f"{base}/reference?shell=vue&tab=studio", wait_until="domcontentloaded")
    page.wait_for_selector('[data-testid="reference-studio-title"]', state="visible", timeout=60_000)


def read_json_body(route: Route) -> dict:
    try:
        raw = route.request.post_data
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def read_batch_total(page: Page) -> tuple[int | None, int | None, str]:
    """读取常驻的「当前 N / 上限 M」文本，返回 (N, M, 原文)。"""
    text = text_of(page, '[data-testid="studio-batch-total"]')
    match = re.search(r"当前\s*(\d+)\s*/\s*上限\s*(\d+)", text)
    if not match:
        return None, None, text
    return int(match.group(1)), int(match.group(2)), text


def read_slot_counts(page: Page) -> dict[str, int]:
    """读取三槽已选数量徽标；空槽无徽标时按 0 计。"""
    counts: dict[str, int] = {}
    for key in ("portrait", "costume", "pose"):
        badge = page.locator(f'[data-testid="studio-slot-count-{key}"]')
        raw = badge.first.inner_text().strip() if badge.count() else ""
        counts[key] = int(raw) if raw.isdigit() else 0
    return counts


def slot_product(counts: dict[str, int]) -> int:
    """槽位组合数：空槽按 1 计，三槽全空为 0（与前端纯函数同口径）。"""
    dims = [counts["portrait"], counts["costume"], counts["pose"]]
    if all(value <= 0 for value in dims):
        return 0
    total = 1
    for value in dims:
        total *= max(1, value)
    return total


def choose_workflow(page: Page, fragment: str) -> str:
    """展开工作流下拉，按 title 片段选中一项；成功返回触发器 title，失败返回空串。

    只用 role=listbox / role=option 语义定位，不依赖构建产物类名。
    """
    trigger = page.locator('[data-testid="studio-workflow-trigger"]')
    trigger.click()
    listbox = page.get_by_role("listbox", name="本机工作流列表")
    try:
        listbox.wait_for(state="visible", timeout=15_000)
    except PlaywrightTimeoutError:
        return ""
    options = listbox.get_by_role("option")
    target = None
    for index in range(options.count()):
        option = options.nth(index)
        if fragment in (option.get_attribute("title") or ""):
            target = option
            break
    if target is None:
        page.keyboard.press("Escape")
        return ""
    target.click()
    page.wait_for_timeout(500)
    return trigger.get_attribute("title") or ""


def click_chips(page: Page, field_testid: str, *, select: bool) -> list[str]:
    """批量点击画质 / 比例档位。

    `select=True` 只点未选中项（aria-pressed=false），否则只点已选中项。
    返回点击过的按钮文案，便于断言实际点击数量。
    """
    container = page.locator(f'[data-testid="{field_testid}"]')
    if container.count() == 0:
        return []
    buttons = container.locator("button")
    clicked: list[str] = []
    # 点击会切换 aria-pressed；按下标遍历并逐项判断，每项最多点一次。
    total = buttons.count()
    for index in range(total):
        button = buttons.nth(index)
        pressed = button.get_attribute("aria-pressed") == "true"
        if (select and pressed) or (not select and not pressed):
            continue
        button.click()
        clicked.append(button.inner_text().strip())
        page.wait_for_timeout(60)
    return clicked


def click_first_unselected_chip(page: Page, field_testid: str) -> str:
    """点选该字段下第一个未选中的档位，返回其文案；没有可选项时返回空串。"""
    container = page.locator(f'[data-testid="{field_testid}"]')
    if container.count() == 0:
        return ""
    buttons = container.locator("button")
    for index in range(buttons.count()):
        button = buttons.nth(index)
        if button.get_attribute("aria-pressed") == "true":
            continue
        label = button.inner_text().strip()
        button.click()
        page.wait_for_timeout(120)
        return label
    return ""


def post_json_status(base: str, path: str, payload: dict, timeout: float = 30.0) -> tuple[int, str]:
    """POST JSON，返回 (状态码, 响应体文本)；HTTP 错误也读取响应体。"""
    request = urllib.request.Request(
        f"{base.rstrip('/')}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as error:
        return 0, str(error)


# ---------------------------------------------------------------------------
# G1 入口与路由（10 项）
# ---------------------------------------------------------------------------


def run_g1(browser: Browser, base: str, recorder: Recorder) -> None:
    group = "G1"
    if not recorder.enabled(group):
        return

    # 1. /reference 200 且 ?shell=vue 参数被忽略，仍渲染 Vue 版（无 iframe）
    session = BrowserSession(browser, base, recorder)
    try:
        session.open()
        status, _ = session.goto(
            "/reference?shell=vue",
            wait_selector='nav[aria-label="参考图库页签"]',
        )
        iframes = session.page.locator("iframe").count()
        recorder.check(
            group,
            "/reference 200 且 ?shell=vue 被忽略、渲染纯 Vue",
            status == 200 and iframes == 0,
            "HTTP 200，iframe 数 = 0",
            f"HTTP {status}，iframe 数 = {iframes}",
        )
        session.shoot("G1-reference-shell-vue")

        # 2-6. 五页签直达（首页由下一项与未知 tab 合并断言）
        tabs = [
            ("pose", "姿势库"),
            ("costume", "服装库"),
            ("portrait", "人像库"),
            ("studio", "合成台"),
            ("settings", "设置"),
        ]
        for key, heading in tabs:
            status, _ = session.goto(f"/reference?shell=vue&tab={key}", wait_selector="h1")
            actual = text_of(session.page, "h1")
            recorder.check(
                group,
                f"?tab={key} 直达渲染「{heading}」",
                status == 200 and actual == heading,
                f"HTTP 200 且 h1 = {heading}",
                f"HTTP {status} 且 h1 = {actual}",
            )

        # 7. ?tab=home 直达与未知 tab 都归「图库总览」
        session.goto("/reference?shell=vue&tab=home", wait_selector="h1")
        home_h1 = text_of(session.page, "h1")
        session.shoot("G1-tab-home")
        session.goto("/reference?shell=vue&tab=not-a-tab", wait_selector="h1")
        unknown_h1 = text_of(session.page, "h1")
        recorder.check(
            group,
            "?tab=home 直达且未知 tab 回落「图库总览」",
            home_h1 == "图库总览" and unknown_h1 == "图库总览",
            "home 与未知 tab 的 h1 均为图库总览",
            f"home h1={home_h1}，未知 tab h1={unknown_h1}",
        )
    finally:
        session.close()

    # 9. ?shell=iframe 被忽略：阶段 4.3 删除了 iframe 壳，任何 shell 值都渲染纯 Vue。
    session = BrowserSession(browser, base, recorder)
    try:
        session.open()
        session.goto("/reference?shell=iframe", wait_selector='nav[aria-label="参考图库页签"]')
        iframe_count = session.page.locator("iframe").count()
        heading = text_of(session.page, "h1")
        final_url = session.page.url
        recorder.check(
            group,
            "?shell=iframe 被忽略，仍渲染纯 Vue",
            iframe_count == 0 and heading == "图库总览" and "shell=" not in final_url,
            "iframe 数 = 0、h1 = 图库总览、URL 已剔除 shell",
            f"iframe 数 = {iframe_count}，h1 = {heading}，URL = {final_url}",
        )
        session.shoot("G1-shell-iframe-ignored")

        # 10. 旧 localStorage 记忆键（pb.reference_shell_v1/v2）随壳删除而失效：
        # 写入 iframe 后无参访问仍渲染 Vue，不产生 iframe。
        session.page.evaluate(
            f"() => window.localStorage.setItem('{SHELL_STORAGE_KEY}', 'iframe')"
        )
        session.goto("/reference", wait_selector='nav[aria-label="参考图库页签"]')
        legacy_iframes = session.page.locator("iframe").count()
        legacy_heading = text_of(session.page, "h1")
        recorder.check(
            group,
            f"旧存储键 {SHELL_STORAGE_KEY} 已失效",
            legacy_iframes == 0 and legacy_heading == "图库总览",
            "写入 iframe 后无参访问仍无 iframe、h1 = 图库总览",
            f"iframe 数 = {legacy_iframes}，h1 = {legacy_heading}",
        )
    finally:
        session.close()

    # 默认实现检查：阶段 4.1 起默认 vue，阶段 4.3 后不再有 iframe 分支。
    session = BrowserSession(browser, base, recorder)
    try:
        session.open()
        session.goto("/reference", wait_selector='nav[aria-label="参考图库页签"]')
        iframes = session.page.locator("iframe").count()
        actual = text_of(session.page, "h1")
        recorder.check(
            group,
            "无参访问默认渲染 Vue 版",
            iframes == 0 and actual == "图库总览",
            "无 iframe 且 h1 = 图库总览",
            f"iframe 数 = {iframes}，h1 = {actual}",
        )
    finally:
        session.close()


# ---------------------------------------------------------------------------
# G2 三库数据（9 项）
# ---------------------------------------------------------------------------


def run_g2(browser: Browser, base: str, recorder: Recorder) -> None:
    group = "G2"
    if not recorder.enabled(group):
        return

    api_totals = {}
    for library in LIBRARIES:
        payload = api_json(base, f"/api/reference/items?library={library}&page=1&page_size=1")
        api_totals[library] = int(payload.get("total") or 0)

    session = BrowserSession(browser, base, recorder)
    try:
        session.open(init_script=True)
        page = session.page

        # 触发三个页签，让四库各自完成全量分页加载。
        session.goto("/reference?shell=vue&tab=pose", wait_selector='[data-testid="pose-card"]')
        wait_for_items_loaded(page, "pose")
        click_tab(page, "服装")
        page.wait_for_selector('[data-testid="costume-card"]', state="visible", timeout=60_000)
        wait_for_items_loaded(page, "costume")
        wait_for_items_loaded(page, "costume-anime")
        click_tab(page, "人像")
        page.wait_for_selector('[data-testid="portrait-card"]', state="visible", timeout=60_000)
        wait_for_items_loaded(page, "portrait")

        snapshot = instrument_snapshot(page)
        counts = snapshot["counts"]

        # 1-4. 四库条目数与后端 total 一致
        labels = {
            "pose": "姿势库",
            "costume": "服装现实库",
            "costume-anime": "服装二次元库",
            "portrait": "人像库",
        }
        for library in LIBRARIES:
            actual = counts.get(library)
            expected = api_totals[library]
            recorder.check(
                group,
                f"{labels[library]}条目数与 total 一致",
                actual == expected,
                f"页面去重条目 {expected}（后端 total）",
                f"页面去重条目 {actual}，后端 total {expected}",
            )

        # 5. page_size=200 且单库并发峰值 ≤6
        page_sizes = snapshot["pageSizes"]
        peaks = snapshot["peaks"]
        bad_page_size = {k: v for k, v in page_sizes.items() if v != 200}
        bad_peak = {k: v for k, v in peaks.items() if v > 6}
        recorder.check(
            group,
            "分页 page_size=200 且单库并发 ≤6",
            not bad_page_size and not bad_peak,
            "所有库 page_size=200，单库并发峰值 ≤6",
            f"page_size={page_sizes}，并发峰值={peaks}",
        )

        # 6-9. DOM 图片健康度（在服装页执行：图片数量最多）
        click_tab(page, "服装")
        page.wait_for_selector('[data-testid="costume-card"]', state="visible", timeout=60_000)
        page.evaluate(
            """() => {
                document.querySelectorAll('img').forEach((img) => {
                    img.loading = 'eager';
                });
                window.scrollTo(0, document.body.scrollHeight);
            }"""
        )
        page.wait_for_timeout(2000)

        issues = page.evaluate(
            """() => {
                const result = { empty: [], undefinedSrc: [], doubleSlash: [], direct: [], broken: [], checked: 0, depthNonPose: [] };
                const libraryOf = (src) => {
                    const match = src.match(/\\/api\\/reference\\/items\\/([^/]+)\\//);
                    return match ? decodeURIComponent(match[1]) : '';
                };
                document.querySelectorAll('img').forEach((img) => {
                    const src = img.getAttribute('src') || '';
                    const alt = img.getAttribute('alt') || '';
                    if (src === '') result.empty.push(alt);
                    if (src === 'undefined' || src === 'null') result.undefinedSrc.push(src + ':' + alt);
                    if (src.startsWith('//api') || src.includes('//api/')) result.doubleSlash.push(src);
                    if (src.includes('charadb-2fi.pages.dev')) result.direct.push(src);
                    if (/kind=depth/.test(src) && libraryOf(src) && libraryOf(src) !== 'pose') {
                        result.depthNonPose.push(src);
                    }
                    if (src) {
                        result.checked += 1;
                        if (img.complete && img.naturalWidth === 0) result.broken.push(alt || src);
                    }
                });
                document.querySelectorAll('a[href]').forEach((anchor) => {
                    const href = anchor.getAttribute('href') || '';
                    if (href.startsWith('//api') || href.includes('//api/')) result.doubleSlash.push(href);
                    if (href.includes('charadb-2fi.pages.dev')) result.direct.push(href);
                });
                return result;
            }"""
        )

        recorder.check(
            group,
            "无 src='' 或 src='undefined'",
            not issues["empty"] and not issues["undefinedSrc"],
            "空 src 0 个，undefined src 0 个",
            f"空 src {len(issues['empty'])} 个，undefined src {len(issues['undefinedSrc'])} 个",
        )
        recorder.check(
            group,
            "图片/链接无 //api 二次拼接",
            not issues["doubleSlash"],
            "//api 出现 0 次",
            f"//api 出现 {len(issues['doubleSlash'])} 次：{issues['doubleSlash'][:2]}",
        )
        recorder.check(
            group,
            "无直连 charadb-2fi.pages.dev",
            not issues["direct"],
            "直连上游域名 0 次",
            f"直连 {len(issues['direct'])} 次",
        )
        recorder.check(
            group,
            "已加载图片裂图 0",
            issues["checked"] > 0 and not issues["broken"],
            "检查图片数 > 0 且裂图 0",
            f"检查 {issues['checked']} 张，裂图 {len(issues['broken'])} 张：{issues['broken'][:3]}",
        )
        session.shoot("G2-costume-grid")
    except PlaywrightTimeoutError as error:
        recorder.fail(group, "三库数据加载", "四库分页在 90s 内完成", f"超时：{error}")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# G3 姿势特性（9 项）
# ---------------------------------------------------------------------------


def run_g3(browser: Browser, base: str, recorder: Recorder) -> None:
    group = "G3"
    if not recorder.enabled(group):
        return

    # 18+ 后缀是否可见取决于「是否有敏感条目」与「安全模式是否默认隐藏」，
    # 两者都按真实数据统计，避免把当前数据面写死成 nsfw=0。
    pose_items = fetch_all_reference_items(base, "pose")
    pose_nsfw_count = sum(1 for item in pose_items if item.get("nsfw") is True)

    session = BrowserSession(browser, base, recorder)
    try:
        session.open()
        page = session.page
        session.goto("/reference?shell=vue&tab=pose", wait_selector='[data-testid="pose-card"]')
        page.wait_for_selector('[data-testid="pose-card"]', state="visible", timeout=60_000)

        cards = page.locator('[data-testid="pose-card"]')
        card_count = cards.count()

        # 1. 按「体系|姿势编号」分组：组数 = 前 60 组
        expected_groups = min(60, card_count)
        recorder.check(
            group,
            "按姿势编号分组（首屏 60 组）",
            card_count == 60,
            "首屏分组卡 = 60",
            f"首屏分组卡 = {card_count}（期望 {expected_groups}）",
        )

        # 2. 同组多角度：绝大多数分组卡的角度条至少 2 个角度
        multi_angle = 0
        sample = min(20, card_count)
        for index in range(sample):
            angle_buttons = cards.nth(index).locator("[data-angle]").count()
            if angle_buttons >= 2:
                multi_angle += 1
        recorder.check(
            group,
            "同组多角度切换（角度条 ≥2 个角度）",
            sample > 0 and multi_angle >= sample * 0.8,
            f"抽样 {sample} 组中 ≥80% 有 2 个以上角度",
            f"抽样 {sample} 组，有 {multi_angle} 组满足",
        )

        # 3. 5 角度顺序
        angle_texts = [
            text.strip()
            for text in page.locator('[data-testid="pose-angles"] button').all_text_contents()
        ]
        expected_angles = ["全部视角", "正面", "俯视", "仰视", "侧面", "斜侧"]
        recorder.check(
            group,
            "角度顺序为 正面/俯视/仰视/侧面/斜侧",
            angle_texts == expected_angles,
            f"{expected_angles}",
            f"{angle_texts}",
        )

        # 4. 深度图端点：切到深度图后卡片图片走 kind=depth*
        page.locator('[data-testid="pose-depth-toggle"]').get_by_role(
            "button", name="深度图 (Depth)", exact=True
        ).click()
        page.wait_for_timeout(800)
        depth_srcs = page.locator('[data-testid="pose-card"] img').evaluate_all(
            "(nodes) => nodes.map((node) => node.getAttribute('src') || '')"
        )
        depth_hits = [src for src in depth_srcs if "kind=depth" in src]
        recorder.check(
            group,
            "深度图请求 kind=depth* 且仅 pose 端点",
            bool(depth_hits)
            and all("/api/reference/items/pose/" in src for src in depth_hits),
            "存在 kind=depth 图片且路径含 /items/pose/",
            f"depth 图片 {len(depth_hits)} 张，样例={depth_hits[:1]}",
        )
        session.shoot("G3-pose-depth")

        # 5. 白模切换：切回素体白模后不再出现 depth
        page.locator('[data-testid="pose-depth-toggle"]').get_by_role(
            "button", name="素体白模", exact=True
        ).click()
        page.wait_for_timeout(800)
        normal_srcs = page.locator('[data-testid="pose-card"] img').evaluate_all(
            "(nodes) => nodes.map((node) => node.getAttribute('src') || '')"
        )
        recorder.check(
            group,
            "白模/深度图切换生效",
            bool(normal_srcs) and not any("kind=depth" in src for src in normal_srcs),
            "切回白模后卡片 src 不含 kind=depth",
            f"仍含 depth 的图片 {sum(1 for src in normal_srcs if 'kind=depth' in src)} 张",
        )

        # 6. 灯箱内深度切换
        opened = open_first_card_lightbox(page, "pose-card")
        has_lightbox_depth = (
            opened and page.locator('[data-testid="lightbox-depth-toggle"]').count() > 0
        )
        recorder.check(
            group,
            "灯箱内提供深度图切换",
            has_lightbox_depth,
            "灯箱存在 lightbox-depth-toggle",
            f"灯箱打开={opened}，切换条存在={has_lightbox_depth}",
        )
        close_lightbox(page)

        # 7. 分组 / 单张视图切换
        page.locator('[data-testid="pose-view-single"]').click()
        page.wait_for_selector('[data-testid="pose-card-single"]', state="visible", timeout=60_000)
        single_count = page.locator('[data-testid="pose-card-single"]').count()
        page.locator('[data-testid="pose-view-group"]').click()
        page.wait_for_selector('[data-testid="pose-card"]', state="visible", timeout=60_000)
        recorder.check(
            group,
            "分组/单张视图切换",
            single_count >= 60,
            "单张视图首屏 ≥60 张",
            f"单张视图 {single_count} 张",
        )

        # 8. 加载更多文案（+60，不是分页）
        more = page.get_by_role("button", name=re.compile(r"加载更多（剩余 \d+ 组）"))
        has_more = more.count() > 0
        more_text = more.first.inner_text().strip() if has_more else ""
        recorder.check(
            group,
            "加载更多文案带剩余组数（+60）",
            has_more and "加载更多（剩余" in more_text,
            "按钮文案形如「加载更多（剩余 N 组）」",
            f"文案={more_text or '未找到'}",
        )

        # 9. 18+ 体系标记：按真实 nsfw 数据与安全模式默认态动态说明。
        if pose_nsfw_count:
            suffix_reason = (
                f"实测姿势库含 {pose_nsfw_count} 条 nsfw=true 条目（共 {len(pose_items)} 条），"
                "但安全模式默认开启，页面在未解锁时整体隐藏这些体系，"
                "运行态不渲染「 · 18+」后缀；本组未在解锁后复测该后缀，"
                "故按未验证处理（G6 已单独验证解锁流程）"
            )
        else:
            suffix_reason = (
                f"实测姿势库 nsfw 条目为 0（共 {len(pose_items)} 条），"
                "运行态不渲染该元素"
            )
        recorder.skip(
            group,
            "体系药丸 18+ 文本后缀",
            "含 18+ 条目且解锁后出现「 · 18+」后缀",
            suffix_reason,
        )
        session.shoot("G3-pose-grid")
    except PlaywrightTimeoutError as error:
        recorder.fail(group, "姿势库加载", "姿势库在 60s 内渲染", f"超时：{error}")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# G4 服装特性（7 项）
# ---------------------------------------------------------------------------


def run_g4(browser: Browser, base: str, recorder: Recorder) -> None:
    group = "G4"
    if not recorder.enabled(group):
        return

    session = BrowserSession(browser, base, recorder)
    try:
        session.open()
        page = session.page
        session.goto("/reference?shell=vue&tab=costume", wait_selector='[data-testid="costume-card"]')
        page.wait_for_selector('[data-testid="costume-card"]', state="visible", timeout=60_000)

        def libraries() -> list[str]:
            return attr_all(page, '[data-testid="costume-card"]', "data-library")

        first_batch = libraries()[:60]
        recorder.check(
            group,
            "双库合并现实在前（首屏 60 张）",
            bool(first_batch) and all(value == "costume" for value in first_batch),
            "前 60 张 data-library 全为 costume",
            f"前 {len(first_batch)} 张中非 costume "
            f"{sum(1 for value in first_batch if value != 'costume')} 张",
        )

        # 加载更多直到第 1069 张可见；现实库 1068 张，第 1069 张应为二次元。
        more_button = page.get_by_role("button", name=re.compile(r"加载更多（剩余"))
        for _ in range(25):
            if page.locator('[data-testid="costume-card"]').count() >= 1069:
                break
            if more_button.count() == 0:
                break
            more_button.first.click()
            page.wait_for_timeout(180)

        merged = libraries()
        boundary_ok = (
            len(merged) >= 1069
            and merged[1067] == "costume"
            and merged[1068] == "costume-anime"
        )
        recorder.check(
            group,
            "第 1069 张起为二次元库",
            boundary_ok,
            "第 1068 张=costume，第 1069/1070 张起=costume-anime",
            f"总卡片 {len(merged)}；第 1068 张={(merged[1067] if len(merged) > 1067 else '缺失')}，"
            f"第 1069 张={(merged[1068] if len(merged) > 1068 else '缺失')}",
        )
        session.shoot("G4-costume-merged-1069")

        kinds = page.locator('[data-testid="costume-kinds"]').get_by_role("button")

        # 一级分类：现实 / 二次元 双向收窄
        kinds.filter(has_text="现实").first.click()
        page.wait_for_timeout(800)
        reality_libs = libraries()
        kinds.filter(has_text="二次元").first.click()
        page.wait_for_timeout(800)
        anime_libs = libraries()
        reality_ok = bool(reality_libs) and all(value == "costume" for value in reality_libs)
        anime_ok = bool(anime_libs) and all(value == "costume-anime" for value in anime_libs)
        recorder.check(
            group,
            "一级分类「现实/二次元」双向收窄",
            reality_ok and anime_ok,
            "「现实」下全为 costume，「二次元」下全为 costume-anime",
            f"现实下非 costume {sum(1 for value in reality_libs if value != 'costume')}"
            f"/{len(reality_libs)}；二次元下非 anime "
            f"{sum(1 for value in anime_libs if value != 'costume-anime')}/{len(anime_libs)}",
        )

        # 外链标注：二次元条目灯箱显示「二次元素材 · 仅作参考」与来源入口
        opened = open_first_card_lightbox(page, "costume-card")
        page.wait_for_timeout(600)
        actions = page.locator('[data-testid="costume-actions"]')
        actions_text = actions.inner_text().strip() if actions.count() > 0 else ""
        has_source_link = (
            page.locator('[data-testid="costume-source-image"]').count() > 0
            or page.locator('[data-testid="costume-author-site"]').count() > 0
        )
        recorder.check(
            group,
            "外链来源标注（CharaDB / 仅作参考 / 来源入口）",
            opened and "二次元素材 · 仅作参考" in actions_text and has_source_link,
            "操作条含「二次元素材 · 仅作参考」且至少有前往来源原图/原作者站点",
            f"操作条文本={actions_text[:60]}，来源入口={has_source_link}",
        )

        # 外链无 download
        download_links = page.locator('[data-testid="costume-download"]').count()
        any_download = page.locator('[data-testid="reference-lightbox"] a[download]').count()
        recorder.check(
            group,
            "外链只读不可下载",
            download_links == 0 and any_download == 0,
            "外链条目无 costume-download，灯箱无 download 链接",
            f"costume-download={download_links}，灯箱 download 链接={any_download}",
        )
        close_lightbox(page)

        # 现实条目可下载
        kinds.filter(has_text="现实").first.click()
        page.wait_for_timeout(800)
        open_first_card_lightbox(page, "costume-card")
        page.wait_for_timeout(600)
        reality_download = page.locator('[data-testid="costume-download"]')
        reality_ok = (
            reality_download.count() > 0
            and bool(reality_download.first.get_attribute("download"))
        )
        recorder.check(
            group,
            "现实条目提供下载高清原图",
            reality_ok,
            "存在 costume-download 且 download 属性非空",
            f"按钮数={reality_download.count()}，download 属性="
            f"{reality_download.first.get_attribute('download') if reality_download.count() else '无'}",
        )
        session.shoot("G4-costume-reality-lightbox")
    except PlaywrightTimeoutError as error:
        recorder.fail(group, "服装库加载", "服装库在 60s 内渲染", f"超时：{error}")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# G5 人像特性（6 项）
# ---------------------------------------------------------------------------


def run_g5(browser: Browser, base: str, recorder: Recorder) -> None:
    group = "G5"
    if not recorder.enabled(group):
        return

    session = BrowserSession(browser, base, recorder)
    try:
        session.open()
        page = session.page
        session.goto("/reference?shell=vue&tab=portrait", wait_selector='[data-testid="portrait-card"]')
        page.wait_for_selector('[data-testid="portrait-card"]', state="visible", timeout=60_000)

        pills = page.locator('[data-testid="portrait-pills"]')
        section_values = attr_all(page, '[data-testid="portrait-pills"] [data-section]', "data-section")
        hair_values = attr_all(page, '[data-testid="portrait-pills"] [data-hair]', "data-hair")
        all_text = pills.inner_text().strip()

        recorder.check(
            group,
            "分区/发长药丸齐全（全部/正脸参考/造型氛围 + 发长）",
            "全部人像" in all_text and bool(section_values) and bool(hair_values),
            "含「全部人像」、≥1 个分区、≥1 个发长",
            f"分区={section_values[:4]}，发长={hair_values[:5]}",
        )

        total_all = page.locator('[data-testid="portrait-card"]').count()
        target_section = section_values[0] if section_values else ""
        section_pill = (
            page.locator(f'[data-testid="portrait-pills"] [data-section="{target_section}"]').first
        )
        section_pill.click()
        page.wait_for_timeout(600)
        section_cards = page.locator('[data-testid="portrait-card"]')
        section_texts = [text for text in section_cards.all_text_contents()]
        section_ok = bool(target_section) and len(section_texts) > 0 and all(
            target_section in text for text in section_texts
        )
        recorder.check(
            group,
            f"分区筛选「{target_section}」收窄",
            section_ok,
            f"筛选后所有卡片含分区「{target_section}」",
            f"卡片 {len(section_texts)} 张，不含目标分区 "
            f"{sum(1 for text in section_texts if target_section not in text)} 张",
        )

        # 二次点击取消
        section_pill.click()
        page.wait_for_timeout(600)
        after_cancel = page.locator('[data-testid="portrait-card"]').count()
        pressed = section_pill.get_attribute("aria-pressed")
        recorder.check(
            group,
            "分区药丸二次点击取消",
            pressed == "false" and after_cancel == total_all,
            f"aria-pressed=false 且卡片恢复到 {total_all}",
            f"aria-pressed={pressed}，卡片 {after_cancel} 张",
        )

        target_hair = hair_values[0] if hair_values else ""
        hair_pill = page.locator(f'[data-testid="portrait-pills"] [data-hair="{target_hair}"]').first
        hair_pill.click()
        page.wait_for_timeout(600)
        hair_cards = page.locator('[data-testid="portrait-card"]')
        hair_texts = hair_cards.all_text_contents()
        hair_ok = bool(target_hair) and len(hair_texts) > 0 and all(
            target_hair in text for text in hair_texts
        )
        recorder.check(
            group,
            f"发长筛选「{target_hair}」收窄",
            hair_ok,
            f"筛选后所有卡片含发长「{target_hair}」",
            f"卡片 {len(hair_texts)} 张，不含目标发长 "
            f"{sum(1 for text in hair_texts if target_hair not in text)} 张",
        )

        hair_pill.click()
        page.wait_for_timeout(600)
        after_hair_cancel = page.locator('[data-testid="portrait-card"]').count()
        recorder.check(
            group,
            "发长药丸二次点击取消",
            hair_pill.get_attribute("aria-pressed") == "false" and after_hair_cancel == total_all,
            f"aria-pressed=false 且卡片恢复到 {total_all}",
            f"aria-pressed={hair_pill.get_attribute('aria-pressed')}，"
            f"卡片 {after_hair_cancel} 张",
        )

        # 反向断言：§7 冻结「精选/热门」不迁移
        body_text = page.locator("body").inner_text()
        recorder.check(
            group,
            "不渲染精选/热门标记（§7 冻结为不迁移）",
            "精选" not in body_text and "热门" not in body_text,
            "页面文本不含「精选」「热门」",
            f"含精选={'精选' in body_text}，含热门={'热门' in body_text}",
        )
        session.shoot("G5-portrait-grid")
    except PlaywrightTimeoutError as error:
        recorder.fail(group, "人像库加载", "人像库在 60s 内渲染", f"超时：{error}")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# G6 18+ 语义（6 项）
# ---------------------------------------------------------------------------


def run_g6(browser: Browser, base: str, recorder: Recorder) -> None:
    group = "G6"
    if not recorder.enabled(group):
        return

    # 先直连读真实总闸，不经过浏览器路由；后续断言与是否拦截都以它为准。
    gate_payload = api_json(base, "/api/reference/libraries")
    raw_allow_nsfw = gate_payload.get("allow_nsfw")
    real_allow_nsfw = raw_allow_nsfw if isinstance(raw_allow_nsfw, bool) else None
    if real_allow_nsfw is True:
        gate_source = "真实后端 allow_nsfw=true"
    elif real_allow_nsfw is False:
        gate_source = "模拟 allow_nsfw=true（真实后端为 false，弹窗流程用拦截验证）"
    else:
        gate_source = f"真实后端 allow_nsfw={raw_allow_nsfw!r}（非布尔值，按 true 模拟）"

    # 为了端到端验证弹窗与「只弹一次」，需要 allow_nsfw=true：
    # - 真实值就是 true：不拦截，直接测真实环境；
    # - 真实值为 false / 未知：才在测试 context 内拦截响应模拟 true，
    #   不改后端进程与源码，并在断言实测文案里标注模拟来源。
    def allow_nsfw_route(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        payload["allow_nsfw"] = True
        for library in payload.get("libraries", []):
            if isinstance(library, dict):
                library["allow_nsfw"] = True
        route.fulfill(
            status=200,
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload, ensure_ascii=False),
        )

    gate_routes = None if real_allow_nsfw is True else [("**/api/reference/libraries", allow_nsfw_route)]

    session = BrowserSession(browser, base, recorder)
    try:
        session.open(routes=gate_routes)
        page = session.page
        session.goto("/reference?shell=vue&tab=pose", wait_selector='[data-testid="pose-safe-toggle"]')
        toggle = page.locator('[data-testid="pose-safe-toggle"]')
        page.wait_for_function(
            """() => {
                const node = document.querySelector('[data-testid="pose-safe-toggle"]');
                return node && node.getAttribute('data-gate') === 'open';
            }""",
            timeout=20_000,
        )

        # 1. 默认安全模式开启
        recorder.check(
            group,
            "默认安全模式开启",
            toggle.get_attribute("data-safe") == "1" and "安全模式 (SFW)" in toggle.inner_text(),
            "data-safe=1 且文案为「安全模式 (SFW)」",
            f"data-safe={toggle.get_attribute('data-safe')}，"
            f"文案={toggle.inner_text().strip()}；{gate_source}",
        )

        # 2. 存储键缺省 true（未写入 safe mode 值）
        stored_safe = page.evaluate(f"() => window.localStorage.getItem('{SAFE_MODE_KEY}')")
        recorder.check(
            group,
            f"{SAFE_MODE_KEY} 缺省为 true",
            stored_safe is None and toggle.get_attribute("data-safe") == "1",
            "localStorage 无该键且 UI 为安全模式",
            f"localStorage 值={stored_safe}",
        )

        # 3. 首次解锁弹年龄确认
        toggle.click()
        page.wait_for_selector('[data-testid="age-gate-confirm"]', state="visible", timeout=10_000)
        gate_title = text_of(page, "h2")
        recorder.check(
            group,
            "首次解锁弹出 18+ 年龄确认（只此一次）",
            "18+ 内容确认" in gate_title,
            "弹窗标题 = 18+ 内容确认",
            f"弹窗标题 = {gate_title}",
        )
        session.shoot("G6-age-gate-first")

        # 4. 确认后写确认标记
        page.locator('[data-testid="age-gate-confirm"]').click()
        page.wait_for_timeout(600)
        confirmed = page.evaluate(f"() => window.localStorage.getItem('{NSFW_CONFIRMED_KEY}')")
        after_confirm_text = toggle.inner_text().strip()
        recorder.check(
            group,
            f"确认后写入 {NSFW_CONFIRMED_KEY}=true",
            confirmed == "true" and "18+ 完整模式" in after_confirm_text,
            "localStorage=true 且按钮切到 18+ 完整模式",
            f"localStorage={confirmed}，按钮={after_confirm_text}",
        )

        # 5. 切回安全模式不重置；再解锁不再弹窗
        toggle.click()  # 18+ -> 安全模式
        page.wait_for_timeout(400)
        confirmed_after_switch = page.evaluate(
            f"() => window.localStorage.getItem('{NSFW_CONFIRMED_KEY}')"
        )
        toggle.click()  # 安全模式 -> 再解锁，应直接放行
        page.wait_for_timeout(900)
        gate_visible = page.locator('[data-testid="age-gate-confirm"]').count() > 0
        recorder.check(
            group,
            "切回安全模式不重置确认标记，二次解锁不弹窗",
            confirmed_after_switch == "true"
            and not gate_visible
            and "18+ 完整模式" in toggle.inner_text(),
            "确认标记仍为 true，二次解锁无弹窗并进入 18+ 模式",
            f"切回后标记={confirmed_after_switch}，二次解锁弹窗={gate_visible}，"
            f"按钮={toggle.inner_text().strip()}",
        )
    except PlaywrightTimeoutError as error:
        recorder.fail(group, "18+ 弹窗流程", "弹窗在 10s 内出现", f"超时：{error}")
    finally:
        session.close()

    # 6. 真实后端总闸：按 /api/reference/libraries 的真实 allow_nsfw 动态判定。
    # 不写死 false：启动.bat 默认 ATELIER_REFERENCE_ALLOW_NSFW=1，此时应断言可用。
    if real_allow_nsfw is None:
        recorder.fail(
            group,
            "后端总闸 allow_nsfw 动态判定",
            "读到布尔值 allow_nsfw",
            f"实测={raw_allow_nsfw!r}（/api/reference/libraries）",
        )
        return

    session = BrowserSession(browser, base, recorder)
    try:
        session.open()
        page = session.page
        session.goto("/reference?shell=vue&tab=pose", wait_selector='[data-testid="pose-safe-toggle"]')
        toggle = page.locator('[data-testid="pose-safe-toggle"]')
        expected_gate = "open" if real_allow_nsfw else "closed"
        page.wait_for_function(
            """(expected) => {
                const node = document.querySelector('[data-testid="pose-safe-toggle"]');
                return node && node.getAttribute('data-gate') === expected;
            }""",
            arg=expected_gate,
            timeout=20_000,
        )
        title = toggle.get_attribute("title") or ""
        disabled = toggle.is_disabled()
        actual_gate = toggle.get_attribute("data-gate") or ""

        if real_allow_nsfw:
            # 真实总闸开启：解锁入口应可用，点击应弹出年龄确认。
            clicked_gate = False
            try:
                toggle.click()
                page.wait_for_selector(
                    '[data-testid="age-gate-confirm"]', state="visible", timeout=10_000
                )
                clicked_gate = True
            except PlaywrightTimeoutError:
                clicked_gate = False
            recorder.check(
                group,
                "后端总闸 allow_nsfw=true（实测）时解锁入口可用",
                not disabled
                and actual_gate == "open"
                and "总闸已关闭" not in title
                and clicked_gate,
                "按钮可点击、data-gate=open、title 不含「总闸已关闭」且点击弹出年龄确认",
                f"disabled={disabled}，data-gate={actual_gate}，title={title}，"
                f"点击弹窗={clicked_gate}",
            )
            session.shoot("G6-safe-gate-open")
        else:
            # 真实总闸关闭：解锁入口必须置灰，且给出总闸关闭文案。
            recorder.check(
                group,
                "后端总闸 allow_nsfw=false（实测）时解锁入口置灰",
                disabled and actual_gate == "closed" and "总闸已关闭" in title,
                "按钮 disabled、data-gate=closed 且 title 含「总闸已关闭」",
                f"disabled={disabled}，data-gate={actual_gate}，title={title}",
            )
            session.shoot("G6-safe-gate-closed")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# G7 合成台（14 项）
# ---------------------------------------------------------------------------


def run_g7(browser: Browser, base: str, recorder: Recorder) -> None:
    group = "G7"
    if not recorder.enabled(group):
        return

    workflow_catalog = api_json(base, "/api/workflows?scope=studio")
    expected_default = str(workflow_catalog.get("default") or "")
    recommended_paths = {
        item.get("path")
        for item in workflow_catalog.get("workflows", [])
        if item.get("recommended") is True
    }

    captured_bodies: list[dict] = []
    poll_counter = {"value": 0}

    def recipes_route(route: Route) -> None:
        captured_bodies.append(read_json_body(route))
        route.fulfill(
            status=200,
            headers={"Content-Type": "application/json"},
            body=json.dumps({"success": True, "job_id": 999001, "errors": []}),
        )

    def jobs_route(route: Route) -> None:
        """轮询端点 /api/jobs/{id}：第一次返回 running，其后返回 done + 结果图。"""
        poll_counter["value"] += 1
        if poll_counter["value"] <= 1:
            payload = {
                "id": 999001,
                "status": "running",
                "total": 1,
                "done_count": 0,
                "items": [],
            }
        else:
            payload = {
                "id": 999001,
                "status": "done",
                "total": 1,
                "done_count": 1,
                "items": [
                    {
                        "images": [
                            {"filename": "e2e-mock.png", "subfolder": "", "type": "output"}
                        ]
                    }
                ],
            }
        route.fulfill(
            status=200,
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload, ensure_ascii=False),
        )

    def uploads_route(route: Route) -> None:
        # 故意返回 uploads 目录之外的路径，触发前端越界拦截。
        payload = {
            "path": "C:\\Windows\\Temp\\e2e-not-uploads.png",
            "name": "e2e-not-uploads.png",
            "width": 1,
            "height": 1,
            "bytes": len(TINY_PNG),
            "dedup": False,
        }
        route.fulfill(
            status=200,
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload, ensure_ascii=False),
        )

    session = BrowserSession(browser, base, recorder)
    try:
        session.open(routes=[
            ("**/api/reference/recipes**", recipes_route),
            ("**/api/jobs/999001", jobs_route),
            ("**/api/reference/uploads", uploads_route),
        ])
        page = session.page
        ensure_vue_studio(page, base)

        # 1. 三槽位卡存在
        slot_ids = ["portrait", "costume", "pose"]
        slot_counts = {
            key: page.locator(f'[data-testid="studio-slot-{key}"]').count() for key in slot_ids
        }
        recorder.check(
            group,
            "三槽位（人像/服装/姿势）存在",
            all(value == 1 for value in slot_counts.values()),
            "studio-slot-portrait/costume/pose 各 1 个",
            f"{slot_counts}",
        )

        # 2. 空槽位 aria-label 语义
        empty_arias = {
            key: page.locator(f'[data-testid="studio-slot-{key}"]').get_attribute("aria-label") or ""
            for key in slot_ids
        }
        recorder.check(
            group,
            "空槽位用无障碍标签表达「未选择」",
            all("未选择" in value for value in empty_arias.values()),
            "三个槽位 aria-label 均含「未选择」",
            f"{empty_arias}",
        )

        # 3. 缺槽位时提交按钮禁用
        generate = page.locator('[data-testid="studio-generate"]')
        recorder.check(
            group,
            "缺槽位时「生成角色图」禁用",
            generate.is_disabled(),
            "按钮 disabled",
            f"disabled={generate.is_disabled()}，文案={generate.inner_text().strip()}",
        )

        # 4. 工作流下拉默认值 = 后端 default
        trigger = page.locator('[data-testid="studio-workflow-trigger"]')
        page.wait_for_function(
            """() => {
                const node = document.querySelector('[data-testid="studio-workflow-trigger"]');
                return node && (node.getAttribute('title') || '') !== '选择工作流';
            }""",
            timeout=30_000,
        )
        actual_default = trigger.get_attribute("title") or ""
        recorder.check(
            group,
            "工作流下拉默认值 = 后端 default",
            bool(expected_default) and actual_default == expected_default,
            f"title = {expected_default}",
            f"title = {actual_default}",
        )

        # 5. 推荐徽章：默认项未必是推荐项，因此展开下拉选中推荐项后再断言。
        trigger.click()
        page.wait_for_selector(
            '[role="listbox"][aria-label="本机工作流列表"]', state="visible", timeout=15_000
        )
        recommended_options = page.get_by_role("option", name=re.compile("推荐"))
        option_count = recommended_options.count()
        if option_count == 0:
            recorder.skip(
                group,
                "推荐工作流显示「推荐」徽章",
                "选择 recommended 工作流后触发器显示「推荐」",
                f"后端 default={expected_default}，但列表中没有 recommended 项"
                "（/api/workflows 当前 recommended 集合为空或未被下拉渲染）",
            )
        else:
            recommended_options.first.click()
            page.wait_for_timeout(400)
            badge = page.locator('[data-testid="studio-workflow-recommended"]')
            selected_title = trigger.get_attribute("title") or ""
            recorder.check(
                group,
                "推荐工作流显示「推荐」徽章",
                badge.count() > 0 and selected_title in recommended_paths,
                "下拉含「推荐」项，选中后触发器显示「推荐」徽章",
                f"推荐项 {option_count} 个，选中 title={selected_title}，徽章数={badge.count()}",
            )

        # 6-7. 画风下拉
        style_select = page.locator('[data-testid="studio-style"]')
        style_options = style_select.locator("option").all_text_contents()
        recorder.check(
            group,
            "画风预设仅 none/realistic 两项",
            style_options == ["无预设（跟随参考图）", "写实人像写真"],
            "两个选项：无预设（跟随参考图）/ 写实人像写真",
            f"{style_options}",
        )
        recorder.check(
            group,
            "画风默认 realistic",
            style_select.input_value() == "realistic",
            "默认值 = realistic",
            f"默认值 = {style_select.input_value()}",
        )

        # 3'. 随机捏人填满三槽
        page.locator('[data-testid="studio-random"]').click()
        page.wait_for_function(
            """() => {
                const node = document.querySelector('[data-testid="studio-recipe-count"]');
                return node && node.textContent.trim() === '3/3';
            }""",
            timeout=60_000,
        )
        count_label = text_of(page, '[data-testid="studio-recipe-count"]')
        slot_imgs = page.evaluate(
            """() => {
                const keys = ['portrait', 'costume', 'pose'];
                return keys.map((key) => {
                    const slot = document.querySelector('[data-testid="studio-slot-' + key + '"]');
                    const img = slot ? slot.querySelector('img') : null;
                    return img ? (img.getAttribute('src') || '') : '';
                });
            }"""
        )
        recorder.check(
            group,
            "随机捏人填满三槽且各有预览图",
            count_label == "3/3" and all(slot_imgs),
            "配方计数 3/3，三槽图片 src 非空",
            f"计数={count_label}，槽位图片={slot_imgs}",
        )

        # 确保服装槽为现实库：点服装槽 -> 服装页 -> 一级分类「现实」-> 加入配方
        def select_costume_kind(kind: str) -> bool:
            page.locator('[data-testid="studio-slot-costume"]').click()
            page.wait_for_selector('[data-testid="costume-kinds"]', state="visible", timeout=60_000)
            kind_button = page.locator('[data-testid="costume-kinds"]').get_by_role(
                "button", name=kind, exact=True
            )
            if kind_button.count() == 0:
                return False
            kind_button.first.click()
            page.wait_for_timeout(700)
            card = page.locator('[data-testid="costume-card"]').first
            select_button = card.get_by_role("button", name=re.compile("加入配方"))
            if select_button.count() == 0:
                return False
            select_button.first.click()
            # 多选升级后点「加入配方」只 toggle、不再自动回合成台，
            # 必须显式点页签返回，否则后续断言会停在服装页。
            page.get_by_role("tab", name="合成台", exact=True).click()
            page.wait_for_selector('[data-testid="reference-studio"]', state="visible", timeout=20_000)
            page.wait_for_timeout(600)
            return True

        select_costume_kind("现实")

        # 8. 填补充要求与画风
        suffix_text = "E2E 补充要求：暖色灯光、浅景深"
        page.locator('[data-testid="studio-prompt-suffix"]').fill(suffix_text)
        style_select.select_option("none")
        page.wait_for_timeout(200)

        # 9-11. 拦截 POST 断言提交体（不真实提交）
        generate.click()
        page.wait_for_timeout(800)
        first_body = captured_bodies[-1] if captured_bodies else {}
        recorder.check(
            group,
            "提交体含三槽 id 且 costume_library=costume",
            all(first_body.get(key) for key in ("portrait_id", "costume_id", "pose_id"))
            and first_body.get("costume_library") == "costume",
            "portrait_id/costume_id/pose_id 非空，costume_library=costume",
            f"{ {key: first_body.get(key) for key in ('portrait_id', 'costume_id', 'pose_id', 'costume_library')} }",
        )
        recorder.check(
            group,
            "prompt_suffix 进入提交体",
            first_body.get("prompt_suffix") == suffix_text,
            f"prompt_suffix = {suffix_text}",
            f"prompt_suffix = {first_body.get('prompt_suffix')}",
        )
        recorder.check(
            group,
            "画风/种子字段进入提交体",
            first_body.get("style") == "none"
            and isinstance(first_body.get("seed"), int)
            and first_body.get("seed_mode") == "fixed",
            "style=none，seed 为整数，seed_mode=fixed",
            f"style={first_body.get('style')}，seed={first_body.get('seed')}，"
            f"seed_mode={first_body.get('seed_mode')}",
        )

        # 12. 提交后进度条与结果图（mock 轮询，不真实出图）
        try:
            page.wait_for_selector('[role="progressbar"][aria-label="生成进度"]', timeout=15_000)
            progress_visible = True
        except PlaywrightTimeoutError:
            progress_visible = False
        page.wait_for_selector('[data-testid="studio-result-image"]', timeout=20_000)
        result_src = page.locator('[data-testid="studio-result-image"]').get_attribute("src") or ""
        recorder.check(
            group,
            "提交后展示进度条与结果图（mock 轮询）",
            progress_visible and result_src.startswith("/api/media/image"),
            "进度条出现，结果图 src 走 /api/media/image",
            f"进度条={progress_visible}，结果图 src={result_src}",
        )
        session.shoot("G7-studio-result")

        # 12'. 二次元服装槽提交 costume_library=costume-anime
        select_costume_kind("二次元")
        page.locator('[data-testid="studio-generate"]').click()
        page.wait_for_timeout(900)
        second_body = captured_bodies[-1] if captured_bodies else {}
        recorder.check(
            group,
            "二次元服装槽提交 costume_library=costume-anime",
            second_body.get("costume_library") == "costume-anime",
            "costume_library=costume-anime",
            f"costume_library={second_body.get('costume_library')}",
        )

        # 13. extra 越界拒绝（拦截上传返回 uploads 目录外路径）
        page.wait_for_selector('input[type="file"]', state="attached", timeout=10_000)
        page.locator('input[type="file"]').set_input_files(
            {"name": "e2e-not-uploads.png", "mimeType": "image/png", "buffer": TINY_PNG}
        )
        try:
            page.get_by_text(re.compile("第 4 张参考图被拒绝")).first.wait_for(
                state="visible", timeout=10_000
            )
            toast_text = page.get_by_text(re.compile("第 4 张参考图被拒绝")).first.inner_text()
        except PlaywrightTimeoutError:
            toast_text = "未出现拒绝提示"
        recorder.check(
            group,
            "extra 越界拒绝并给中文错误",
            "不在 uploads 上传目录内" in toast_text,
            "提示含「不在 uploads 上传目录内」",
            f"提示={toast_text}",
        )
        session.shoot("G7-extra-rejected")

        # ------------------------------------------------------------------
        # G7 增补（2026-11-05）：批量组合数、上限 100、空槽提交、
        # 非 studio 400、Qwen 系 caps 过滤。全部只用语义选择器与文案。
        # ------------------------------------------------------------------

        captured_bodies.clear()

        # 1) 尺寸多选相乘：切到 PornMaster（caps quality/orientation=true），
        #    在默认 1 档基础上各再选 1 档 → N = 槽位组合 × 2 × 2。
        porn_path = choose_workflow(page, "PornMaster_Flux2Klein9B_三图角色合成")
        porn_has_size = (
            page.locator('[data-testid="studio-quality-field"]').count() > 0
            and page.locator('[data-testid="studio-ratio-field"]').count() > 0
        )
        click_first_unselected_chip(page, "studio-quality-options")
        click_first_unselected_chip(page, "studio-ratio-options")
        selected_quality = page.locator(
            '[data-testid="studio-quality-options"] button[aria-pressed="true"]'
        ).count()
        selected_ratio = page.locator(
            '[data-testid="studio-ratio-options"] button[aria-pressed="true"]'
        ).count()

        counts = read_slot_counts(page)
        combos = slot_product(counts)
        expected_total = combos * selected_quality * selected_ratio
        actual_total, limit_value, total_text = read_batch_total(page)
        recorder.check(
            group,
            "组合数 = 槽位组合 × 画质档数 × 比例数（尺寸多选相乘）",
            bool(porn_path) and porn_has_size
            and selected_quality >= 2
            and selected_ratio >= 2
            and actual_total == expected_total
            and limit_value == 100,
            f"N = {combos} × {selected_quality} × {selected_ratio} = {expected_total}，上限 100",
            f"工作流={porn_path}，槽位={counts}，画质档={selected_quality}，"
            f"比例={selected_ratio}，实测文本={total_text}",
        )

        # 2) 空槽不展开：清空人像 / 服装两槽，只剩姿势 → 空槽按 1 计而非 0。
        page.locator(
            '[data-testid="studio-slot-portrait"] button[aria-label^="清除"]'
        ).click()
        page.locator(
            '[data-testid="studio-slot-costume"] button[aria-label^="清除"]'
        ).click()
        page.wait_for_timeout(400)
        counts_after_clear = read_slot_counts(page)
        combos_after_clear = slot_product(counts_after_clear)
        actual_after_clear, _, text_after_clear = read_batch_total(page)
        expected_after_clear = combos_after_clear * selected_quality * selected_ratio
        recorder.check(
            group,
            "空槽按 1 计、不展开为 0",
            counts_after_clear["pose"] >= 1
            and combos_after_clear == 1
            and actual_after_clear == expected_after_clear
            and actual_after_clear > 0,
            f"清空人像/服装后 N = 1 × {selected_quality} × {selected_ratio} = {expected_after_clear}（>0）",
            f"槽位={counts_after_clear}，实测文本={text_after_clear}",
        )

        # 3) 上限 100：姿势槽加到 3 张 + 全尺寸档（5×9）→ 135 > 100，
        #    提交按钮禁用并给出与常量逐字一致的文案。
        page.locator('[data-testid="studio-slot-pose"]').click()
        page.wait_for_selector('[data-testid="pose-card"]', state="visible", timeout=60_000)
        add_pose = page.get_by_role("button", name="加入配方", exact=True)
        for _ in range(2):
            if add_pose.count() == 0:
                break
            add_pose.first.click()
            page.wait_for_timeout(250)
        page.get_by_role("tab", name="合成台", exact=True).click()
        page.wait_for_selector('[data-testid="reference-studio"]', state="visible", timeout=30_000)
        page.wait_for_timeout(800)

        # 切页签会重置工作流与尺寸选择，回合成台后重新选 PornMaster 并点满档位。
        choose_workflow(page, "PornMaster_Flux2Klein9B_三图角色合成")
        click_chips(page, "studio-quality-options", select=True)
        click_chips(page, "studio-ratio-options", select=True)
        counts_over = read_slot_counts(page)
        combos_over = slot_product(counts_over)
        quality_over = page.locator(
            '[data-testid="studio-quality-options"] button[aria-pressed="true"]'
        ).count()
        ratio_over = page.locator(
            '[data-testid="studio-ratio-options"] button[aria-pressed="true"]'
        ).count()
        total_over, limit_over, text_over = read_batch_total(page)
        expected_over = combos_over * quality_over * ratio_over
        limit_message = f"全组合共 {expected_over} 张，超过上限 100 张；请减少素材或尺寸档位"
        blocked_text = text_of(page, '[data-testid="studio-generate-blocked"]')
        batch_limit_text = text_of(page, '[data-testid="studio-batch-limit"]')
        generate = page.locator('[data-testid="studio-generate"]')
        recorder.check(
            group,
            "超过上限 100 时禁用提交并给出原文案",
            expected_over > 100
            and total_over == expected_over
            and limit_over == 100
            and generate.is_disabled()
            and blocked_text == limit_message
            and batch_limit_text == limit_message,
            f"N={expected_over} > 100，按钮 disabled，文案=「{limit_message}」",
            f"N={total_over}，disabled={generate.is_disabled()}，"
            f"按钮下方文案=「{blocked_text}」，摘要文案=「{batch_limit_text}」",
        )
        session.shoot("G7-batch-limit")

        # 4) 空槽提交：M=1（仅姿势）< N=3。
        #    可裁剪工作流（Qwen21 三图）→ 后端探测可裁 → 直接提交 + 裁剪 toast，不弹确认框；
        #    不可裁剪工作流（PornMaster/Flux）→ 才弹降级确认框，且不给「仍用当前工作流提交」。
        choose_workflow(page, "图库专用_Qwen21+VNCCS")
        page.wait_for_timeout(500)
        counts_before_submit = read_slot_counts(page)
        total_before_submit, _, _ = read_batch_total(page)
        captured_bodies.clear()
        page.locator('[data-testid="studio-generate"]').click()
        page.wait_for_timeout(2500)
        trim_dialog = page.locator('[data-testid="studio-workflow-downgrade"]').count()
        try:
            trim_toast = page.get_by_text(re.compile("自动裁剪空槽后提交")).first.inner_text(
                timeout=10_000
            )
        except PlaywrightTimeoutError:
            trim_toast = "未出现裁剪提示"
        empty_slot_body = captured_bodies[-1] if captured_bodies else {}
        recorder.check(
            group,
            "可裁剪工作流（Qwen21，M=1<N=3）直接提交并 toast 说明，不弹确认框",
            trim_dialog == 0
            and "自动裁剪空槽后提交" in trim_toast
            and bool(captured_bodies),
            "无确认框、出现「已按 1 图自动裁剪空槽后提交」toast、POST 已发出",
            f"确认框={trim_dialog}，toast=「{trim_toast}」，POST={len(captured_bodies)}，"
            f"提交前槽位={counts_before_submit}，N={total_before_submit}",
        )
        recorder.check(
            group,
            "空槽提交只发送已填槽（不含 portrait_id / costume_id）",
            bool(captured_bodies)
            and "pose_id" in empty_slot_body
            and "portrait_id" not in empty_slot_body
            and "costume_id" not in empty_slot_body,
            "提交体含 pose_id，且不含 portrait_id / costume_id",
            f"提交体键={sorted(empty_slot_body.keys())}，"
            f"pose_id={empty_slot_body.get('pose_id')}",
        )
        # 缺服装必须自动按素体展示提交（否则 Qwen 系会出裸体）
        recorder.check(
            group,
            "缺服装时自动按素体展示（body_mode=bare）提交",
            empty_slot_body.get("body_mode") == "bare",
            "提交体 body_mode=bare",
            f"body_mode={empty_slot_body.get('body_mode')!r}",
        )

        # 不可裁剪工作流必须仍能拦住：Flux 系参考图不进文本编码器，裁不掉就是 400。
        choose_workflow(page, "PornMaster_Flux2Klein9B_三图角色合成")
        page.wait_for_timeout(500)
        captured_bodies.clear()
        page.locator('[data-testid="studio-generate"]').click()
        page.wait_for_selector(
            '[data-testid="studio-workflow-downgrade"]', state="visible", timeout=15_000
        )
        downgrade_message = text_of(page, '[data-testid="studio-downgrade-message"]')
        blocked_reason = text_of(page, '[data-testid="studio-downgrade-blocked"]')
        has_force_button = page.locator('[data-testid="studio-downgrade-current"]').count() > 0
        recorder.check(
            group,
            "不可裁剪工作流才弹确认框，且不提供「仍用当前工作流提交」",
            "切换后任务语义可能变为换衣/编辑" in downgrade_message
            and "无法裁剪" in blocked_reason
            and not has_force_button
            and not captured_bodies,
            "文案含语义变化 + 后端确认无法裁剪原因，强制提交按钮不存在，未发出 POST",
            f"文案=「{downgrade_message}」，原因=「{blocked_reason}」，"
            f"强制按钮={has_force_button}，POST={len(captured_bodies)}",
        )
        page.locator('[data-testid="studio-downgrade-cancel"]').click()
        page.wait_for_timeout(500)

        # 5) 非 studio 400 与 M==0 400：直接打后端，避免页面前置校验。
        all_workflows = api_json(base, "/api/workflows?scope=all")
        studio_paths = {
            item.get("path") for item in workflow_catalog.get("workflows", [])
        }
        non_studio_paths = [
            item.get("path")
            for item in all_workflows.get("workflows", [])
            if item.get("path") and item.get("path") not in studio_paths
        ]
        portrait_payload = api_json(
            base, "/api/reference/items?library=portrait&page=1&page_size=1"
        )
        portrait_items = portrait_payload.get("items") or []
        portrait_id = portrait_items[0].get("id") if portrait_items else None

        empty_status, empty_body = post_json_status(
            base,
            "/api/reference/recipes",
            {
                "style": "realistic",
                "prompt_suffix": "",
                "seed": 100000,
                "seed_mode": "fixed",
            },
        )
        recorder.check(
            group,
            "空槽提交（M=0）返回 400 且提示至少选择一张",
            empty_status == 400 and "请至少选择一个参考图" in empty_body,
            "HTTP 400，detail 含「请至少选择一个参考图」",
            f"HTTP {empty_status}，响应={empty_body[:160]}",
        )

        if not non_studio_paths or portrait_id is None:
            recorder.skip(
                group,
                "非 studio 工作流返回 400",
                "HTTP 400，detail 含「不属于合成台可用范围」",
                f"无法构造用例：非 studio 工作流 {len(non_studio_paths)} 个，"
                f"人像条目 {len(portrait_items)} 条",
            )
        else:
            outside_status, outside_body = post_json_status(
                base,
                "/api/reference/recipes",
                {
                    "portrait_id": portrait_id,
                    "workflow": non_studio_paths[0],
                    "style": "realistic",
                    "prompt_suffix": "",
                    "seed": 100000,
                    "seed_mode": "fixed",
                },
            )
            recorder.check(
                group,
                "非 studio 工作流返回 400",
                outside_status == 400 and "不属于合成台可用范围" in outside_body,
                "HTTP 400，detail 含「不属于合成台可用范围」",
                f"HTTP {outside_status}，工作流={non_studio_paths[0]}，"
                f"响应={outside_body[:160]}",
            )

        # 6) Qwen 系 caps 过滤：尺寸档与比例控件隐藏，提交体绝不带
        #    quality / aspect_ratio / orientation 三个字段。
        page.locator('[data-testid="studio-random"]').click()
        page.wait_for_function(
            """() => {
                const node = document.querySelector('[data-testid="studio-recipe-count"]');
                return node && node.textContent.trim() === '3/3';
            }""",
            timeout=60_000,
        )
        qwen_path = choose_workflow(page, "图库专用_Qwen21+VNCCS")
        qwen_hidden = (
            page.locator('[data-testid="studio-quality-field"]').count() == 0
            and page.locator('[data-testid="studio-ratio-field"]').count() == 0
            and page.locator('[data-testid="studio-size-follow-note"]').count() > 0
        )
        captured_bodies.clear()
        page.locator('[data-testid="studio-generate"]').click()
        page.wait_for_timeout(1500)
        qwen_body = captured_bodies[-1] if captured_bodies else {}
        recorder.check(
            group,
            "Qwen 系不发送 quality / aspect_ratio / orientation",
            "Qwen21+VNCCS" in qwen_path
            and qwen_hidden
            and bool(captured_bodies)
            and "quality" not in qwen_body
            and "aspect_ratio" not in qwen_body
            and "orientation" not in qwen_body,
            "尺寸控件隐藏；提交体不含 quality / aspect_ratio / orientation",
            f"工作流={qwen_path}，控件隐藏={qwen_hidden}，"
            f"提交体键={sorted(qwen_body.keys())}",
        )

    except PlaywrightTimeoutError as error:
        recorder.fail(group, "合成台加载/交互", "合成台在 60s 内可用", f"超时：{error}")
    finally:
        session.close()

    # 可选的 1 组真实提交（--live-submit）：验证链路，不批量出图。
    run_live_submit(browser, base, recorder, group)


# ---------------------------------------------------------------------------
# G8 历史与参考板（6 项）
# ---------------------------------------------------------------------------


def run_g8(browser: Browser, base: str, recorder: Recorder) -> None:
    group = "G8"
    if not recorder.enabled(group):
        return

    session = BrowserSession(browser, base, recorder)
    try:
        session.open()
        page = session.page
        ensure_vue_studio(page, base)
        panel = page.locator('[data-testid="reference-history-panel"]')
        panel.wait_for(state="visible", timeout=30_000)
        page.wait_for_timeout(1200)

        panel_text = panel.inner_text()
        recorder.check(
            group,
            "生成历史面板可读且标注「只读」",
            "生成历史" in panel_text and "只读" in panel_text,
            "面板含「生成历史」与「只读」",
            f"面板文本前 80 字={panel_text[:80]}",
        )

        button_texts = panel.get_by_role("button").all_text_contents()
        recorder.check(
            group,
            "历史无删除按钮",
            not any("删除" in text for text in button_texts),
            "面板内无「删除」按钮",
            f"按钮={button_texts}",
        )
        recorder.check(
            group,
            "历史无清空按钮",
            not any("清空" in text for text in button_texts),
            "面板内无「清空」按钮",
            f"按钮={button_texts}",
        )

        history_cards = page.locator('article[data-testid^="reference-history-"]')
        card_count = history_cards.count()
        if card_count == 0:
            recorder.skip(
                group,
                "历史图片地址走后端 view_url",
                "img src 以 /api/ 开头",
                "当前 /api/images 没有历史记录，无法断言图片地址",
            )
        else:
            srcs = page.locator(
                'article[data-testid^="reference-history-"] img'
            ).evaluate_all("(nodes) => nodes.map((node) => node.getAttribute('src') || '')")
            recorder.check(
                group,
                "历史图片地址走后端 view_url",
                bool(srcs) and all(src.startswith("/api/") for src in srcs),
                "历史图片 src 全部以 /api/ 开头",
                f"图片 {len(srcs)} 张，非 /api/ 开头 "
                f"{sum(1 for src in srcs if not src.startswith('/api/'))} 张",
            )

        session.shoot("G8-history-panel")
    except PlaywrightTimeoutError as error:
        recorder.fail(group, "历史面板加载", "历史面板在 30s 内渲染", f"超时：{error}")
    finally:
        session.close()

    # 空图占位：拦截 /api/images 注入一条 view_url 为空的历史记录
    def empty_images_route(route: Route) -> None:
        payload = {
            "items": [
                {
                    "id": 1,
                    "job_id": 0,
                    "prompt_id": 0,
                    "comfyui_prompt_id": "",
                    "filename": "e2e-empty.png",
                    "subfolder": "",
                    "img_type": "output",
                    "view_url": "",
                    "is_favorite": False,
                    "missing": True,
                    "width": 0,
                    "height": 0,
                    "file_size": 0,
                    "created_at": "2026-11-05 00:00:00",
                    "captured_at": "2026-11-05 00:00:00",
                    "source": "e2e",
                    "prompt_name": "E2E 空图",
                    "prompt_params": {},
                }
            ],
            "total": 1,
        }
        route.fulfill(
            status=200,
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload, ensure_ascii=False),
        )

    session = BrowserSession(browser, base, recorder)
    try:
        session.open(routes=[("**/api/images**", empty_images_route)])
        page = session.page
        ensure_vue_studio(page, base)
        page.wait_for_selector('[data-testid="reference-history-panel"]', state="visible", timeout=30_000)
        page.get_by_text("图片不可用").first.wait_for(state="visible", timeout=15_000)
        disabled_download = page.locator(
            '[data-testid="reference-history-panel"] [aria-disabled="true"]'
        ).count()
        recorder.check(
            group,
            "空图渲染「图片不可用」并禁用下载",
            disabled_download > 0,
            "存在「图片不可用」占位且下载 aria-disabled=true",
            f"禁用下载元素 {disabled_download} 个",
        )
        session.shoot("G8-empty-image")
    except PlaywrightTimeoutError as error:
        recorder.fail(group, "空图占位", "空图占位在 15s 内出现", f"超时：{error}")
    finally:
        session.close()

    # §7 冻结：参考板 ReferenceSheetButton 与 labels 开关均不迁移
    recorder.skip(
        group,
        "参考板 1800×1200 与 labels 开关",
        "参考板导出与标签开关可用",
        "§7 已冻结「参考板 ReferenceSheetButton 不迁移」；Vue 参考图库无该入口，"
        "属功能不存在而非未实现",
    )


# ---------------------------------------------------------------------------
# G9 深链与多入口（§6 全表 + 边界，阶段 4.3/4.4 起转正）
# ---------------------------------------------------------------------------


def run_g9(browser: Browser, base: str, recorder: Recorder) -> None:
    group = "G9"
    if not recorder.enabled(group):
        return

    # 1-7. §6 映射表：直接请求后端、不跟随重定向，断言状态码与 Location。
    redirect_cases = [
        ("/ref-web", 301, "/reference"),
        ("/ref-web/", 301, "/reference"),
        ("/ref-web/poses", 301, "/reference?tab=pose"),
        ("/ref-web/costumes", 301, "/reference?tab=costume"),
        ("/ref-web/portraits", 301, "/reference?tab=portrait"),
        ("/ref-web/studio", 301, "/reference?tab=studio"),
        ("/ref-web/settings", 301, "/reference?tab=settings"),
    ]
    for path, expected_code, expected_location in redirect_cases:
        code, location = probe_redirect(base, path)
        recorder.check(
            group,
            f"深链映射 {path}",
            code == expected_code and location == expected_location,
            f"{expected_code} → {expected_location}",
            f"{code} → {location}",
        )

    # 8. 未知段兜底：302 到 /reference，不 404。
    code, location = probe_redirect(base, "/ref-web/__unknown_page__")
    recorder.check(
        group,
        "深链映射 /ref-web/<其它>",
        code == 302 and location == "/reference",
        "302 → /reference（不 404）",
        f"{code} → {location}",
    )

    # 9. query 传递：/ref-web/poses?x=1 → /reference?tab=pose&x=1。
    code, location = probe_redirect(base, "/ref-web/poses?x=1")
    recorder.check(
        group,
        "深链保留原 query（/ref-web/poses?x=1）",
        code == 301 and location == "/reference?tab=pose&x=1",
        "301 → /reference?tab=pose&x=1",
        f"{code} → {location}",
    )

    # 10. 前缀边界：/ref-webevil 不能被当成 /ref-web。
    code, location = probe_redirect(base, "/ref-webevil")
    recorder.check(
        group,
        "前缀边界 /ref-webevil 不误匹配",
        code not in (301, 302) and location != "/reference",
        "不是 301/302 到 /reference（由 SPA 兜底）",
        f"{code} → {location or '（无重定向）'}",
    )

    # 11. 路径穿越：不泄漏文件、不 404（由重定向或 SPA 兜底接住）。
    code, location = probe_redirect(base, "/ref-web/../../etc/passwd")
    safe = (code in (301, 302) and location == "/reference") or code == 200
    recorder.check(
        group,
        "路径穿越 /ref-web/../../etc/passwd 不泄漏",
        safe,
        "302 → /reference 或 200（SPA 兜底），不返回系统文件",
        f"{code} → {location or '（无重定向）'}",
    )

    # 12. ?path= 翻译：后端 301 到对应页签。
    code, location = probe_redirect(base, "/reference?path=/ref-web/studio")
    recorder.check(
        group,
        "?path=/ref-web/studio 翻译为 ?tab=studio",
        code == 301 and location == "/reference?tab=studio",
        "301 → /reference?tab=studio",
        f"{code} → {location}",
    )

    # 13. ?path= 非法值：回落默认页（去掉 path），不白屏。
    code, location = probe_redirect(base, "/reference?path=/ref-web/../../etc/passwd")
    recorder.check(
        group,
        "非法 ?path= 回落 /reference",
        code == 301 and location == "/reference",
        "301 → /reference（默认图库总览）",
        f"{code} → {location}",
    )

    # 14-15. 浏览器落地：跟随重定向后仍渲染正确的 Vue 页签。
    session = BrowserSession(browser, base, recorder)
    try:
        session.open()
        session.goto("/ref-web/poses", wait_selector="h1")
        deep_heading = text_of(session.page, "h1")
        deep_url = session.page.url
        recorder.check(
            group,
            "浏览器落地 /ref-web/poses → 姿势库",
            deep_heading == "姿势库" and "tab=pose" in deep_url,
            "h1 = 姿势库 且 URL 含 tab=pose",
            f"h1 = {deep_heading}，URL = {deep_url}",
        )
        session.shoot("G9-deeplink-poses")

        session.goto("/reference?path=/ref-web/portraits", wait_selector="h1")
        path_heading = text_of(session.page, "h1")
        path_url = session.page.url
        recorder.check(
            group,
            "浏览器落地 ?path=/ref-web/portraits → 人像库",
            path_heading == "人像库" and "tab=portrait" in path_url and "path=" not in path_url,
            "h1 = 人像库、URL 含 tab=portrait 且不含 path",
            f"h1 = {path_heading}，URL = {path_url}",
        )
    finally:
        session.close()


# ---------------------------------------------------------------------------
# G10 响应式与健康（6 项）
# ---------------------------------------------------------------------------


def run_g10(browser: Browser, base: str, recorder: Recorder) -> None:
    group = "G10"
    if not recorder.enabled(group):
        return

    session = BrowserSession(browser, base, recorder)
    try:
        session.open(viewport={"width": 390, "height": 844})
        page = session.page
        console_errors: list[str] = []
        http_errors: list[str] = []

        def on_console(message) -> None:
            if message.type == "error":
                console_errors.append(message.text)

        def on_response(response) -> None:
            if response.status >= 400:
                http_errors.append(f"{response.status} {response.url}")

        page.on("console", on_console)
        page.on("response", on_response)

        session.goto("/reference?shell=vue&tab=home", wait_selector='[data-testid="reference-home-title"]')
        page.wait_for_timeout(2500)

        # 1. 390px 无横向溢出
        overflow = page.evaluate(
            """() => ({
                docScroll: document.documentElement.scrollWidth,
                docClient: document.documentElement.clientWidth,
                bodyScroll: document.body.scrollWidth,
                bodyClient: document.body.clientWidth,
            })"""
        )
        recorder.check(
            group,
            "390px 无横向溢出",
            overflow["docScroll"] <= overflow["docClient"] + 1
            and overflow["bodyScroll"] <= overflow["bodyClient"] + 1,
            "document/body 的 scrollWidth ≤ clientWidth + 1",
            f"{overflow}",
        )

        # 2. 页签条可横滚
        nav_scroll = page.evaluate(
            """() => {
                const nav = document.querySelector('nav[aria-label="参考图库页签"]');
                if (!nav) return null;
                const style = window.getComputedStyle(nav);
                return {
                    scrollWidth: nav.scrollWidth,
                    clientWidth: nav.clientWidth,
                    overflowX: style.overflowX,
                };
            }"""
        )
        recorder.check(
            group,
            "390px 页签条可横向滚动",
            bool(nav_scroll)
            and (
                nav_scroll["scrollWidth"] > nav_scroll["clientWidth"]
                or nav_scroll["overflowX"] in ("auto", "scroll")
            ),
            "页签条 scrollWidth > clientWidth 或 overflow-x 为 auto/scroll",
            f"{nav_scroll}",
        )
        session.shoot("G10-390px-home")

        # 3. console error 0
        recorder.check(
            group,
            "console error 为 0",
            not console_errors,
            "console error 0 条",
            f"{len(console_errors)} 条：{console_errors[:3]}",
        )

        # 4. 无 404 资源
        recorder.check(
            group,
            "无 404/4xx/5xx 资源",
            not http_errors,
            "无 HTTP ≥400 响应",
            f"{len(http_errors)} 条：{http_errors[:3]}",
        )

        # 5. 纯 Vue：无 React #root 根节点
        roots = page.evaluate(
            """() => ({
                root: document.querySelectorAll('#root').length,
                app: document.querySelectorAll('#app').length,
            })"""
        )
        recorder.check(
            group,
            "页面无 React #root 根节点（纯 Vue）",
            roots["root"] == 0 and roots["app"] == 1,
            "#root=0 且 #app=1",
            f"{roots}",
        )
    except PlaywrightTimeoutError as error:
        recorder.fail(group, "390px 页面加载", "首页在 60s 内渲染", f"超时：{error}")
    finally:
        session.close()

    # 6. 构建产物不含 ref-web（阶段 4.3 已删除 React 与 iframe 分支，必须 PASS）
    index_html = PROJECT_ROOT / "脚本" / "atelier" / "web" / "index.html"
    if not index_html.exists():
        recorder.fail(
            group,
            "构建产物不含 ref-web",
            "web/index.html 引用的 JS 中 ref-web 出现 0 次",
            "未找到 脚本/atelier/web/index.html，无法检查构建产物（先 pnpm run build）",
        )
    else:
        html = index_html.read_text(encoding="utf-8", errors="replace")
        asset_paths = re.findall(r'src="(/assets/[^"]+\.js)"', html)
        hits: list[str] = []
        for asset in asset_paths:
            asset_file = PROJECT_ROOT / "脚本" / "atelier" / "web" / asset.lstrip("/")
            if not asset_file.exists():
                continue
            content = asset_file.read_text(encoding="utf-8", errors="replace")
            count = content.count("ref-web")
            if count:
                hits.append(f"{asset}: {count}")
        if not asset_paths:
            recorder.fail(
                group,
                "构建产物不含 ref-web",
                "web/index.html 引用的 JS 中 ref-web 出现 0 次",
                "web/index.html 未引用任何本地 JS，无法检查（构建产物异常）",
            )
        elif hits:
            recorder.fail(
                group,
                "构建产物不含 ref-web",
                "web/index.html 引用的 JS 中 ref-web 出现 0 次",
                f"产物仍含 ref-web（{hits}）—— iframe 分支或旧注释未清理干净",
            )
        else:
            recorder.check(
                group,
                "构建产物不含 ref-web",
                True,
                "web/index.html 引用的 JS 中 ref-web 出现 0 次",
                "0 次",
            )


# ---------------------------------------------------------------------------
# G11 合成台交互（2026-11-05，8 项）
# ---------------------------------------------------------------------------


def run_g11(browser: Browser, base: str, recorder: Recorder) -> None:
    group = "G11"
    if not recorder.enabled(group):
        return

    captured: list[dict] = []

    def recipes_route(route: Route) -> None:
        captured.append(read_json_body(route))
        route.fulfill(
            status=200,
            headers={"Content-Type": "application/json"},
            body=json.dumps({"success": True, "job_id": 999011, "errors": []}),
        )

    session = BrowserSession(browser, base, recorder)
    try:
        session.open(routes=[("**/api/reference/recipes**", recipes_route)])
        page = session.page
        ensure_vue_studio(page, base)
        page.wait_for_function(
            """() => {
                const node = document.querySelector('[data-testid="studio-workflow-trigger"]');
                return node && (node.getAttribute('title') || '') !== '选择工作流';
            }""",
            timeout=30_000,
        )

        # 初始空态：常驻「当前 0 / 上限 100」。
        initial_total, initial_limit, initial_text = read_batch_total(page)

        # 1. 基础种子输入存在且 hint 说明第 i 组 = base_seed + i
        seed_input = page.locator('[data-testid="studio-base-seed"]')
        seed_hint = text_of(page, '[data-testid="studio-seed-hint"]')
        seed_value = seed_input.input_value() if seed_input.count() else ""
        recorder.check(
            group,
            "基础种子输入存在且说明 base_seed + i 派生",
            seed_input.count() == 1
            and seed_value.isdigit()
            and "基础种子" in seed_hint
            and "+i" in seed_hint,
            "存在数字输入框，说明含「基础种子」与「+i」",
            f"输入值={seed_value or '缺失'}，说明=「{seed_hint}」",
        )

        # 2. 随机捏人填三槽后，到姿势库再选 3 张（共 4 张）
        page.locator('[data-testid="studio-random"]').click()
        page.wait_for_function(
            """() => {
                const node = document.querySelector('[data-testid="studio-recipe-count"]');
                return node && node.textContent.trim() === '3/3';
            }""",
            timeout=60_000,
        )
        page.locator('[data-testid="studio-slot-pose"]').click()
        page.wait_for_selector('[data-testid="pose-card"]', state="visible", timeout=60_000)
        add_buttons = page.get_by_role("button", name="加入配方", exact=True)
        added = 0
        for _ in range(3):
            if add_buttons.count() == 0:
                break
            add_buttons.first.click()
            added += 1
            page.wait_for_timeout(250)
        page.get_by_role("tab", name="合成台", exact=True).click()
        page.wait_for_selector('[data-testid="reference-studio"]', state="visible", timeout=30_000)
        page.wait_for_timeout(800)

        # 3. 三槽卡片显示已选数量与前 3 张缩略图（第 4 张用 +N 表达）
        counts = read_slot_counts(page)
        pose_thumbs = page.locator('[data-testid="studio-slot-pose"] img').count()
        pose_text = page.locator('[data-testid="studio-slot-pose"]').inner_text()
        other_thumbs = {
            key: page.locator(f'[data-testid="studio-slot-{key}"] img').count()
            for key in ("portrait", "costume")
        }
        recorder.check(
            group,
            "三槽卡片显示已选数量与前 3 张缩略图（溢出 +N）",
            added == 3
            and counts["pose"] == 4
            and pose_thumbs == 3
            and "+1" in pose_text
            and other_thumbs["portrait"] == 1
            and other_thumbs["costume"] == 1,
            "姿势槽计数 4、缩略图 3 张、文本含「+1」；人像/服装各 1 张",
            f"新增 {added} 张，槽位计数={counts}，姿势缩略图={pose_thumbs}，"
            f"文本=「{pose_text}」，其它槽缩略图={other_thumbs}",
        )
        session.shoot("G11-slot-thumbs")

        # 4. 切回合成台后默认工作流是 Qwen21：尺寸档与比例控件隐藏
        qwen_hidden = (
            page.locator('[data-testid="studio-quality-field"]').count() == 0
            and page.locator('[data-testid="studio-ratio-field"]').count() == 0
            and page.locator('[data-testid="studio-size-follow-note"]').count() > 0
        )
        qwen_title = (
            page.locator('[data-testid="studio-workflow-trigger"]').get_attribute("title") or ""
        )
        after_material, after_limit, after_text = read_batch_total(page)
        recorder.check(
            group,
            "Qwen21 工作流隐藏尺寸档与比例控件",
            "Qwen21+VNCCS" in qwen_title and qwen_hidden and after_limit == 100,
            "画质档/比例字段 0 个，出现「输出尺寸跟随参考图」说明",
            f"工作流={qwen_title}，隐藏={qwen_hidden}，N 文本=「{after_text}」",
        )

        # 5. 页面常驻「N / 上限 100」且随素材变化实时更新
        recorder.check(
            group,
            "页面常驻「当前 N / 上限 100」并随素材实时更新",
            initial_total == 0
            and initial_limit == 100
            and after_material == 4
            and after_limit == 100,
            "初始「当前 0 / 上限 100」；姿势 4 张后「当前 4 / 上限 100」",
            f"初始「{initial_text}」，当前「{after_text}」",
        )

        # 6. 切到 PornMaster（caps 支持尺寸）→ 尺寸档与比例控件出现
        porn_title = choose_workflow(page, "PornMaster_Flux2Klein9B_三图角色合成")
        porn_visible = (
            page.locator('[data-testid="studio-quality-field"]').count() > 0
            and page.locator('[data-testid="studio-ratio-field"]').count() > 0
        )
        recorder.check(
            group,
            "PornMaster 工作流出现尺寸档与比例控件",
            "PornMaster_Flux2Klein9B_三图角色合成" in porn_title and porn_visible,
            "画质档与比例字段各 1 个",
            f"工作流={porn_title}，控件出现={porn_visible}",
        )

        # 7. 超限：点满 5 画质 + 9 比例 → N = 4 × 5 × 9 = 180 > 100
        click_chips(page, "studio-quality-options", select=True)
        click_chips(page, "studio-ratio-options", select=True)
        quality_count = page.locator(
            '[data-testid="studio-quality-options"] button[aria-pressed="true"]'
        ).count()
        ratio_count = page.locator(
            '[data-testid="studio-ratio-options"] button[aria-pressed="true"]'
        ).count()
        total_over, limit_over, text_over = read_batch_total(page)
        expected_over = slot_product(read_slot_counts(page)) * quality_count * ratio_count
        limit_message = f"全组合共 {expected_over} 张，超过上限 100 张；请减少素材或尺寸档位"
        generate = page.locator('[data-testid="studio-generate"]')
        blocked_text = text_of(page, '[data-testid="studio-generate-blocked"]')
        recorder.check(
            group,
            "超限时提交按钮禁用且展示原文案",
            expected_over > 100
            and total_over == expected_over
            and limit_over == 100
            and generate.is_disabled()
            and blocked_text == limit_message,
            f"N={expected_over} > 100，按钮 disabled，文案=「{limit_message}」",
            f"N 文本=「{text_over}」，disabled={generate.is_disabled()}，"
            f"文案=「{blocked_text}」",
        )
        session.shoot("G11-batch-limit")

        # 8. 降级确认框：切 Qwen 再切回 PornMaster（尺寸选择回落 1 档）→ N=4；
        #    清空人像/服装，只剩姿势 4 张 → M=1 < input_count=3，点提交先弹框。
        choose_workflow(page, "图库专用_Qwen21+VNCCS")
        choose_workflow(page, "PornMaster_Flux2Klein9B_三图角色合成")
        page.locator('[data-testid="studio-slot-portrait"] button[aria-label^="清除"]').click()
        page.locator('[data-testid="studio-slot-costume"] button[aria-label^="清除"]').click()
        page.wait_for_timeout(500)
        _, _, text_before = read_batch_total(page)
        captured.clear()
        page.locator('[data-testid="studio-generate"]').click()
        page.wait_for_selector(
            '[data-testid="studio-workflow-downgrade"]', state="visible", timeout=15_000
        )
        downgrade_message = text_of(page, '[data-testid="studio-downgrade-message"]')
        blocked_reason = text_of(page, '[data-testid="studio-downgrade-blocked"]')
        has_force_button = page.locator('[data-testid="studio-downgrade-current"]').count() > 0
        recorder.check(
            group,
            "不可裁剪工作流弹出降级确认框并说明语义变化与无法裁剪原因",
            "切换后任务语义可能变为换衣/编辑" in downgrade_message
            and "无法裁剪" in blocked_reason
            and not has_force_button,
            "确认框文案含「切换后任务语义可能变为换衣/编辑」与后端原因，且无强制提交按钮",
            f"文案=「{downgrade_message}」，原因=「{blocked_reason}」，"
            f"强制按钮={has_force_button}，提交前 N 文本=「{text_before}」",
        )
        session.shoot("G11-downgrade")

        # 9. 取消确认框：不提交（POST 计数为 0）
        page.locator('[data-testid="studio-downgrade-cancel"]').click()
        page.wait_for_timeout(800)
        dialog_gone = page.locator('[data-testid="studio-workflow-downgrade"]').count() == 0
        recorder.check(
            group,
            "取消降级确认框后不发生提交",
            dialog_gone and not captured,
            "确认框消失且 POST /api/reference/recipes 调用 0 次",
            f"确认框消失={dialog_gone}，POST 次数={len(captured)}",
        )
    except PlaywrightTimeoutError as error:
        recorder.fail(group, "合成台交互", "G11 交互在 60s 内完成", f"超时：{error}")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 真实提交（--live-submit，仅 1 组 / 1 张图）
# ---------------------------------------------------------------------------


def run_live_submit(browser: Browser, base: str, recorder: Recorder, group: str = "G7") -> None:
    """真实提交 1 组，验证「前端 → 后端 → 轮询 → 结果图」链路。

    仅在 `--live-submit` 且对应分组启用时执行；不挂任何路由 mock。
    全量验收最多产生 1 张图，避免 27 张批量出图。
    """
    if not recorder.live_submit or not recorder.enabled(group):
        return

    responses: list[dict] = []
    session = BrowserSession(browser, base, recorder)
    try:
        page = session.open()

        def on_response(response) -> None:  # noqa: ANN001
            if "/api/reference/recipes" not in response.url:
                return
            if response.request.method != "POST":
                return
            try:
                responses.append(response.json())
            except Exception:
                responses.append({})

        page.on("response", on_response)
        ensure_vue_studio(page, base)
        page.wait_for_function(
            """() => {
                const node = document.querySelector('[data-testid="studio-workflow-trigger"]');
                return node && (node.getAttribute('title') || '') !== '选择工作流';
            }""",
            timeout=30_000,
        )
        workflow_title = (
            page.locator('[data-testid="studio-workflow-trigger"]').get_attribute("title") or ""
        )

        # 随机捏人 → 三槽各 1 张；Qwen21 无尺寸维度，全组合恰好 1 组。
        page.locator('[data-testid="studio-random"]').click()
        page.wait_for_function(
            """() => {
                const node = document.querySelector('[data-testid="studio-recipe-count"]');
                return node && node.textContent.trim() === '3/3';
            }""",
            timeout=60_000,
        )
        total, limit, total_text = read_batch_total(page)
        recorder.check(
            group,
            "真实提交前组合数 = 1 组（只出 1 张）",
            total == 1 and limit == 100,
            "三槽各 1 张、Qwen21 无尺寸维度 → 当前 1 / 上限 100",
            f"工作流={workflow_title}，实测「{total_text}」",
        )

        started = time.time()
        page.locator('[data-testid="studio-generate"]').click()
        page.wait_for_selector('[data-testid="studio-result-image"]', timeout=300_000)
        elapsed = time.time() - started
        result_src = (
            page.locator('[data-testid="studio-result-image"]').get_attribute("src") or ""
        )

        job_id = None
        for payload in responses:
            if isinstance(payload, dict) and payload.get("job_id"):
                job_id = payload.get("job_id")
                break
        result_files: list[str] = []
        if job_id:
            snapshot = api_json(base, f"/api/jobs/{job_id}", timeout=30)
            for item in snapshot.get("items") or []:
                for image in item.get("images") or []:
                    name = image.get("filename")
                    if name:
                        result_files.append(name)

        media_status = 0
        if result_src.startswith("/api/"):
            try:
                with urllib.request.urlopen(f"{base}{result_src}", timeout=30) as response:  # noqa: S310
                    media_status = response.status
            except urllib.error.HTTPError as error:
                media_status = error.code
        recorder.check(
            group,
            "真实提交 1 组打通提交链路并产出 1 张结果图",
            bool(job_id)
            and bool(result_files)
            and result_src.startswith("/api/media/image")
            and media_status == 200,
            "POST 返回 job_id，任务完成后结果图走 /api/media/image 且可访问（HTTP 200）",
            f"job_id={job_id}，耗时 {elapsed:.1f}s，结果图={result_src}，"
            f"media HTTP={media_status}，产物={result_files}",
        )
        print(
            f"[LIVE] job_id={job_id} | 耗时={elapsed:.1f}s | "
            f"结果图={result_src} | 产物={result_files}"
        )
        session.shoot("G7-live-submit")
    except PlaywrightTimeoutError as error:
        recorder.fail(group, "真实提交 1 组", "300s 内返回结果图", f"超时：{error}")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


GROUPS: dict[str, Callable[[Browser, str, Recorder], None]] = {
    "G1": run_g1,
    "G2": run_g2,
    "G3": run_g3,
    "G4": run_g4,
    "G5": run_g5,
    "G6": run_g6,
    "G7": run_g7,
    "G8": run_g8,
    "G9": run_g9,
    "G10": run_g10,
    "G11": run_g11,
}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="参考图库 Vue 版关键路径 E2E 验收（阶段 4.2）",
    )
    parser.add_argument(
        "--base",
        default=DEFAULT_BASE,
        help=f"被测站点基址（默认 {DEFAULT_BASE}）",
    )
    parser.add_argument(
        "--only",
        default="",
        help="只跑指定分组，逗号分隔，例如 G1,G2；缺省跑全部",
    )
    parser.add_argument(
        "--live-submit",
        action="store_true",
        help="G7 额外真实提交 1 组（1 张图）验证提交链路；默认关闭，避免批量出图",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    base = args.base.rstrip("/")

    only: set[str] | None = None
    if args.only.strip():
        only = {item.strip().upper() for item in args.only.split(",") if item.strip()}
        unknown = sorted(only - set(GROUPS))
        if unknown:
            print(
                f"参数错误。原因：--only 含未知分组 {unknown}。"
                f"下一步：改用以下之一 {sorted(GROUPS)} 后重试。"
            )
            return 2

    print(f"参考图库 Vue E2E 验收开始：base={base}")
    print(f"截图目录：{SCREENSHOT_DIR}")
    print(f"分组过滤：{'全部' if only is None else ','.join(sorted(only))}")
    print(f"真实提交：{'开启（最多 1 组 / 1 张图）' if args.live_submit else '关闭'}")
    print("-" * 78)

    recorder = Recorder(only=only, live_submit=args.live_submit)
    started = time.time()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for key in sorted(GROUPS, key=lambda value: int(value[1:])):
                if only is not None and key not in only:
                    continue
                print(f"\n### 执行 {key}")
                try:
                    GROUPS[key](browser, base, recorder)
                except Exception as error:  # 单组异常不应中断其余分组
                    traceback.print_exc()
                    recorder.fail(key, "分组执行异常", "分组正常执行", f"{type(error).__name__}: {error}")
        finally:
            browser.close()

    _, failed, _ = recorder.summary()
    print(f"耗时 {time.time() - started:.1f}s")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())