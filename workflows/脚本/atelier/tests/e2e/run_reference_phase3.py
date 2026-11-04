"""gallery-web 阶段三 / 阶段一（T3）独立验收脚本。

覆盖内容（对应计划 T3 的 acceptance_and_local_checks）：

1. 静态检查：gallery-web `tsc -b --noEmit` / `oxlint src`、Vue `pnpm run typecheck`、
   后端 `python -c "import app.main"`。
2. 构建产物：`dist/index.html` 只引用 `/ref-web/assets/`、dist mtime 晚于源码、
   dist 中旧模板字面量扫描（`qwen2509_2img`、`charadb-2fi.pages.dev` 为硬失败；
   `/data/*.json` 在阶段一仍被旧数据层使用，作为“如实记录”的观察项输出）。
3. 临时实例（8766）+ Playwright 全新 context：
   a. 六个 `/ref-web/**` 路由 200，console error / pageerror 为 0；
   b. 三个返回画廊入口都是原生 `a[href="/gallery"]`，无 `/ref-web/gallery` 拼接；
   c. 18+ 首次确认弹窗只弹一次（记忆键 `pose_atlas_nsfw_confirmed_v1`）；
   d. 合成台工作流下拉选中后端 `GET /api/workflows?scope=studio` 的 `default`，
      而不是列表第一项；
   e. 四库页正常网络裂图 0；屏蔽外部域名（保留 127.0.0.1）后重载四页裂图仍为 0；
   f. 设置页导出旧 IDB 记录：无数据禁用；注入 1 条后导出得到 JSON 1 + PNG 1，
      JSON 字段齐全，导出后 IDB key 仍在；单张图片坏掉时记录 failure 并继续；
      清空后按钮恢复禁用；
   g. 生成记录区数据来自 `GET /api/images`（total 与卡片数比对）、无裂图；
      用 route mock 返回空列表时整区不渲染；合成台不再写 `pose_atlas_history_v3`。

阶段二（T7）追加检查（`C-REMOTE-CACHE@1` / `C-REF-ITEM-DTO@2` / `C-REF-RECIPES@2`）：

   1. `costume-anime` DTO：`thumb_url`/`image_url` 为后端端点、`remote=true`、
      `depth_url=null`、含 `number`/`search_text`/`source_url`；`page_size` 上限 200。
   2. 图片端点：已缓存条目 thumb/image 双次请求均 200 + `image/*`，缓存文件数与
      mtime 不变；未缓存条目首次下载 200 且落盘，第二次不再变化；外链库 depth 404；
      本地库图片端点不回归。
   3. 断网等价（自起实例时）：用不可达代理让服务端外链下载失败，未缓存条目 502、
      已缓存条目仍 200、本地库仍 200，且不留下 `.tmp`/半成品。
   4. recipes：已缓存 anime 服装 + `costume_library=costume-anime` + `dry_run=true`
      返回节点 1/2/3 与三图工作流；未知 `costume_library` 400；缺省仍走本地 `costume`；
      第 4 张仍固定节点 78。
   5. 页面回归：新 context 下四页 200、裂图 0、console 0、返回入口 3 个、
      18+ 首次确认、studio 下拉选中后端 default。
   6. 缓存目录位于 `.cache/reference-remote`、不在 `data/`/`dist/`/`reference_root`，
      且被根 `.gitignore` 忽略（`git check-ignore` / `git status --ignored`）。

跑法（二选一，脚本会自动判断是否需要自起实例）：

    ATELIER_PORT=8766 ATELIER_REFERENCE_ALLOW_NSFW=1 python main.py   # 手动先起
    python tests/e2e/run_reference_phase3.py

脚本自起实例时固定使用 8766，退出时只停止自己启动的进程；
**永不触碰** 运行中的 8656（只做 GET 探活）。

退出码：0 = 全部硬检查通过；1 = 存在硬检查失败或异常。
截图与结果 JSON 写到系统临时目录（不污染仓库），路径会在结尾打印。
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

# ---------------------------------------------------------------------------
# 路径与常量
# ---------------------------------------------------------------------------
V4 = Path(__file__).resolve().parents[2]          # workflows/脚本/atelier
GALLERY = V4 / "gallery-web"
FRONTEND = V4 / "frontend"
DIST = GALLERY / "dist"

PORT = int(os.environ.get("T3_E2E_PORT", "8766"))
BASE = f"http://127.0.0.1:{PORT}"
LIVE_PORT = 8656                                   # 运行中实例：只读探活
NSFW_CONFIRMED_KEY = "pose_atlas_nsfw_confirmed_v1"
LEGACY_HISTORY_KEY = "pose_atlas_history_v3"
IDB_NAME = "pose_atlas_studio_db"                  # 与 src/lib/idbStorage.ts 一致
IDB_STORE = "kv_store"
#: 阶段二：外链图片本机私有缓存（CharaDB 素材仅本机参考、禁止再分发）
CACHE_ROOT = V4 / ".cache" / "reference-remote"
REPO_ROOT = V4.parents[2]                          # 仓库根
#: 服务端“断网等价”探针：不可达代理 + 短超时 + 不重试
OFFLINE_ENV = {
    "HTTPS_PROXY": "http://127.0.0.1:9",
    "HTTP_PROXY": "http://127.0.0.1:9",
    "NO_PROXY": "",
    "ATELIER_REFERENCE_REMOTE_TIMEOUT_SEC": "3",
    "ATELIER_REFERENCE_REMOTE_RETRY": "0",
}

# 1x1 透明 PNG data URL：用于注入旧历史记录。
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
TINY_PNG_DATA_URL = f"data:image/png;base64,{TINY_PNG_B64}"

ROUTES = ["/ref-web/", "/ref-web/poses", "/ref-web/costumes",
          "/ref-web/portraits", "/ref-web/studio", "/ref-web/settings"]
LIBRARY_ROUTES = ["/ref-web/", "/ref-web/poses", "/ref-web/costumes", "/ref-web/portraits"]

# 硬失败字面量（计划 C-BUILD-ARTIFACT@1 明确要求不存在）
FORBIDDEN_LITERALS = ["qwen2509_2img", "charadb-2fi.pages.dev"]
# 阶段一仍会出现在产物里的旧数据路径：如实记录，不作为阶段一失败。
LEGACY_DATA_LITERALS = [
    "/data/pose-zh.json",
    "/data/costume-zh.json",
    "/data/portrait-zh.json",
    "/data/costume-anime-zh.json",
]

_results: list[tuple[bool, str, str]] = []
_observations: list[tuple[str, str]] = []


# ---------------------------------------------------------------------------
# 结果记录
# ---------------------------------------------------------------------------
def check(ok: bool, name: str, detail: str = "") -> bool:
    _results.append((bool(ok), name, detail))
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""))
    return bool(ok)


def observe(name: str, detail: str = "") -> None:
    _observations.append((name, detail))
    print(f"  [观察] {name}" + (f" | {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n=== {title} ===")


# ---------------------------------------------------------------------------
# HTTP / 进程
# ---------------------------------------------------------------------------
def http_get_status(url: str, timeout: float = 5.0) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return None


def api_json(path: str):
    with urllib.request.urlopen(BASE + path, timeout=30) as resp:
        return json.loads(resp.read())


def api_request(path: str, payload: dict | None = None, timeout: float = 60.0):
    """返回 `(status, content_type, body_text)`；4xx/5xx 不抛异常。"""
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers,
                                 method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return (resp.status, resp.headers.get("Content-Type", ""),
                    resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        return (exc.code, exc.headers.get("Content-Type", "") if exc.headers else "",
                exc.read().decode("utf-8", errors="replace"))


def cache_snapshot() -> dict[str, tuple[int, int]]:
    """缓存文件 → (mtime_ns, size)；用于判断请求是否新增/改写了文件。"""
    snap: dict[str, tuple[int, int]] = {}
    if CACHE_ROOT.is_dir():
        for path in CACHE_ROOT.rglob("*"):
            if path.is_file():
                st = path.stat()
                snap[path.relative_to(CACHE_ROOT).as_posix()] = (st.st_mtime_ns, st.st_size)
    return snap


def _cached_item_ids() -> set[str]:
    root = CACHE_ROOT / "costume-anime"
    if not root.is_dir():
        return set()
    return {p.name for p in root.iterdir() if p.is_dir() and any(p.iterdir())}


def port_serving(port: int) -> bool:
    return http_get_status(f"http://127.0.0.1:{port}/ref-web/", timeout=3.0) == 200


def start_instance_if_needed(
    env_extra: dict[str, str] | None = None,
    log_name: str = "t3_phase1_server.log",
) -> subprocess.Popen | None:
    """8766 未被占用时自起临时实例；被占用则复用（不抢、不杀）。

    `env_extra` 用于阶段二的“断网等价”探针（不可达代理）；只影响脚本自己拉起的进程。
    """
    if port_serving(PORT):
        print(f"复用已运行的临时实例 {BASE}（脚本不会停止它）")
        return None

    log_path = Path(tempfile.gettempdir()) / log_name
    env = dict(os.environ)
    env.update({
        "ATELIER_PORT": str(PORT),
        "ATELIER_REFERENCE_ALLOW_NSFW": "1",
        "ATELIER_NO_BROWSER": "1",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    })
    if env_extra:
        env.update(env_extra)
    print(f"自起临时实例 {BASE}，日志 {log_path}")
    logf = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-u", "main.py"],
        cwd=str(V4), env=env, stdout=logf, stderr=subprocess.STDOUT,
    )
    for _ in range(120):
        time.sleep(0.5)
        if proc.poll() is not None:
            break
        if port_serving(PORT):
            return proc
    raise RuntimeError(f"临时实例未就绪，见 {log_path}")


def stop_instance(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
    print(f"已停止脚本自起的临时实例 {BASE}")


# ---------------------------------------------------------------------------
# 静态检查 / 构建产物
# ---------------------------------------------------------------------------
def run_cmd(label: str, cmd: str, cwd: Path, timeout: int = 600) -> tuple[bool, str]:
    proc = subprocess.run(cmd, cwd=str(cwd), shell=True, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout)
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    tail = "\n".join(output.splitlines()[-6:]) if output else "(无输出)"
    ok = proc.returncode == 0
    check(ok, f"{label} 退出码 0", f"exit={proc.returncode} | {tail}")
    return ok, output


def check_static() -> None:
    section("静态检查")
    run_cmd("gallery-web tsc -b --noEmit", "pnpm exec tsc -b --noEmit", GALLERY)
    run_cmd("gallery-web oxlint src", "pnpm exec oxlint src", GALLERY)
    run_cmd("Vue pnpm run typecheck", "pnpm run typecheck", FRONTEND)
    run_cmd("后端 import app.main", f'"{sys.executable}" -c "import app.main"', V4)


_META_RE = re.compile(r'(?:src|href)="([^"]+)"')


def check_dist_artifact() -> None:
    section("构建产物 C-BUILD-ARTIFACT@1（阶段一实例）")
    index_path = DIST / "index.html"
    if not check(index_path.exists(), "dist/index.html 存在", str(index_path)):
        return

    html = index_path.read_text(encoding="utf-8")
    refs = _META_RE.findall(html)
    asset_refs = [r for r in refs if not r.startswith("data:")]
    check(bool(asset_refs), "dist/index.html 含资源引用", f"{len(asset_refs)} 条")
    bad_refs = [r for r in asset_refs if not r.startswith("/ref-web/assets/")]
    check(not bad_refs, "dist/index.html 只引用 /ref-web/assets/", f"异常引用={bad_refs}")

    dist_files = [p for p in DIST.rglob("*") if p.is_file()]
    src_files = [p for p in (GALLERY / "src").rglob("*") if p.is_file()]
    check(bool(dist_files), "dist 产物非空", f"{len(dist_files)} 个文件")
    if dist_files and src_files:
        oldest_dist = min(p.stat().st_mtime for p in dist_files)
        newest_src = max(p.stat().st_mtime for p in src_files)
        check(oldest_dist > newest_src,
              "dist 全部产物 mtime 晚于最新源码",
              f"dist_min={time.strftime('%H:%M:%S', time.localtime(oldest_dist))} "
              f"src_max={time.strftime('%H:%M:%S', time.localtime(newest_src))}")

    # 字面量扫描：硬失败项 + 如实记录的旧数据路径
    scanned: dict[str, list[str]] = {lit: [] for lit in FORBIDDEN_LITERALS + LEGACY_DATA_LITERALS}
    for path in dist_files:
        if path.suffix in {".woff2", ".png", ".jpg", ".webp"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for lit in scanned:
            if lit in text:
                scanned[lit].append(path.relative_to(DIST).as_posix())

    for lit in FORBIDDEN_LITERALS:
        check(not scanned[lit], f"dist 不含旧模板字面量 {lit}", f"命中={scanned[lit]}")

    legacy_hits = {lit: files for lit, files in scanned.items()
                   if lit in LEGACY_DATA_LITERALS and files}
    if legacy_hits:
        detail = "; ".join(f"{lit} -> {files}" for lit, files in legacy_hits.items())
        observe("阶段一产物仍保留旧 /data/*.json 数据路径（计划阶段三 R3 才迁后端，属实记录）", detail)
    else:
        observe("阶段一产物已无旧 /data/*.json 数据路径")


# ---------------------------------------------------------------------------
# Playwright 通用工具
# ---------------------------------------------------------------------------
def _attach_errors(page, sink: list[str], tag: str) -> None:
    page.on("pageerror", lambda exc: sink.append(f"[{tag}] pageerror: {exc}"))
    page.on(
        "console",
        lambda msg: sink.append(f"[{tag}] console.{msg.type}: {msg.text}")
        if msg.type == "error" else None,
    )


def new_page(context, sink: list[str], tag: str):
    page = context.new_page()
    _attach_errors(page, sink, tag)
    return page


def wait_images_settled(page, timeout_ms: int = 30000) -> None:
    """滚到底触发懒加载，等到所有 <img> 完成解码（或超时）。"""
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(500)
    try:
        page.wait_for_function(
            "() => Array.from(document.images).every((i) => i.complete)",
            timeout=timeout_ms,
        )
    except Exception:
        pass
    page.wait_for_timeout(300)


def image_stats(page) -> dict:
    return page.evaluate(
        """() => {
            const imgs = Array.from(document.images)
            const broken = imgs.filter((i) => i.complete && i.naturalWidth === 0)
            const pending = imgs.filter((i) => !i.complete)
            return {
                total: imgs.length,
                broken: broken.length,
                pending: pending.length,
                brokenSrc: broken.slice(0, 5).map((i) => i.currentSrc || i.src),
            }
        }"""
    )


def goto_settle(page, path: str, anchor_text: str | None = None,
                expect_status: int = 200) -> int | None:
    resp = page.goto(BASE + path, wait_until="domcontentloaded", timeout=60000)
    status = resp.status if resp else None
    if anchor_text:
        try:
            page.get_by_text(anchor_text, exact=False).first.wait_for(
                state="visible", timeout=45000)
        except Exception:
            pass
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    return status


# ---------------------------------------------------------------------------
# 3a. 六路由 200 + console 0 错误
# ---------------------------------------------------------------------------
ROUTE_ANCHORS = {
    "/ref-web/": "AI 角色参考库",
    "/ref-web/poses": "动作姿势库",
    "/ref-web/costumes": "服装穿搭库",
    "/ref-web/portraits": "人像颜值库",
    "/ref-web/studio": "AI 角色合成台",
    "/ref-web/settings": "ComfyUI 连接",
}


def check_routes(context, shots_dir: Path) -> list[str]:
    section("3a 六路由 200 与 console 错误")
    errors: list[str] = []
    page = new_page(context, errors, "routes")
    for route in ROUTES:
        status = goto_settle(page, route, ROUTE_ANCHORS.get(route))
        check(status == 200, f"GET {route} 返回 200", f"status={status} url={page.url}")
        shot = shots_dir / f"route{route.strip('/').replace('/', '_') or 'index'}.png"
        page.screenshot(path=str(shot), full_page=False)
    check(not errors, "六路由 console error / pageerror 为 0", "; ".join(errors[:5]))
    page.close()
    return errors


# ---------------------------------------------------------------------------
# 3b. 返回画廊 3 个入口
# ---------------------------------------------------------------------------
def check_gallery_entries(page, tag: str) -> None:
    gallery_links = page.locator('a[href="/gallery"]')
    count = gallery_links.count()
    hrefs = gallery_links.evaluate_all("els => els.map((e) => e.getAttribute('href'))")
    check(count == 3, f"[{tag}] 返回画廊入口 3 个", f"count={count} hrefs={hrefs}")

    derived = page.locator('a[href="/ref-web/gallery"]')
    check(derived.count() == 0, f"[{tag}] 无 /ref-web/gallery 拼接链接",
          f"count={derived.count()}")

    header = page.locator('header a[aria-label="返回画室画廊"]')
    check(header.count() == 1 and header.first.get_attribute("href") == "/gallery",
          f"[{tag}] 顶栏「画室画廊」是原生链接", f"count={header.count()}")

    back = page.locator('a[href="/gallery"]:has-text("返回画廊")')
    check(back.count() == 1, f"[{tag}] 侧栏「返回画廊」是原生链接", f"count={back.count()}")

    brand = page.locator('a[href="/gallery"]:has-text("参考图库")')
    check(brand.count() == 1 and "画室" in (brand.first.inner_text() if brand.count() else ""),
          f"[{tag}] 侧栏 brand 是原生链接", f"count={brand.count()}")


def check_gallery_entries_all(context, shots_dir: Path) -> None:
    section("3b 返回画廊入口")
    errors: list[str] = []
    page = new_page(context, errors, "entries")
    for route in ROUTES:
        goto_settle(page, route, ROUTE_ANCHORS.get(route))
        check_gallery_entries(page, route)
    shot = shots_dir / "gallery_entries_settings.png"
    page.screenshot(path=str(shot))
    check(not errors, "返回入口检查期间无 console error", "; ".join(errors[:5]))
    page.close()


# ---------------------------------------------------------------------------
# 3c. 18+ 首次确认只弹一次
# ---------------------------------------------------------------------------
def _alertdialog(page):
    return page.locator('[role="alertdialog"]')


def check_nsfw_age_gate(browser, shots_dir: Path) -> None:
    section("3c 18+ 首次确认只弹一次")
    ctx = browser.new_context(viewport={"width": 1500, "height": 950})
    errors: list[str] = []
    page = new_page(ctx, errors, "nsfw")
    goto_settle(page, "/ref-web/poses", "动作姿势库")

    confirmed = page.evaluate(
        "(k) => localStorage.getItem(k)", NSFW_CONFIRMED_KEY)
    check(confirmed is None, "初始 context 无 18+ 确认记忆键", f"value={confirmed}")

    # 首次点击：必须弹确认框
    page.locator('header button[title^="当前已开启安全模式"]').first.click()
    try:
        _alertdialog(page).first.wait_for(state="visible", timeout=8000)
    except Exception:
        pass
    visible = _alertdialog(page).count()
    check(visible == 1, "首次点击 18+ 弹出确认框", f"alertdialog={visible}")
    if visible:
        check("18+ 内容确认" in _alertdialog(page).first.inner_text(),
              "确认框标题正确", _alertdialog(page).first.inner_text()[:40])
        page.screenshot(path=str(shots_dir / "nsfw_first_dialog.png"))
        page.get_by_role("button", name="我已年满 18 周岁").click()
        page.wait_for_timeout(700)

    marker = page.evaluate("(k) => localStorage.getItem(k)", NSFW_CONFIRMED_KEY)
    check(marker == "true", "确认后写入记忆键 pose_atlas_nsfw_confirmed_v1", f"value={marker}")
    check(_alertdialog(page).count() == 0, "确认后弹窗关闭", f"count={_alertdialog(page).count()}")
    unlocked_title = page.locator('header button[title^="当前已显示 18+"]').count()
    check(unlocked_title == 1, "确认后进入 18+ 完整模式", f"header button={unlocked_title}")

    # 切回安全模式：不撤销记忆键
    page.locator('header button[title^="当前已显示 18+"]').first.click()
    page.wait_for_timeout(500)
    safe_title = page.locator('header button[title^="当前已开启安全模式"]').count()
    check(safe_title == 1, "可切回安全模式", f"header button={safe_title}")
    check(_alertdialog(page).count() == 0, "切回安全模式不弹确认框", "")

    # 再次开启：不应重复弹窗
    page.locator('header button[title^="当前已开启安全模式"]').first.click()
    page.wait_for_timeout(900)
    re_dialog = _alertdialog(page).count()
    check(re_dialog == 0, "二次开启 18+ 不重复弹确认框", f"alertdialog={re_dialog}")
    reopened = page.locator('header button[title^="当前已显示 18+"]').count()
    check(reopened == 1, "二次开启直接进入 18+ 完整模式", f"header button={reopened}")
    marker2 = page.evaluate("(k) => localStorage.getItem(k)", NSFW_CONFIRMED_KEY)
    check(marker2 == "true", "记忆键在二次开启后仍存在", f"value={marker2}")
    page.screenshot(path=str(shots_dir / "nsfw_second_unlock.png"))

    check(not errors, "18+ 交互期间无 console error", "; ".join(errors[:5]))
    page.close()
    ctx.close()

    # 对抗性探针：点「保持安全模式」必须不写记忆键、不切换模式
    section("3c-probe 18+ 取消路径")
    ctx2 = browser.new_context(viewport={"width": 1500, "height": 950})
    errors2: list[str] = []
    p2 = new_page(ctx2, errors2, "nsfw-cancel")
    goto_settle(p2, "/ref-web/poses", "动作姿势库")
    p2.locator('header button[title^="当前已开启安全模式"]').first.click()
    try:
        _alertdialog(p2).first.wait_for(state="visible", timeout=8000)
    except Exception:
        pass
    p2.get_by_role("button", name="保持安全模式").click()
    p2.wait_for_timeout(600)
    check(p2.evaluate("(k) => localStorage.getItem(k)", NSFW_CONFIRMED_KEY) is None,
          "取消 18+ 确认不写记忆键", "")
    check(p2.locator('header button[title^="当前已开启安全模式"]').count() == 1,
          "取消 18+ 确认后仍处于安全模式", "")
    check(_alertdialog(p2).count() == 0, "取消后弹窗关闭", "")
    ctx2.close()


# ---------------------------------------------------------------------------
# 3d. studio 工作流下拉选中后端 default
# ---------------------------------------------------------------------------
def check_studio_workflow_default(context, shots_dir: Path) -> None:
    section("3d 合成台工作流下拉选中后端 default")
    errors: list[str] = []
    page = new_page(context, errors, "studio-workflow")
    catalog = api_json("/api/workflows?scope=studio")
    default_path = catalog.get("default") or ""
    workflows = catalog.get("workflows") or []
    check(bool(default_path), "后端返回 workflows.default", f"default={default_path}")
    check(default_path in [w.get("path") for w in workflows],
          "default 存在于 workflows 列表", f"count={len(workflows)}")
    first_path = workflows[0].get("path") if workflows else None
    check(bool(first_path) and first_path != default_path,
          "本机列表第一项 != default（本用例具备区分力）",
          f"first={first_path}")

    goto_settle(page, "/ref-web/studio", "AI 角色合成台")
    try:
        page.wait_for_function(
            """() => {
                try {
                    const raw = localStorage.getItem('pose_atlas_api_config_v3')
                    if (!raw) return false
                    const cfg = JSON.parse(raw)
                    return Boolean(cfg?.comfyuiParams?.workflowPreset)
                } catch { return false }
            }""",
            timeout=45000,
        )
    except Exception:
        pass
    stored = page.evaluate(
        """() => {
            try {
                const cfg = JSON.parse(localStorage.getItem('pose_atlas_api_config_v3') || '{}')
                return cfg?.comfyuiParams?.workflowPreset || ''
            } catch { return '' }
        }"""
    )
    check(stored == default_path, "工作流下拉选中值 == 后端 default",
          f"stored={stored}")
    check(stored != first_path, "选中值不是列表第一项", f"first={first_path}")

    default_workflow = next((w for w in workflows if w.get("path") == default_path), {})
    default_label = re.sub(r"\.api\.json$|\.json$", "", default_workflow.get("name", ""))
    trigger_text = ""
    try:
        trigger = page.locator('section:has(h2:has-text("模型与参数")) button[role="combobox"]').first
        trigger_text = trigger.inner_text().strip()
    except Exception:
        pass
    check(bool(default_label) and default_label in trigger_text,
          "下拉框显示文本包含 default 工作流名",
          f"trigger={trigger_text!r} expected_contains={default_label!r}")
    page.screenshot(path=str(shots_dir / "studio_workflow_dropdown.png"))
    check(not errors, "studio 工作流加载无 console error", "; ".join(errors[:5]))
    page.close()


# ---------------------------------------------------------------------------
# 3e. 四库页裂图（正常网络 + 屏蔽外部域名）
# ---------------------------------------------------------------------------
def check_library_images(context, shots_dir: Path) -> None:
    section("3e-1 四库页正常网络裂图")
    errors: list[str] = []
    page = new_page(context, errors, "library-normal")
    for route in LIBRARY_ROUTES:
        goto_settle(page, route, ROUTE_ANCHORS.get(route))
        wait_images_settled(page)
        stats = image_stats(page)
        name = route.strip("/").replace("/", "_") or "index"
        page.screenshot(path=str(shots_dir / f"library_normal_{name}.png"))
        check(stats["total"] > 0, f"{route} 有图片渲染", f"imgs={stats['total']}")
        check(stats["broken"] == 0, f"{route} 正常网络裂图为 0",
              f"broken={stats['broken']} pending={stats['pending']} src={stats['brokenSrc']}")
        check(stats["pending"] == 0, f"{route} 无未完成加载的图片",
              f"pending={stats['pending']}")
    check(not errors, "四库页正常网络无 console error", "; ".join(errors[:5]))
    page.close()


def _make_external_blocker(context):
    def handler(route):
        url = route.request.url
        parsed = urlsplit(url)
        if parsed.scheme in ("http", "https") and parsed.hostname not in ("127.0.0.1", "localhost"):
            route.abort()
        else:
            route.continue_()
    context.route("**/*", handler)


def check_library_images_offline(browser, shots_dir: Path) -> None:
    section("3e-2 断网（屏蔽外部域名）四库页裂图")
    ctx = browser.new_context(viewport={"width": 1500, "height": 950})
    _make_external_blocker(ctx)
    errors: list[str] = []
    page = new_page(ctx, errors, "library-offline")
    for route in LIBRARY_ROUTES:
        goto_settle(page, route, ROUTE_ANCHORS.get(route))
        wait_images_settled(page)
        stats = image_stats(page)
        name = route.strip("/").replace("/", "_") or "index"
        page.screenshot(path=str(shots_dir / f"library_offline_{name}.png"))
        check(stats["broken"] == 0, f"{route} 断网重载裂图为 0",
              f"broken={stats['broken']} pending={stats['pending']} src={stats['brokenSrc']}")

    # 对抗性探针：二次元服装缩略图是外链，阶段二缓存未实现前断网必然裂图。
    goto_settle(page, "/ref-web/costumes", "服装穿搭库")
    try:
        page.get_by_role("button", name="二次元", exact=True).click()
        page.wait_for_timeout(1200)
        wait_images_settled(page)
    except Exception as exc:
        observe("二次元筛选点击失败", str(exc))
    probe = image_stats(page)
    page.screenshot(path=str(shots_dir / "library_offline_costume_anime.png"))
    observe(
        "对抗性探针：断网下切到「二次元」服装（外链 charadb 缩略图）",
        f"broken={probe['broken']}/{probe['total']} pending={probe['pending']} "
        "——阶段二前端仍读 JSON、缩略图仍是外链（阶段三 R3 才切后端端点），属预期表现",
    )
    observe("断网阶段 console 记录数（包含被中止的外部请求，非阶段一硬检查）", str(len(errors)))
    ctx.close()


# ---------------------------------------------------------------------------
# 3f. 设置页导出旧 IDB 历史
# ---------------------------------------------------------------------------
IDB_READ_JS = """
(key) => new Promise((resolve) => {
    const DB_NAME = 'pose_atlas_studio_db'
    const STORE_NAME = 'kv_store'
    const req = indexedDB.open(DB_NAME, 1)
    req.onupgradeneeded = () => {
        if (!req.result.objectStoreNames.contains(STORE_NAME)) req.result.createObjectStore(STORE_NAME)
    }
    req.onsuccess = () => {
        const db = req.result
        try {
            const tx = db.transaction(STORE_NAME, 'readonly')
            const getReq = tx.objectStore(STORE_NAME).get(key)
            getReq.onsuccess = () => { db.close(); resolve(getReq.result === undefined ? null : getReq.result) }
            getReq.onerror = () => { db.close(); resolve(null) }
        } catch (e) { db.close(); resolve(null) }
    }
    req.onerror = () => resolve(null)
})
"""

IDB_WRITE_JS = """
([key, value]) => new Promise((resolve, reject) => {
    const DB_NAME = 'pose_atlas_studio_db'
    const STORE_NAME = 'kv_store'
    const req = indexedDB.open(DB_NAME, 1)
    req.onupgradeneeded = () => {
        if (!req.result.objectStoreNames.contains(STORE_NAME)) req.result.createObjectStore(STORE_NAME)
    }
    req.onsuccess = () => {
        const db = req.result
        const tx = db.transaction(STORE_NAME, 'readwrite')
        tx.objectStore(STORE_NAME).put(value, key)
        tx.oncomplete = () => { db.close(); resolve(true) }
        tx.onerror = () => { db.close(); reject(tx.error) }
    }
    req.onerror = () => reject(req.error)
})
"""

IDB_DELETE_JS = """
(key) => new Promise((resolve, reject) => {
    const DB_NAME = 'pose_atlas_studio_db'
    const STORE_NAME = 'kv_store'
    const req = indexedDB.open(DB_NAME, 1)
    req.onupgradeneeded = () => {
        if (!req.result.objectStoreNames.contains(STORE_NAME)) req.result.createObjectStore(STORE_NAME)
    }
    req.onsuccess = () => {
        const db = req.result
        const tx = db.transaction(STORE_NAME, 'readwrite')
        tx.objectStore(STORE_NAME).delete(key)
        tx.oncomplete = () => { db.close(); resolve(true) }
        tx.onerror = () => { db.close(); reject(tx.error) }
    }
    req.onerror = () => reject(req.error)
})
"""


def idb_read(page, key: str):
    return page.evaluate(IDB_READ_JS, key)


def idb_write(page, key: str, value) -> None:
    page.evaluate(IDB_WRITE_JS, [key, value])


def idb_delete(page, key: str) -> None:
    page.evaluate(IDB_DELETE_JS, key)


def _wait_downloads(page, expected: int, timeout_s: float = 15.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if len(pending_downloads[0]) >= expected:
            return
        page.wait_for_timeout(200)


def _notice_texts(page) -> list[str]:
    """本项目的通知区是自研 Toaster（`.app-notices` / `[data-notice-id]`），
    不是 sonner 默认的 `[data-sonner-toast]`。"""
    notices = page.locator("[data-notice-id]")
    return [notices.nth(i).inner_text() for i in range(notices.count())]


def _wait_notice_contains(page, needle: str, timeout_s: float = 8.0) -> str:
    deadline = time.time() + timeout_s
    last: list[str] = []
    while time.time() < deadline:
        last = _notice_texts(page)
        for text in last:
            if needle in text:
                return text
        page.wait_for_timeout(150)
    return " | ".join(last)


pending_downloads: list[list[dict]] = [[]]
download_dirs = {"current": "", "step": ""}


def _install_download_handler(page) -> None:
    def on_download(download):
        target_dir = download_dirs["current"]
        name = download.suggested_filename
        path = os.path.join(target_dir, name)
        try:
            download.save_as(path)
            pending_downloads[0].append(
                {"step": download_dirs["step"], "name": name, "path": path})
        except Exception as exc:  # 保存失败也要留痕
            pending_downloads[0].append(
                {"step": download_dirs["step"], "name": name, "path": "", "error": str(exc)})
    page.on("download", on_download)


def check_settings_export(browser, shots_dir: Path) -> None:
    section("3f 设置页导出旧生成记录")
    ctx = browser.new_context(viewport={"width": 1500, "height": 950}, accept_downloads=True)
    errors: list[str] = []
    page = new_page(ctx, errors, "settings-export")
    _install_download_handler(page)
    goto_settle(page, "/ref-web/settings", "ComfyUI 连接")

    button = page.locator('button:has-text("导出旧生成记录")')
    check(button.count() == 1, "设置页存在「导出旧生成记录」按钮", f"count={button.count()}")
    page.wait_for_timeout(800)
    check(button.first.is_disabled(), "无旧记录时按钮 disabled", "")
    body_text = page.locator("body").inner_text()
    check("未发现旧生成记录" in body_text, "无旧记录时显示「未发现旧生成记录」", "")
    page.screenshot(path=str(shots_dir / "settings_export_empty.png"))

    # ---- 注入 1 条合法记录 ----
    record = {
        "id": "legacy-1",
        "createdAt": 1700000000000,
        "provider": "comfyui",
        "model": "test-model-v1",
        "prompt": "a test prompt for legacy export",
        "recipeSummary": "测试配方摘要",
        "imageUrl": TINY_PNG_DATA_URL,
    }
    idb_write(page, LEGACY_HISTORY_KEY, [record])
    injected = idb_read(page, LEGACY_HISTORY_KEY)
    check(isinstance(injected, list) and len(injected) == 1,
          "IndexedDB 注入 1 条 pose_atlas_history_v3 记录",
          f"db={IDB_NAME} store={IDB_STORE} count={len(injected) if isinstance(injected, list) else 'n/a'}")

    page.reload(wait_until="domcontentloaded")
    page.get_by_text("ComfyUI 连接", exact=False).first.wait_for(state="visible", timeout=30000)
    page.wait_for_timeout(1200)
    check(not button.first.is_disabled(), "有旧记录时按钮可点击", "")
    check("共发现 1 条旧生成记录" in page.locator("body").inner_text(),
          "页面显示「共发现 1 条旧生成记录」", "")

    # ---- 导出：期望 JSON 1 + PNG 1 ----
    step1_dir = str(shots_dir / "downloads_step1")
    os.makedirs(step1_dir, exist_ok=True)
    download_dirs["current"] = step1_dir
    download_dirs["step"] = "step1"
    pending_downloads[0] = []
    page.screenshot(path=str(shots_dir / "settings_export_one_record.png"))
    button.first.click()
    _wait_downloads(page, 2, timeout_s=20.0)
    downloads = [d for d in pending_downloads[0] if d["step"] == "step1"]
    names = [d["name"] for d in downloads]
    check(len(downloads) == 2, "点击导出产生 2 个下载（JSON + PNG）", f"downloads={names}")

    json_files = [d for d in downloads if d["name"].endswith(".json")]
    png_files = [d for d in downloads if d["name"].endswith(".png")]
    check(len(json_files) == 1, "导出 JSON 数量为 1", f"{[d['name'] for d in json_files]}")
    check(len(png_files) == 1, "导出 PNG 数量为 1", f"{[d['name'] for d in png_files]}")

    if json_files:
        json_name = json_files[0]["name"]
        check(bool(re.fullmatch(r"gallery-web-legacy-history-\d{8}-\d{6}\.json", json_name)),
              "JSON 文件命名符合 gallery-web-legacy-history-YYYYMMDD-HHmmss.json",
              json_name)
        payload = json.loads(Path(json_files[0]["path"]).read_text(encoding="utf-8"))
        check(isinstance(payload, list) and len(payload) == 1,
              "JSON 内容为 1 条记录的数组", f"len={len(payload) if isinstance(payload, list) else 'n/a'}")
        if isinstance(payload, list) and payload:
            keys = {"id", "createdAt", "prompt", "recipeSummary", "model", "imageUrl"}
            check(keys.issubset(payload[0].keys()), "JSON 字段含 id/createdAt/prompt/recipeSummary/model/imageUrl",
                  f"keys={sorted(payload[0].keys())}")
            check(payload[0].get("id") == "legacy-1", "JSON 中 id 正确", str(payload[0].get("id")))
            check(str(payload[0].get("imageUrl", "")).startswith("data:image/png;base64,"),
                  "JSON 中 imageUrl 保留 base64 data URL",
                  str(payload[0].get("imageUrl", ""))[:40])

    if png_files:
        raw = Path(png_files[0]["path"]).read_bytes()
        check(raw.startswith(b"\x89PNG\r\n\x1a\n"), "PNG 文件头合法",
              f"size={len(raw)} name={png_files[0]['name']}")
        check(bool(re.fullmatch(r"legacy-1-legacy-1\.png", png_files[0]["name"])),
              "PNG 命名可辨认（legacy-{index}-{id}.png）", png_files[0]["name"])

    toast_text = _wait_notice_contains(page, "已导出 1 条旧生成记录")
    check("已导出 1 条旧生成记录" in toast_text, "导出后 toast 汇总数量", f"toast={toast_text[:80]!r}")

    remaining = idb_read(page, LEGACY_HISTORY_KEY)
    check(isinstance(remaining, list) and len(remaining) == 1,
          "导出后 IDB 中 pose_atlas_history_v3 仍存在（未被删除）",
          f"count={len(remaining) if isinstance(remaining, list) else 'n/a'}")
    page.screenshot(path=str(shots_dir / "settings_export_done.png"))

    # ---- 对抗性探针：1 条坏图记录 + 1 条好图记录 ----
    bad = dict(record, id="legacy-bad", imageUrl="not-a-url")
    idb_write(page, LEGACY_HISTORY_KEY, [record, bad])
    page.reload(wait_until="domcontentloaded")
    page.get_by_text("ComfyUI 连接", exact=False).first.wait_for(state="visible", timeout=30000)
    page.wait_for_timeout(1200)
    check("共发现 2 条旧生成记录" in page.locator("body").inner_text(),
          "注入 2 条后页面计数为 2", "")

    step2_dir = str(shots_dir / "downloads_step2")
    os.makedirs(step2_dir, exist_ok=True)
    download_dirs["current"] = step2_dir
    download_dirs["step"] = "step2"
    pending_downloads[0] = []
    button.first.click()
    _wait_downloads(page, 2, timeout_s=20.0)
    d2 = [d for d in pending_downloads[0] if d["step"] == "step2"]
    names2 = [d["name"] for d in d2]
    check(len(d2) == 2, "坏图记录不阻止整体导出（JSON 1 + PNG 1）", f"downloads={names2}")
    check(sum(1 for d in d2 if d["name"].endswith(".json")) == 1, "仍导出 1 个 JSON", str(names2))
    check(sum(1 for d in d2 if d["name"].endswith(".png")) == 1, "坏图仅跳过该张 PNG", str(names2))
    toast2 = _wait_notice_contains(page, "失败 1 张")
    check("失败 1 张" in toast2, "单张失败在 toast 中提示", f"toast={toast2[:120]!r}")
    kept2 = idb_read(page, LEGACY_HISTORY_KEY)
    check(isinstance(kept2, list) and len(kept2) == 2, "坏图导出后 IDB 原始数据仍保留 2 条",
          f"count={len(kept2) if isinstance(kept2, list) else 'n/a'}")
    page.screenshot(path=str(shots_dir / "settings_export_partial_failure.png"))

    # ---- 清空后恢复禁用态 ----
    idb_delete(page, LEGACY_HISTORY_KEY)
    page.reload(wait_until="domcontentloaded")
    page.get_by_text("ComfyUI 连接", exact=False).first.wait_for(state="visible", timeout=30000)
    page.wait_for_timeout(1200)
    check(button.first.is_disabled(), "清空旧记录后按钮恢复 disabled", "")
    check("未发现旧生成记录" in page.locator("body").inner_text(),
          "清空后显示「未发现旧生成记录」", "")
    check(idb_read(page, LEGACY_HISTORY_KEY) is None, "清理后 IDB key 确实不存在", "")
    page.screenshot(path=str(shots_dir / "settings_export_cleared.png"))

    # ---- 对抗性探针：IDB 值是脏数据（非数组 / 条目缺 id）时不得崩溃 ----
    idb_write(page, LEGACY_HISTORY_KEY, {"oops": "not-an-array"})
    page.reload(wait_until="domcontentloaded")
    page.get_by_text("ComfyUI 连接", exact=False).first.wait_for(state="visible", timeout=30000)
    page.wait_for_timeout(1000)
    check(button.first.is_disabled(), "IDB 值为非数组时按钮 disabled（读取失败降级）", "")
    check("未发现旧生成记录" in page.locator("body").inner_text(),
          "脏数据（非数组）显示「未发现旧生成记录」", "")

    idb_write(page, LEGACY_HISTORY_KEY, [{"noId": True}, "garbage", 42])
    page.reload(wait_until="domcontentloaded")
    page.get_by_text("ComfyUI 连接", exact=False).first.wait_for(state="visible", timeout=30000)
    page.wait_for_timeout(1000)
    check(button.first.is_disabled(), "条目全部缺 id 时按钮 disabled（normalize 过滤）", "")
    check("未发现旧生成记录" in page.locator("body").inner_text(),
          "脏数据（条目缺 id）显示「未发现旧生成记录」", "")
    idb_delete(page, LEGACY_HISTORY_KEY)
    page.screenshot(path=str(shots_dir / "settings_export_dirty_idb.png"))

    check(not errors, "设置页导出流程无 console error", "; ".join(errors[:5]))
    ctx.close()


# ---------------------------------------------------------------------------
# 3g. 合成台生成记录区来自 /api/images
# ---------------------------------------------------------------------------
HISTORY_SECTION_JS = """
() => {
    const h2 = Array.from(document.querySelectorAll('h2'))
        .find((e) => (e.textContent || '').includes('来自 atelier 画廊的历史'))
    if (!h2) return { rendered: false, cards: 0, imgs: 0, broken: 0, pending: 0, text: '' }
    const sec = h2.closest('section')
    const grid = sec ? sec.querySelector(':scope > div.mt-4') : null
    const cards = grid ? grid.children.length : 0
    const imgs = Array.from(sec.querySelectorAll('img'))
    const broken = imgs.filter((i) => i.complete && i.naturalWidth === 0)
    return {
        rendered: true,
        cards,
        imgs: imgs.length,
        broken: broken.length,
        pending: imgs.filter((i) => !i.complete).length,
        brokenSrc: broken.slice(0, 5).map((i) => i.currentSrc || i.src),
        text: sec.innerText.slice(0, 200),
    }
}
"""


def check_history_section(context, shots_dir: Path) -> None:
    section("3g 生成记录区（GET /api/images）")
    errors: list[str] = []
    page = new_page(context, errors, "history")
    goto_settle(page, "/ref-web/studio", "AI 角色合成台")

    api = api_json("/api/images?page=1&page_size=30&sort=newest")
    total = api.get("total", 0)
    expected_cards = min(total, 30)
    try:
        page.wait_for_function(
            """(expected) => {
                const h2 = Array.from(document.querySelectorAll('h2'))
                    .find((e) => (e.textContent || '').includes('来自 atelier 画廊的历史'))
                if (!h2) return expected === 0
                const grid = h2.closest('section')?.querySelector(':scope > div.mt-4')
                return (grid ? grid.children.length : 0) >= Math.min(expected, 1)
            }""",
            arg=expected_cards,
            timeout=45000,
        )
    except Exception:
        pass
    page.wait_for_timeout(1500)
    stats = page.evaluate(HISTORY_SECTION_JS)
    page.screenshot(path=str(shots_dir / "studio_history_section.png"))

    if expected_cards == 0:
        check(not stats["rendered"], "/api/images 为空时整区不渲染", f"stats={stats}")
    else:
        check(stats["rendered"], "生成记录区已渲染", f"total={total}")
        check(stats["cards"] == expected_cards,
              "卡片数量 == min(GET /api/images total, 30)",
              f"cards={stats['cards']} total={total} expected={expected_cards}")
        check(stats["broken"] == 0, "历史卡片无裂图",
              f"broken={stats['broken']} pending={stats['pending']} src={stats.get('brokenSrc')}")
        check("undefined" not in (stats.get("text") or ""), "历史卡片无 undefined 文本",
              (stats.get("text") or "")[:120])

    # 合成台不再写本地历史：IDB key 不存在
    local_hist = idb_read(page, LEGACY_HISTORY_KEY)
    check(local_hist is None, "合成台不再写 pose_atlas_history_v3",
          f"value={'null' if local_hist is None else 'present'}")

    # 对比 page 内 fetch 的 total 与卡片数
    fetched_total = page.evaluate(
        """async () => {
            const res = await fetch('/api/images?page=1&page_size=30&sort=newest')
            const body = await res.json()
            return { total: body.total, items: body.items.length }
        }"""
    )
    check(fetched_total["items"] == expected_cards,
          "page.evaluate fetch 的 items 数 == 卡片数",
          f"items={fetched_total['items']} cards={stats['cards']} total={fetched_total['total']}")
    check(not errors, "生成记录区无 console error", "; ".join(errors[:5]))
    page.close()


def check_history_empty_mock(browser, shots_dir: Path) -> None:
    section("3g-probe /api/images 空列表时整区不渲染（route mock）")
    ctx = browser.new_context(viewport={"width": 1500, "height": 950})
    errors: list[str] = []
    page = new_page(ctx, errors, "history-empty")

    def fulfill(route):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"items": [], "total": 0, "page": 1, "page_size": 30}))

    page.route(re.compile(r".*/api/images\b.*"), fulfill)
    goto_settle(page, "/ref-web/studio", "AI 角色合成台")
    page.wait_for_timeout(2500)
    stats = page.evaluate(HISTORY_SECTION_JS)
    check(not stats["rendered"], "mock 空列表时生成记录区不渲染", f"stats={stats}")
    broken = image_stats(page)["broken"]
    check(broken == 0, "mock 空列表时无裂图", f"broken={broken}")
    page.screenshot(path=str(shots_dir / "studio_history_empty_mock.png"))
    check(not errors, "mock 空列表无 console error", "; ".join(errors[:5]))
    ctx.close()


# ---------------------------------------------------------------------------
# 阶段二（T7）：外链缓存 / 图片端点 / recipes
# ---------------------------------------------------------------------------
def _anime_items(size: int) -> list[dict]:
    data = api_json(f"/api/reference/items?library=costume-anime&page_size={size}")
    return list(data.get("items") or [])


def _pick_uncached(items: list[dict]) -> dict | None:
    cached = _cached_item_ids()
    for item in items:
        if item.get("id") not in cached:
            return item
    return None


def check_phase2_dto() -> None:
    section("阶段二-1 costume-anime DTO 契约 C-REF-ITEM-DTO@2")
    status, ctype, text = api_request("/api/reference/items?library=costume-anime&page_size=5")
    check(status == 200, "GET items costume-anime 返回 200", f"status={status}")
    try:
        body = json.loads(text)
    except Exception as exc:
        check(False, "items 响应是合法 JSON", f"{exc}: {text[:120]}")
        return
    items = body.get("items") or []
    check(body.get("total") == 440, "costume-anime total == 440", f"total={body.get('total')}")
    check(len(items) == 5, "page_size=5 返回 5 条", f"len={len(items)}")
    if not items:
        return
    first = items[0]
    required = {"number", "search_text", "source_url", "depth_url",
                "depth_thumb_url", "remote", "thumb_url", "image_url", "library"}
    missing = sorted(required - set(first))
    check(not missing, "DTO 含新增字段", f"missing={missing}")

    prefix = "/api/reference/items/costume-anime/"
    thumb, image = first.get("thumb_url"), first.get("image_url")
    check(first.get("remote") is True, "`remote` 仍为 true", f"remote={first.get('remote')}")
    check(first.get("depth_url") is None and first.get("depth_thumb_url") is None,
          "外链库 depth_url/depth_thumb_url 恒为 null",
          f"depth={first.get('depth_url')} depth_thumb={first.get('depth_thumb_url')}")
    check(bool(thumb) and thumb.startswith(prefix) and "kind=thumb" in thumb,
          "thumb_url 是后端端点", f"thumb_url={thumb}")
    check(bool(image) and image.startswith(prefix) and "kind=image" in image,
          "image_url 是后端端点", f"image_url={image}")
    external = "charadb-2fi.pages.dev"
    check(external not in (thumb or "") + (image or "") and "https://" not in (thumb or "") + (image or ""),
          "DTO 图片 URL 不再返回外链域名", f"{thumb} | {image}")
    check(first.get("number") == "", "costume-anime 的 number 为空串", f"number={first.get('number')!r}")
    check(bool(first.get("search_text")), "search_text 非空",
          f"len={len(first.get('search_text') or '')}")
    check(isinstance(first.get("source_url"), (str, type(None))),
          "source_url 字段存在且为 str|null", f"source_url={first.get('source_url')}")

    # 边界：page_size 上限 200
    oversized = api_json("/api/reference/items?library=costume-anime&page_size=500")
    check(oversized.get("page_size") == 200, "page_size 超出按 200 截断",
          f"page_size={oversized.get('page_size')}")

    # 对抗性探针：未知 kind / depth 对 anime 必须是 404，而不是 200 或 500
    item_id = first["id"]
    for kind, expect in (("depth", 404), ("depth_thumb", 404), ("bogus", 404)):
        st, _, btext = api_request(f"/api/reference/items/costume-anime/{item_id}/image?kind={kind}")
        check(st == expect, f"anime/{kind} 返回 {expect}", f"status={st} body={btext[:120]}")


def check_phase2_image_cache() -> None:
    section("阶段二-2 图片端点缓存优先（R2-AC1/AC2）")
    items = _anime_items(12)
    cached_ids = _cached_item_ids()
    cached = next((it for it in items if it.get("id") in cached_ids), None)
    check(cached is not None, "存在已缓存探针条目", f"cached_ids={sorted(cached_ids)[:5]}...")
    if cached is not None:
        cid = cached["id"]
        before = cache_snapshot()
        for kind in ("thumb", "image"):
            for attempt in (1, 2):
                status, ctype, _ = api_request(
                    f"/api/reference/items/costume-anime/{cid}/image?kind={kind}")
                check(status == 200, f"已缓存 {cid}/{kind} 第{attempt}次 200", f"status={status}")
                check(ctype.startswith("image/"),
                      f"已缓存 {cid}/{kind} 第{attempt}次 Content-Type image/*",
                      f"content-type={ctype}")
        after = cache_snapshot()
        changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
        check(not changed, "已缓存条目双次请求不新增/改写缓存文件",
              f"before={len(before)} after={len(after)} changed={sorted(changed)[:5]}")
    else:
        cid = None

    # 未缓存条目：首次下载落盘，第二次不再变化（真实外网；失败则如实标注）
    uncached = _pick_uncached(_anime_items(60))
    if uncached is None:
        observe("60 条内全部已缓存，跳过“未缓存下载落盘”探针")
    else:
        uid = uncached["id"]
        before = cache_snapshot()
        status, ctype, text = api_request(
            f"/api/reference/items/costume-anime/{uid}/image?kind=image")
        after = cache_snapshot()
        check(status == 200, f"未缓存 {uid} 首次请求 200", f"status={status} body={text[:120]}")
        check(ctype.startswith("image/"), f"未缓存 {uid} 首次 Content-Type image/*",
              f"content-type={ctype}")
        added = sorted(set(after) - set(before))
        check(bool(added), f"未缓存 {uid} 首次下载后出现缓存文件", f"added={added[:3]}")
        status2, ctype2, _ = api_request(
            f"/api/reference/items/costume-anime/{uid}/image?kind=image")
        after2 = cache_snapshot()
        check(status2 == 200 and ctype2.startswith("image/"),
              f"未缓存 {uid} 第二次 200 + image/*", f"status={status2} ct={ctype2}")
        check(after2 == after, f"未缓存 {uid} 第二次不新增缓存文件",
              f"before={len(after)} after={len(after2)}")

    # 本地库图片端点不回归
    local = api_json("/api/reference/items?library=costume&page_size=1")["items"]
    if local:
        st, ct, _ = api_request(f"/api/reference/items/costume/{local[0]['id']}/image?kind=image")
        check(st == 200 and ct.startswith("image/"), "本地 costume 图片端点仍 200 + image/*",
              f"status={st} ct={ct}")


def check_phase2_offline() -> None:
    section("阶段二-3 断网等价：未缓存 502 / 已缓存 200（服务端不可达代理）")
    cached_ids = _cached_item_ids()
    cached = next(iter(sorted(cached_ids)), None)
    check(bool(cached), "存在已缓存探针条目", f"cached={cached}")
    if cached:
        for kind in ("thumb", "image"):
            st, ct, _ = api_request(
                f"/api/reference/items/costume-anime/{cached}/image?kind={kind}")
            check(st == 200 and ct.startswith("image/"),
                  f"断网下已缓存 {cached}/{kind} 仍 200 + image/*", f"status={st} ct={ct}")

    uncached = _pick_uncached(_anime_items(200))
    if uncached is None:
        observe("200 条内全部已缓存，跳过未缓存 502 探针")
    else:
        uid = uncached["id"]
        before = cache_snapshot()
        st, ctype, text = api_request(
            f"/api/reference/items/costume-anime/{uid}/image?kind=image")
        after = cache_snapshot()
        check(st == 502, f"断网下未缓存 {uid} 返回 502", f"status={st} body={text[:160]}")
        check("外链图片下载失败" in text, "502 detail 可读且为 JSON",
              f"content-type={ctype} body={text[:160]}")
        check("<html" not in text.lower(), "502 未把 HTML 错误页当图片返回", "")
        check(after == before, "下载失败不留下缓存文件/临时文件",
              f"before={len(before)} after={len(after)}")
        leftovers = [k for k in after if k.startswith(f"costume-anime/{uid}/") or k.endswith(".tmp")]
        check(not leftovers, "失败条目无半成品与 .tmp 残留", f"leftovers={leftovers[:5]}")

    local = api_json("/api/reference/items?library=costume&page_size=1")["items"]
    if local:
        st, ct, _ = api_request(f"/api/reference/items/costume/{local[0]['id']}/image?kind=image")
        check(st == 200 and ct.startswith("image/"), "断网下本地库图片仍 200", f"status={st} ct={ct}")


def check_phase2_recipes() -> None:
    section("阶段二-4 recipes 放行 C-REF-RECIPES@2")
    cached_ids = _cached_item_ids()
    anime_items = _anime_items(12)
    anime = next((it for it in anime_items if it.get("id") in cached_ids), None)
    portrait_id = api_json("/api/reference/items?library=portrait&page_size=1")["items"][0]["id"]
    pose_items = api_json("/api/reference/items?library=pose&page_size=2")["items"]
    costume_id = api_json("/api/reference/items?library=costume&page_size=1")["items"][0]["id"]
    if anime is None:
        check(False, "存在已缓存 anime 条目可用于 recipes", "none")
        return
    aid = anime["id"]

    body = {
        "portrait_id": portrait_id,
        "costume_id": aid,
        "pose_id": pose_items[0]["id"],
        "costume_library": "costume-anime",
        "dry_run": True,
    }
    st, _, text = api_request("/api/reference/recipes", body)
    check(st == 200, "anime 服装 dry_run 返回 200", f"status={st} body={text[:200]}")
    if st == 200:
        result = json.loads(text)
        nodes = [(n.get("role"), n.get("id")) for n in result.get("nodes", {}).get("inputs", [])]
        check(nodes == [("target", "1"), ("ref1", "2"), ("ref2", "3")],
              "三图节点映射 1/2/3", f"nodes={nodes}")
        check(result.get("dry_run") is True, "dry_run == true", f"dry_run={result.get('dry_run')}")
        check("三图角色合成" in (result.get("workflow_path") or ""),
              "使用三图工作流", f"workflow={result.get('workflow_path')}")
        check("job_id" not in result, "dry_run 响应无 job_id", f"keys={sorted(result)}")
        check(result.get("references", {}).get("costume") == aid,
              "references.costume 为 anime 条目", f"refs={result.get('references')}")
        check("外链素材不能参与" not in text, "不再出现“外链素材不能参与”拒绝", "")
        slot = next((s for s in result.get("slots", []) if s.get("role") == "costume"), {})
        check(slot.get("library") == "costume-anime", "服装槽溯源 library=costume-anime",
              f"slot={slot}")
        check(str(CACHE_ROOT).lower() in (slot.get("path") or "").lower(),
              "服装槽解析到本机缓存文件", f"path={slot.get('path')}")

    # 未知/空 costume_library -> 400
    for bad_value in ("portrait", "", "anime"):
        st, _, text = api_request("/api/reference/recipes",
                                  {**body, "costume_library": bad_value})
        check(st == 400, f"未知 costume_library={bad_value!r} 返回 400",
              f"status={st} body={text[:160]}")
        check("不支持的服装库" in text, f"400 detail 含“不支持的服装库”（{bad_value!r}）",
              f"body={text[:160]}")

    # 缺省 costume_library：行为不变（本地 costume）
    st, _, text = api_request("/api/reference/recipes", {
        "portrait_id": portrait_id,
        "costume_id": costume_id,
        "pose_id": pose_items[0]["id"],
        "dry_run": True,
    })
    check(st == 200, "缺省 costume_library 三图 dry_run 200", f"status={st} body={text[:160]}")
    if st == 200:
        result = json.loads(text)
        nodes = [(n.get("role"), n.get("id")) for n in result.get("nodes", {}).get("inputs", [])]
        check(nodes == [("target", "1"), ("ref1", "2"), ("ref2", "3")],
              "缺省服装库节点映射 1/2/3", f"nodes={nodes}")
        slot = next((s for s in result.get("slots", []) if s.get("role") == "costume"), {})
        check(slot.get("library") == "costume", "缺省服装槽 library=costume", f"slot={slot}")

    # 第 4 张回归：节点 78 + 四图工作流
    if len(pose_items) >= 2:
        st, _, text = api_request("/api/reference/recipes", {
            **body, "extra_library": "pose", "extra_id": pose_items[1]["id"],
        })
        check(st == 200, "anime 服装 + 第 4 张 200", f"status={st} body={text[:160]}")
        if st == 200:
            result = json.loads(text)
            nodes = [(n.get("role"), n.get("id")) for n in result.get("nodes", {}).get("inputs", [])]
            check(nodes == [("target", "1"), ("ref1", "2"), ("ref2", "3"), ("ref3", "78")],
                  "四图节点映射 1/2/3/78", f"nodes={nodes}")
            check("四图参考" in (result.get("workflow_path") or ""),
                  "使用四图工作流", f"workflow={result.get('workflow_path')}")


def check_phase2_cache_location() -> None:
    section("阶段二-5 缓存目录落点与 .gitignore")
    check(CACHE_ROOT.is_dir(), "缓存目录存在于 .cache/reference-remote", str(CACHE_ROOT))
    cache = os.path.normcase(os.path.abspath(CACHE_ROOT))
    app_root = os.path.normcase(os.path.abspath(V4))

    def relation(base: Path) -> str:
        b = os.path.normcase(os.path.abspath(base))
        try:
            if os.path.commonpath([cache, b]) == cache:
                return "cache_contains_base"
            if os.path.commonpath([cache, b]) == b:
                return "base_contains_cache"
        except ValueError:
            pass
        return "disjoint"

    check(relation(V4) == "base_contains_cache", "缓存目录位于 atelier app_root 下",
          f"relation={relation(V4)}")
    for name, base in (("reference_root", V4.parents[1] / "ai-pose-gallery-zh"),
                       ("data", V4 / "data"),
                       ("dist", DIST)):
        check(relation(base) == "disjoint", f"缓存目录与 {name} 无包含关系",
              f"relation={relation(base)}")

    probe = next((p for p in CACHE_ROOT.rglob("*") if p.is_file()), None)
    check(probe is not None, "缓存目录含可检查文件", str(probe))
    if probe is not None:
        rel = probe.relative_to(REPO_ROOT).as_posix()
        proc = subprocess.run(["git", "check-ignore", "-v", rel], cwd=str(REPO_ROOT),
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace")
        check(proc.returncode == 0, "git check-ignore 命中缓存文件",
              f"exit={proc.returncode} out={(proc.stdout or '').strip()}")
    status = subprocess.run(["git", "status", "--ignored", "--short"], cwd=str(REPO_ROOT),
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace")
    ignored = [line for line in (status.stdout or "").splitlines()
               if ".cache/" in line and line.startswith("!!")]
    check(bool(ignored), "git status --ignored 显示 .cache/ 被忽略",
          f"lines={ignored[:3]}")
    dist_cache = [p for p in DIST.rglob("*") if p.is_file() and ".cache" in p.as_posix()]
    check(not dist_cache, "dist 内无缓存文件", f"hits={dist_cache[:3]}")


def check_phase2_pages(browser, shots_dir: Path) -> None:
    section("阶段二-6 页面回归（新 context，前端本阶段仍读 JSON）")
    ctx = browser.new_context(viewport={"width": 1500, "height": 950})
    errors: list[str] = []
    page = new_page(ctx, errors, "phase2-pages")
    for route in LIBRARY_ROUTES:
        status = goto_settle(page, route, ROUTE_ANCHORS.get(route))
        check(status == 200, f"[阶段二] GET {route} 返回 200", f"status={status}")
        wait_images_settled(page)
        stats = image_stats(page)
        name = route.strip("/").replace("/", "_") or "index"
        page.screenshot(path=str(shots_dir / f"phase2_page_{name}.png"))
        check(stats["broken"] == 0, f"[阶段二] {route} 裂图为 0",
              f"broken={stats['broken']} total={stats['total']} src={stats['brokenSrc']}")
    check_gallery_entries(page, "阶段二")
    check(not errors, "[阶段二] 四页 console error / pageerror 为 0", "; ".join(errors[:5]))

    # 预期：本阶段前端仍读 JSON（图片外链 charadb），如实记录而不是硬失败
    try:
        goto_settle(page, "/ref-web/costumes", "服装穿搭库")
        page.get_by_role("button", name="二次元", exact=True).click()
        page.wait_for_timeout(1200)
        wait_images_settled(page)
        srcs = page.evaluate("() => Array.from(document.images).slice(0, 20).map(i => i.currentSrc || i.src)")
        external = [s for s in srcs if "charadb-2fi.pages.dev" in s]
        if external:
            observe("阶段二前端仍读 JSON：二次元服装缩略图仍为外链 charadb URL（阶段三 R3 才切后端）",
                    f"external_imgs={len(external)} sample={external[0][:90]}")
        else:
            observe("阶段二未观察到 charadb 外链缩略图（可能页面/筛选未触发）", f"srcs={srcs[:3]}")
    except Exception as exc:
        observe("二次元筛选探针失败", str(exc))
    page.close()
    ctx.close()

    # 18+ 首次确认（新 context）
    section("阶段二-6b 18+ 首次确认（新 context）")
    ctx2 = browser.new_context(viewport={"width": 1500, "height": 950})
    errs2: list[str] = []
    p2 = new_page(ctx2, errs2, "phase2-nsfw")
    goto_settle(p2, "/ref-web/poses", "动作姿势库")
    check(p2.evaluate("(k) => localStorage.getItem(k)", NSFW_CONFIRMED_KEY) is None,
          "[阶段二] 初始 context 无 18+ 确认记忆键", "")
    p2.locator('header button[title^="当前已开启安全模式"]').first.click()
    try:
        _alertdialog(p2).first.wait_for(state="visible", timeout=8000)
    except Exception:
        pass
    check(_alertdialog(p2).count() == 1, "[阶段二] 首次点击弹出 18+ 确认框",
          f"alertdialog={_alertdialog(p2).count()}")
    p2.screenshot(path=str(shots_dir / "phase2_nsfw_first_dialog.png"))
    try:
        p2.get_by_role("button", name="我已年满 18 周岁").click()
        p2.wait_for_timeout(600)
    except Exception as exc:
        observe("18+ 确认按钮点击失败", str(exc))
    check(p2.evaluate("(k) => localStorage.getItem(k)", NSFW_CONFIRMED_KEY) == "true",
          "[阶段二] 确认后写入记忆键", "")
    p2.close()
    ctx2.close()
    check(not errs2, "[阶段二] 18+ 交互期间无 console error", "; ".join(errs2[:5]))

    # studio 下拉 default
    section("阶段二-6c studio 下拉选中后端 default（新 context）")
    ctx3 = browser.new_context(viewport={"width": 1500, "height": 950})
    errs3: list[str] = []
    p3 = new_page(ctx3, errs3, "phase2-studio")
    catalog = api_json("/api/workflows?scope=studio")
    default_path = catalog.get("default") or ""
    first_path = (catalog.get("workflows") or [{}])[0].get("path")
    goto_settle(p3, "/ref-web/studio", "AI 角色合成台")
    try:
        p3.wait_for_function(
            """() => {
                try {
                    const cfg = JSON.parse(localStorage.getItem('pose_atlas_api_config_v3') || '{}')
                    return Boolean(cfg?.comfyuiParams?.workflowPreset)
                } catch { return false }
            }""",
            timeout=45000,
        )
    except Exception:
        pass
    stored = p3.evaluate(
        """() => {
            try {
                const cfg = JSON.parse(localStorage.getItem('pose_atlas_api_config_v3') || '{}')
                return cfg?.comfyuiParams?.workflowPreset || ''
            } catch { return '' }
        }"""
    )
    check(bool(default_path) and stored == default_path,
          "[阶段二] studio 工作流选中值 == 后端 default", f"stored={stored} default={default_path}")
    check(bool(first_path) and stored != first_path,
          "[阶段二] 选中值不是列表第一项", f"first={first_path}")
    p3.screenshot(path=str(shots_dir / "phase2_studio_dropdown.png"))
    p3.close()
    ctx3.close()
    check(not errs3, "[阶段二] studio 无 console error", "; ".join(errs3[:5]))


# ---------------------------------------------------------------------------
# 阶段三（T10）追加检查：图库数据层切后端（R3.1 ~ R3.3）
#
# 与阶段一/二的区别：三个图库查询已改为 GET /api/reference/items 并行分页，
# 图片全部走后端端点。本段检查：
#   - dist 无旧 /data/*.json 与外链残留（阶段三起为硬失败）；
#   - 六路由 200、console 0、无外部域名请求；
#   - 四库页正常网络裂图 0、图片全部来自后端端点；深度图端点可用；
#   - 断网（Playwright 阻断非 127.0.0.1）重载裂图 0、无外部请求、
#     请求的 costume-anime 条目必须在已缓存集合内；
#   - 返回入口 3 个、18+ 首次确认只弹一次、药丸由 nsfw 聚合；
#   - 姿势搜索/体系切换/加载更多、服装分类/标签/加载更多、人像分区/发长；
#   - studio 下拉仍选中后端 default。
# ---------------------------------------------------------------------------
PHASE3_CACHE_LIB = "costume-anime"

#: 药丸文本：`名称 (数量)` 或 `名称 (数量) · 18+`；排除「解锁 18+ ...」按钮。
_P3_PILL_JS = r"""() => Array.from(document.querySelectorAll('button'))
    .map((b) => (b.textContent || '').trim())
    .filter((t) => !t.startsWith('解锁') && /^[^(]+ \(\d+\)( · 18\+)?$/.test(t))"""

#: 卡片文本：以「加入配方」按钮定位卡片容器，读取整卡可见文本。
_P3_CARD_TEXT_JS = r"""() => Array.from(document.querySelectorAll('button'))
    .filter((b) => (b.textContent || '').trim() === '加入配方')
    .map((b) => {
        const card = b.closest('div.group');
        const box = card || (b.parentElement && b.parentElement.parentElement);
        return ((box ? box.innerText : '') || '').replace(/\s+/g, ' ').trim();
    })"""

#: 图片统计：裂图、未完成、以及图片 URL 来源分类。
_P3_IMAGE_JS = r"""() => {
    const classify = (s) => {
        if (!s) return 'empty';
        if (s.startsWith('data:')) return 'data';
        let u;
        try { u = new URL(s, location.href); } catch { return 'bad'; }
        if (u.hostname !== location.hostname) return 'external';
        if (/^\/(thumbs|img)\//.test(u.pathname)) return 'legacy';
        if (u.pathname.startsWith('/api/reference/items/')) return 'backend';
        return 'other';
    };
    const entries = Array.from(document.images).map((i) => {
        const src = i.currentSrc || i.src;
        return { src, kind: classify(src), complete: i.complete, width: i.naturalWidth };
    });
    const broken = entries.filter((e) => e.complete && e.width === 0);
    const pending = entries.filter((e) => !e.complete);
    const bad = entries.filter((e) => ['external', 'legacy', 'other', 'bad', 'empty'].includes(e.kind));
    return {
        total: entries.length,
        broken: broken.length,
        pending: pending.length,
        bad: bad.length,
        backend: entries.filter((e) => e.kind === 'backend').length,
        brokenSrc: broken.slice(0, 10).map((e) => e.src),
        badSrc: bad.slice(0, 10).map((e) => e.kind + ':' + e.src),
        srcs: entries.slice(0, 10).map((e) => e.src),
    };
}"""


def _p3_is_external(url: str) -> bool:
    """非 127.0.0.1 / localhost 的 http(s) 请求视为外部请求。"""
    parsed = urlsplit(url)
    return parsed.scheme in ("http", "https") and parsed.hostname not in ("127.0.0.1", "localhost")


def _p3_new_context(browser, *, unlocked: bool = False):
    """阶段三专用新 context；unlocked=True 时预先关闭安全模式并写确认标记。"""
    ctx = browser.new_context(viewport={"width": 1500, "height": 950})
    if unlocked:
        ctx.add_init_script(
            "try { localStorage.setItem('pose_atlas_safe_mode_v1', 'false');"
            " localStorage.setItem('pose_atlas_nsfw_confirmed_v1', 'true'); } catch (e) {}"
        )
    return ctx


def _p3_cached_kinds() -> dict[str, set[str]]:
    """读取本机缓存：条目 id -> 已存在的 kind 集合（thumb/image）。"""
    result: dict[str, set[str]] = {}
    root = CACHE_ROOT / PHASE3_CACHE_LIB
    if not root.is_dir():
        return result
    for item_dir in root.iterdir():
        if not item_dir.is_dir():
            continue
        kinds: set[str] = set()
        for path in item_dir.iterdir():
            try:
                if path.is_file() and path.stat().st_size > 0:
                    kinds.add(path.stem)
            except OSError:
                pass
        if kinds:
            result[item_dir.name] = kinds
    return result


def _p3_cached_coverage() -> dict[str, set[str]]:
    """thumb 与 image 均已缓存的条目（断网可稳定出图的集合）。"""
    return {item_id: kinds for item_id, kinds in _p3_cached_kinds().items()
            if {"thumb", "image"} <= kinds}


def _p3_scroll_all(page) -> None:
    """分步滚到底，确保懒加载图片真正进入视口后再统计。"""
    try:
        page.evaluate(
            """async () => {
                const step = Math.max(600, Math.floor(window.innerHeight * 0.8));
                for (let y = 0; y <= document.body.scrollHeight; y += step) {
                    window.scrollTo(0, y);
                    await new Promise((r) => setTimeout(r, 120));
                }
                window.scrollTo(0, document.body.scrollHeight);
            }"""
        )
    except Exception:
        pass
    wait_images_settled(page)


def _p3_image_stats(page) -> dict:
    return page.evaluate(_P3_IMAGE_JS)


def _p3_card_count(page) -> int:
    return page.get_by_role("button", name="加入配方", exact=True).count()


def _p3_card_texts(page) -> list[str]:
    return page.evaluate(_P3_CARD_TEXT_JS)


def _p3_remaining_count(page) -> int | None:
    """读取「加载更多（剩余 N 套/张/组）」中的 N；按钮不存在时返回 None。"""
    try:
        text = page.get_by_role("button", name=re.compile("^加载更多")).first.inner_text()
    except Exception:
        return None
    match = re.search(r"剩余\s*(\d+)", text)
    return int(match.group(1)) if match else None


def _p3_pill_texts(page) -> list[str]:
    return page.evaluate(_P3_PILL_JS)


def _p3_anime_ids(srcs: list[str]) -> set[str]:
    import urllib.parse

    ids: set[str] = set()
    for src in srcs:
        match = re.search(r"/api/reference/items/costume-anime/([^/]+)/image", src or "")
        if match:
            ids.add(urllib.parse.unquote(match.group(1)))
    return ids


def check_phase3_dist() -> None:
    section("阶段三-0 构建产物：无旧数据路径与外链残留（R3 / C-BUILD-ARTIFACT@1）")
    index_path = DIST / "index.html"
    if not check(index_path.exists(), "[阶段三] dist/index.html 存在", str(index_path)):
        return

    html = index_path.read_text(encoding="utf-8")
    refs = [r for r in _META_RE.findall(html) if not r.startswith("data:")]
    check(bool(refs), "[阶段三] dist/index.html 含资源引用", f"{len(refs)} 条")
    bad_refs = [r for r in refs if not r.startswith("/ref-web/assets/")]
    check(not bad_refs, "[阶段三] dist/index.html 只引用 /ref-web/assets/", f"异常引用={bad_refs}")

    dist_files = [p for p in DIST.rglob("*") if p.is_file()]
    src_files = [p for p in (GALLERY / "src").rglob("*") if p.is_file()]
    check(bool(dist_files), "[阶段三] dist 产物非空", f"{len(dist_files)} 个文件")
    if dist_files and src_files:
        oldest_dist = min(p.stat().st_mtime for p in dist_files)
        newest_src = max(p.stat().st_mtime for p in src_files)
        check(oldest_dist > newest_src,
              "[阶段三] dist 全部产物 mtime 晚于最新源码",
              f"dist_min={time.strftime('%H:%M:%S', time.localtime(oldest_dist))} "
              f"src_max={time.strftime('%H:%M:%S', time.localtime(newest_src))}")

    literals = LEGACY_DATA_LITERALS + ["charadb-2fi.pages.dev", "qwen2509_2img"]
    hits: dict[str, list[str]] = {lit: [] for lit in literals}
    for path in dist_files:
        if path.suffix in {".woff2", ".png", ".jpg", ".webp"}:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for lit in literals:
            if lit in content:
                hits[lit].append(path.relative_to(DIST).as_posix())

    for lit in LEGACY_DATA_LITERALS:
        check(not hits[lit], f"[阶段三] dist 无旧数据路径 {lit}", f"命中={hits[lit]}")
    check(not hits["charadb-2fi.pages.dev"],
          "[阶段三] dist 无 charadb 外链残留", f"命中={hits['charadb-2fi.pages.dev']}")
    check(not hits["qwen2509_2img"],
          "[阶段三] dist 无旧模板字面量 qwen2509_2img", f"命中={hits['qwen2509_2img']}")


def check_phase3_routes(browser, shots_dir: Path) -> None:
    section("阶段三-1 六路由 200、console 0、无外部请求（新 context）")
    ctx = _p3_new_context(browser)
    errors: list[str] = []
    external: list[str] = []
    page = new_page(ctx, errors, "p3-routes")
    page.on("request", lambda req: external.append(req.url) if _p3_is_external(req.url) else None)

    for route in ROUTES:
        status = goto_settle(page, route, ROUTE_ANCHORS.get(route))
        check(status == 200, f"[阶段三] GET {route} 返回 200", f"status={status} url={page.url}")
        slug = route.strip("/").replace("/", "_") or "index"
        page.screenshot(path=str(shots_dir / f"phase3_route_{slug}.png"))

    check(not errors, "[阶段三] 六路由 console error / pageerror 为 0", "; ".join(errors[:6]))
    check(not external, "[阶段三] 六路由未请求任何外部域名", f"外部请求={external[:5]}")
    page.close()
    ctx.close()


def check_phase3_normal_images(browser, shots_dir: Path) -> None:
    section("阶段三-2 四库页正常网络裂图 0 与图片端点")
    ctx = _p3_new_context(browser)
    errors: list[str] = []
    page = new_page(ctx, errors, "p3-normal")
    for route in LIBRARY_ROUTES:
        goto_settle(page, route, ROUTE_ANCHORS.get(route))
        _p3_scroll_all(page)
        stats = _p3_image_stats(page)
        slug = route.strip("/").replace("/", "_") or "index"
        page.screenshot(path=str(shots_dir / f"phase3_normal_{slug}.png"))
        check(stats["total"] > 0, f"[阶段三] {route} 有图片渲染", f"imgs={stats['total']}")
        check(stats["broken"] == 0, f"[阶段三] {route} 正常网络裂图为 0",
              f"broken={stats['broken']}/{stats['total']} src={stats['brokenSrc']}")
        check(stats["pending"] == 0, f"[阶段三] {route} 无未完成加载的图片",
              f"pending={stats['pending']}")
        check(stats["bad"] == 0, f"[阶段三] {route} 图片全部走后端端点（无外链/旧静态路径）",
              f"bad={stats['bad']} src={stats['badSrc']}")

    # 对抗性探针 1：姿势深度图模式必须走 depth_thumb 后端端点且不裂图。
    goto_settle(page, "/ref-web/poses", "动作姿势库")
    try:
        page.get_by_role("button", name="深度图 (Depth)", exact=True).click()
        _p3_scroll_all(page)
    except Exception as exc:
        check(False, "[阶段三] 姿势深度图模式切换", f"{type(exc).__name__}: {exc}")
    depth_stats = _p3_image_stats(page)
    depth_srcs = page.evaluate(
        "() => Array.from(document.images).map((i) => i.currentSrc || i.src)"
        ".filter((s) => s.includes('kind=depth_thumb') || s.includes('kind=depth'))"
    )
    page.screenshot(path=str(shots_dir / "phase3_pose_depth_mode.png"))
    check(depth_stats["broken"] == 0, "[阶段三] 深度图模式裂图为 0",
          f"broken={depth_stats['broken']} src={depth_stats['brokenSrc']}")
    check(len(depth_srcs) > 0, "[阶段三] 深度图模式确实使用后端 depth 端点",
          f"depth_srcs={len(depth_srcs)} sample={depth_srcs[:2]}")
    try:
        page.get_by_role("button", name="素体白模", exact=True).click()
        page.wait_for_timeout(400)
    except Exception:
        pass

    # 对抗性探针 2：二次元服装缩略图必须走后端端点（无 charadb 外链）且不裂图。
    goto_settle(page, "/ref-web/costumes", "服装穿搭库")
    try:
        page.get_by_role("button", name="二次元", exact=True).click()
        _p3_scroll_all(page)
    except Exception as exc:
        check(False, "[阶段三] 服装二次元分类切换", f"{type(exc).__name__}: {exc}")
    anime_stats = _p3_image_stats(page)
    page.screenshot(path=str(shots_dir / "phase3_costume_anime.png"))
    check(anime_stats["broken"] == 0, "[阶段三] 二次元服装裂图为 0",
          f"broken={anime_stats['broken']}/{anime_stats['total']} src={anime_stats['brokenSrc']}")
    check(anime_stats["bad"] == 0, "[阶段三] 二次元服装图片全部走后端端点",
          f"bad={anime_stats['bad']} src={anime_stats['badSrc']}")

    check(not errors, "[阶段三] 正常网络图片检查无 console error", "; ".join(errors[:6]))
    page.close()
    ctx.close()


def check_phase3_offline(browser, shots_dir: Path) -> None:
    section("阶段三-3 断网（阻断非 127.0.0.1）四页与已缓存集合")
    coverage = _p3_cached_coverage()
    observe("阶段三断网对照的已缓存集合",
            f"thumb+image 均缓存 {len(coverage)}/440 套")

    ctx = browser.new_context(viewport={"width": 1500, "height": 950})
    blocked: list[str] = []
    external_502: list[str] = []
    anime_requests: list[str] = []

    def handler(route):
        if _p3_is_external(route.request.url):
            blocked.append(route.request.url)
            route.abort()
        else:
            route.continue_()

    ctx.route("**/*", handler)
    errors: list[str] = []
    page = new_page(ctx, errors, "p3-offline")

    def on_request(req):
        if "/api/reference/items/costume-anime/" in req.url:
            anime_requests.append(req.url)

    def on_response(resp):
        if resp.status == 502:
            external_502.append(resp.url)

    page.on("request", on_request)
    page.on("response", on_response)

    broken_total = 0
    for route in LIBRARY_ROUTES:
        goto_settle(page, route, ROUTE_ANCHORS.get(route))
        _p3_scroll_all(page)
        stats = _p3_image_stats(page)
        broken_total += stats["broken"]
        slug = route.strip("/").replace("/", "_") or "index"
        page.screenshot(path=str(shots_dir / f"phase3_offline_{slug}.png"))
        check(stats["broken"] == 0,
              f"[阶段三] {route} 断网重载裂图为 0（已缓存集合）",
              f"broken={stats['broken']}/{stats['total']} pending={stats['pending']} "
              f"src={stats['brokenSrc']}")

    # 外链服装库：切到二次元后所有缩略图都应来自后端缓存端点。
    goto_settle(page, "/ref-web/costumes", "服装穿搭库")
    try:
        page.get_by_role("button", name="二次元", exact=True).click()
        _p3_scroll_all(page)
    except Exception as exc:
        check(False, "[阶段三] 断网下二次元分类切换", f"{type(exc).__name__}: {exc}")
    anime_stats = _p3_image_stats(page)
    broken_total += anime_stats["broken"]
    page.screenshot(path=str(shots_dir / "phase3_offline_costume_anime.png"))
    check(anime_stats["broken"] == 0,
          "[阶段三] 断网下二次元服装裂图为 0（已缓存集合）",
          f"broken={anime_stats['broken']}/{anime_stats['total']} src={anime_stats['brokenSrc']}")

    check(not blocked, "[阶段三] 断网重载未发起任何外部域名请求",
          f"被阻断的外部请求={blocked[:5]}")
    anime_ids = _p3_anime_ids(anime_requests)
    uncached_requested = sorted(item_id for item_id in anime_ids if item_id not in coverage)
    check(not uncached_requested,
          "[阶段三] 断网页面只请求已缓存 anime 条目",
          f"请求条目={len(anime_ids)} 未缓存={uncached_requested[:8]}")

    if broken_total or external_502:
        observe("断网裂图/502 明细（如实降级，不修改口径）",
                f"broken_total={broken_total} 502={external_502[:5]}")
    else:
        observe("断网四页与二次元集合裂图均为 0，且未发起外部请求", "无降级")

    check(not errors, "[阶段三] 断网检查期间 console error 记录（用于区分中止请求）",
          f"console_rows={len(errors)}")
    page.close()
    ctx.close()


def check_phase3_entries(browser, shots_dir: Path) -> None:
    section("阶段三-4 返回入口 3 个（新 context）")
    ctx = _p3_new_context(browser)
    try:
        check_gallery_entries_all(ctx, shots_dir)
    finally:
        ctx.close()


def check_phase3_nsfw(browser, shots_dir: Path) -> None:
    section("阶段三-5 18+ 判定来自 DTO.nsfw（新 context）")
    ctx = _p3_new_context(browser)
    errors: list[str] = []
    page = new_page(ctx, errors, "p3-nsfw")
    goto_settle(page, "/ref-web/poses", "动作姿势库")

    nsfw_pose = api_json("/api/reference/items?library=pose&nsfw=true&page_size=200")
    nsfw_total = int(nsfw_pose.get("total") or 0)
    check(nsfw_total > 0, "[阶段三] 后端总闸开启且 pose 存在 nsfw 条目",
          f"total={nsfw_total}")
    first_pose = (nsfw_pose.get("items") or [{}])[0]
    nsfw_system = first_pose.get("group") or ""
    nsfw_pose_id = first_pose.get("id") or ""
    check(bool(nsfw_system) and bool(nsfw_pose_id),
          "[阶段三] 取得 nsfw 姿势探针（体系 + id）",
          f"system={nsfw_system} id={nsfw_pose_id}")

    safe_key = page.evaluate("(k) => localStorage.getItem(k)", "pose_atlas_safe_mode_v1")
    # 页面挂载时会把当前状态写回 localStorage；默认状态是安全模式，
    # 因此允许键为 null（尚未写入）或 "true"，只拒绝显式的 "false"。
    check(safe_key != "false", "[阶段三] 安全模式默认开启（无记忆键或 true）", f"value={safe_key}")

    unlock_button = page.get_by_role("button", name=re.compile(r"^解锁 18\+ 敏感姿势体系"))
    check(unlock_button.count() == 1, "[阶段三] 安全模式显示 18+ 解锁入口",
          f"count={unlock_button.count()}")
    pills_safe = _p3_pill_texts(page)
    check(bool(nsfw_system) and not any(p.startswith(nsfw_system) for p in pills_safe),
          "[阶段三] 安全模式下 18+ 体系药丸隐藏",
          f"pills={pills_safe}")

    search_input = page.locator('input[placeholder*="搜索姿势名称"]')
    if nsfw_pose_id:
        search_input.fill(nsfw_pose_id)
        page.wait_for_timeout(500)
        hidden_empty = page.get_by_text("没有找到匹配的姿势", exact=False).count()
        check(hidden_empty > 0, "[阶段三] 安全模式下搜索 18+ 条目为空（条目已隐藏）",
              f"empty_state={hidden_empty} id={nsfw_pose_id}")
        search_input.fill("")
        page.wait_for_timeout(300)

    page.locator('header button[title^="当前已开启安全模式"]').first.click()
    try:
        _alertdialog(page).first.wait_for(state="visible", timeout=8000)
    except Exception:
        pass
    check(_alertdialog(page).count() == 1, "[阶段三] 首次解锁弹出年龄确认框",
          f"alertdialog={_alertdialog(page).count()}")
    page.screenshot(path=str(shots_dir / "phase3_nsfw_first_dialog.png"))
    try:
        page.get_by_role("button", name=re.compile("我已年满")).first.click()
        page.wait_for_timeout(700)
    except Exception as exc:
        check(False, "[阶段三] 点击年龄确认按钮", f"{type(exc).__name__}: {exc}")
    check(page.evaluate("(k) => localStorage.getItem(k)", NSFW_CONFIRMED_KEY) == "true",
          "[阶段三] 确认后写入 18+ 记忆键", "")

    pills_unlocked = _p3_pill_texts(page)
    check(bool(nsfw_system) and any(p.startswith(nsfw_system) and "18+" in p for p in pills_unlocked),
          "[阶段三] 解锁后至少一个体系药丸显示 18+",
          f"pills={pills_unlocked}")

    if nsfw_pose_id:
        search_input.fill(nsfw_pose_id)
        page.wait_for_timeout(500)
        visible_cards = _p3_card_count(page)
        check(visible_cards > 0, "[阶段三] 解锁后搜索同一 18+ 条目可显示",
              f"cards={visible_cards} id={nsfw_pose_id}")
        search_input.fill("")
        page.wait_for_timeout(300)

    # 第二次解锁：切回安全模式再解锁，不得再次弹窗。
    page.locator('header button[title^="当前已显示 18+"]').first.click()
    page.wait_for_timeout(500)
    check(page.evaluate("(k) => localStorage.getItem(k)", "pose_atlas_safe_mode_v1") == "true",
          "[阶段三] 可切回安全模式", "")
    page.locator('header button[title^="当前已开启安全模式"]').first.click()
    page.wait_for_timeout(1200)
    check(_alertdialog(page).count() == 0, "[阶段三] 第二次解锁不再弹年龄确认框",
          f"alertdialog={_alertdialog(page).count()}")
    check(page.evaluate("(k) => localStorage.getItem(k)", "pose_atlas_safe_mode_v1") == "false",
          "[阶段三] 第二次解锁直接进入完整模式", "")

    # 服装页：18+ 分类药丸由 nsfw 聚合，安全模式下隐藏。
    nsfw_costume = api_json("/api/reference/items?library=costume&nsfw=true&page_size=200")
    first_costume = (nsfw_costume.get("items") or [{}])[0]
    nsfw_category = first_costume.get("group") or ""
    goto_settle(page, "/ref-web/costumes", "服装穿搭库")
    costume_pills = _p3_pill_texts(page)
    check(bool(nsfw_category) and any(p.startswith(nsfw_category) and "18+" in p
                                      for p in costume_pills),
          "[阶段三] 解锁后至少一个服装分类药丸显示 18+",
          f"category={nsfw_category} pills={costume_pills}")

    page.locator('header button[title^="当前已显示 18+"]').first.click()
    page.wait_for_timeout(500)
    costume_pills_safe = _p3_pill_texts(page)
    check(bool(nsfw_category) and not any(p.startswith(nsfw_category)
                                          for p in costume_pills_safe),
          "[阶段三] 安全模式下 18+ 服装分类药丸隐藏",
          f"category={nsfw_category} pills={costume_pills_safe}")
    page.screenshot(path=str(shots_dir / "phase3_nsfw_costume_pills.png"))

    check(not errors, "[阶段三] 18+ 检查期间无 console error", "; ".join(errors[:6]))
    page.close()
    ctx.close()


def check_phase3_pose_interactions(browser, shots_dir: Path) -> None:
    section("阶段三-6a 姿势页搜索 / 体系切换 / 加载更多")
    ctx = _p3_new_context(browser, unlocked=True)
    errors: list[str] = []
    page = new_page(ctx, errors, "p3-poses")
    goto_settle(page, "/ref-web/poses", "动作姿势库")

    baseline = _p3_card_count(page)
    check(baseline == 60, "[阶段三] 姿势页默认渲染 60 组", f"cards={baseline}")

    search_input = page.locator('input[placeholder*="搜索姿势名称"]')
    search_input.fill("P001")
    page.wait_for_timeout(600)
    filtered = _p3_card_count(page)
    card_texts = _p3_card_texts(page)
    check(filtered > 0, "[阶段三] 姿势搜索 P001 有结果", f"cards={filtered}")
    check(filtered < baseline, "[阶段三] 姿势搜索 P001 确实缩小结果集",
          f"filtered={filtered} baseline={baseline}")
    check(any("P001" in text for text in card_texts),
          "[阶段三] 搜索结果卡片文本包含 P001",
          f"sample={card_texts[:2]}")
    page.screenshot(path=str(shots_dir / "phase3_poses_search_p001.png"))
    search_input.fill("")
    page.wait_for_timeout(300)
    page.get_by_role("button", name="重置", exact=True).click()
    page.wait_for_timeout(400)

    pills = _p3_pill_texts(page)
    target = next((p for p in pills if not p.startswith("全部")), "")
    check(bool(target), "[阶段三] 姿势页存在体系药丸", f"pills={pills}")
    system = target.split(" (")[0] if target else ""
    if system:
        page.get_by_role("button", name=re.compile("^" + re.escape(system) + r" \(")).first.click()
        page.wait_for_timeout(700)
        system_texts = _p3_card_texts(page)
        check(bool(system_texts) and all(system in text for text in system_texts),
              "[阶段三] 体系切换后所有卡片属于该体系",
              f"system={system} cards={len(system_texts)} sample={system_texts[:2]}")

    # 回到全部体系后验证 60 -> 120。
    page.get_by_role("button", name=re.compile(r"^全部 \(\d+\)$")).first.click()
    page.wait_for_timeout(600)
    before_load = _p3_card_count(page)
    check(before_load == 60, "[阶段三] 返回全部体系后仍为 60 组", f"cards={before_load}")
    page.get_by_role("button", name=re.compile("^加载更多")).first.click()
    page.wait_for_timeout(800)
    after_load = _p3_card_count(page)
    check(after_load == 120, "[阶段三] 姿势页加载更多 60 → 120", f"cards={after_load}")
    page.screenshot(path=str(shots_dir / "phase3_poses_load_more.png"))
    check(not errors, "[阶段三] 姿势页交互期间无 console error", "; ".join(errors[:6]))
    page.close()
    ctx.close()


def check_phase3_costume_interactions(browser, shots_dir: Path) -> None:
    section("阶段三-6b 服装页分类 / 标签筛选与加载更多")
    ctx = _p3_new_context(browser, unlocked=True)
    errors: list[str] = []
    page = new_page(ctx, errors, "p3-costumes")
    goto_settle(page, "/ref-web/costumes", "服装穿搭库")

    baseline = _p3_card_count(page)
    check(baseline == 60, "[阶段三] 服装页默认渲染 60 套", f"cards={baseline}")

    pills = _p3_pill_texts(page)
    target = next((p for p in pills if not p.startswith("全部穿搭")), "")
    category = target.split(" (")[0] if target else ""
    check(bool(category), "[阶段三] 服装页存在分类药丸", f"pills={pills}")
    if category:
        page.get_by_role("button", name=re.compile("^" + re.escape(category) + r" \(")).first.click()
        page.wait_for_timeout(700)
        category_texts = _p3_card_texts(page)
        check(bool(category_texts) and all(category in text for text in category_texts),
              "[阶段三] 服装分类筛选后所有卡片属于该分类",
              f"category={category} cards={len(category_texts)} sample={category_texts[:2]}")

    # 标签筛选：优先选「针织」，不可用时取第一个非「全部」选项。
    # 记录分类筛选后的「剩余 N 套」，标签生效后应看到剩余量下降。
    baseline_remaining = _p3_remaining_count(page)
    page.locator('button[role="combobox"]').first.click()
    page.wait_for_timeout(300)
    chose_tag = ""
    try:
        option = page.get_by_role("option", name="针织", exact=True)
        if option.count() > 0:
            option.first.click()
            chose_tag = "针织"
        else:
            options = page.get_by_role("option")
            count = options.count()
            for index in range(1, count):
                text = options.nth(index).inner_text().strip()
                if text and "全部" not in text:
                    options.nth(index).click()
                    chose_tag = text
                    break
    except Exception as exc:
        observe("服装标签选择失败", f"{type(exc).__name__}: {exc}")
    page.wait_for_timeout(700)
    tag_cards = _p3_card_count(page)
    check(bool(chose_tag), "[阶段三] 服装页可选择标签", f"tag={chose_tag}")
    check(tag_cards > 0, "[阶段三] 标签筛选后仍有结果",
          f"tag={chose_tag} cards={tag_cards}")
    check(tag_cards <= baseline, "[阶段三] 标签筛选结果不超过默认集合",
          f"tag_cards={tag_cards} baseline={baseline}")
    tag_remaining = _p3_remaining_count(page)
    tag_narrowed = (
        tag_remaining is None
        or baseline_remaining is None
        or tag_remaining < baseline_remaining
    )
    check(tag_narrowed, "[阶段三] 标签筛选确实缩小结果集",
          f"remaining_before={baseline_remaining} remaining_after={tag_remaining}")
    page.screenshot(path=str(shots_dir / "phase3_costumes_tag_filter.png"))

    # 二次元分类：卡片来源显示 CharaDB（后端端点），验证分类切换。
    page.get_by_role("button", name="重置", exact=True).click()
    page.wait_for_timeout(400)
    page.get_by_role("button", name="二次元", exact=True).click()
    page.wait_for_timeout(800)
    anime_texts = _p3_card_texts(page)
    check(bool(anime_texts) and all("CharaDB" in text for text in anime_texts),
          "[阶段三] 二次元分类下所有卡片来源为 CharaDB",
          f"cards={len(anime_texts)} sample={anime_texts[:2]}")
    page.get_by_role("button", name="全部", exact=True).click()
    page.wait_for_timeout(600)

    before_load = _p3_card_count(page)
    check(before_load == 60, "[阶段三] 服装页返回全部分类后为 60 套", f"cards={before_load}")
    page.get_by_role("button", name=re.compile("^加载更多")).first.click()
    page.wait_for_timeout(800)
    after_load = _p3_card_count(page)
    check(after_load == 120, "[阶段三] 服装页加载更多 60 → 120", f"cards={after_load}")
    page.screenshot(path=str(shots_dir / "phase3_costumes_load_more.png"))
    check(not errors, "[阶段三] 服装页交互期间无 console error", "; ".join(errors[:6]))
    page.close()
    ctx.close()


def check_phase3_portrait_interactions(browser, shots_dir: Path) -> None:
    section("阶段三-6c 人像页分区 / 发长筛选")
    ctx = _p3_new_context(browser, unlocked=True)
    errors: list[str] = []
    page = new_page(ctx, errors, "p3-portraits")
    goto_settle(page, "/ref-web/portraits", "人像颜值库")

    baseline = _p3_card_count(page)
    check(baseline == 60, "[阶段三] 人像页默认渲染 60 张", f"cards={baseline}")

    page.get_by_role("button", name=re.compile(r"^正脸参考 \(\d+\)$")).first.click()
    page.wait_for_timeout(700)
    section_texts = _p3_card_texts(page)
    check(bool(section_texts) and all("正脸参考" in text for text in section_texts),
          "[阶段三] 人像分区筛选后所有卡片属于该分区",
          f"cards={len(section_texts)} sample={section_texts[:2]}")

    page.get_by_role("button", name=re.compile(r"^短发 \(\d+\)$")).first.click()
    page.wait_for_timeout(700)
    hair_texts = _p3_card_texts(page)
    check(bool(hair_texts) and all("短发" in text for text in hair_texts),
          "[阶段三] 人像发长筛选后所有卡片属于该发长",
          f"cards={len(hair_texts)} sample={hair_texts[:2]}")
    check(len(hair_texts) > 0, "[阶段三] 分区+发长组合筛选仍有结果",
          f"cards={len(hair_texts)}")
    page.screenshot(path=str(shots_dir / "phase3_portraits_filters.png"))
    check(not errors, "[阶段三] 人像页交互期间无 console error", "; ".join(errors[:6]))
    page.close()
    ctx.close()


def check_phase3_studio_default(browser, shots_dir: Path) -> None:
    section("阶段三-6d studio 下拉仍选中后端 default（回归）")
    ctx = _p3_new_context(browser)
    try:
        check_studio_workflow_default(ctx, shots_dir)
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("SKIP: 未安装 playwright，无法执行阶段一浏览器验收")
        return 1

    shots_dir = Path(tempfile.mkdtemp(prefix="t3_phase1_shots_"))
    print(f"截图与下载目录：{shots_dir}")

    section("环境前置（8656 只读探活，不 kill/重启）")
    live_before = http_get_status(f"http://127.0.0.1:{LIVE_PORT}/")
    check(live_before == 200, "运行中实例 8656 GET 探活 200（未操作）", f"status={live_before}")

    proc = None

    try:
        proc = start_instance_if_needed()
        check(port_serving(PORT), f"临时实例 {BASE} 就绪", "")

        check_static()
        check_dist_artifact()
        check_phase3_dist()

        # 阶段二：断网等价探针需要重启临时实例（只有脚本自己拉起的实例才可重启）
        if proc is not None:
            stop_instance(proc)
            proc = None
            offline_proc = None
            try:
                offline_proc = start_instance_if_needed(
                    OFFLINE_ENV, "t3_phase2_offline_server.log")
                check_phase2_offline()
            except Exception as exc:
                check(False, "断网等价探针执行失败",
                      f"{type(exc).__name__}: {exc}")
            finally:
                stop_instance(offline_proc)
            proc = start_instance_if_needed()
            check(port_serving(PORT), "断网探针后恢复正常临时实例", "")
        else:
            observe("8766 由外部启动，脚本不能重启为断网实例；跳过服务端 502 探针",
                    "已缓存 200 仍由后续检查覆盖")

        section("阶段二 HTTP 契约检查（C-REMOTE-CACHE@1 / C-REF-ITEM-DTO@2 / C-REF-RECIPES@2）")
        check_phase2_dto()
        check_phase2_image_cache()
        check_phase2_recipes()
        check_phase2_cache_location()

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            ctx_main = browser.new_context(viewport={"width": 1500, "height": 950})
            check_routes(ctx_main, shots_dir)
            check_gallery_entries_all(ctx_main, shots_dir)
            check_library_images(ctx_main, shots_dir)
            check_studio_workflow_default(ctx_main, shots_dir)
            check_history_section(ctx_main, shots_dir)
            ctx_main.close()

            check_nsfw_age_gate(browser, shots_dir)
            check_library_images_offline(browser, shots_dir)
            check_settings_export(browser, shots_dir)
            check_history_empty_mock(browser, shots_dir)
            check_phase2_pages(browser, shots_dir)

            # 阶段三（T10）追加验收：独立新 context，逐项检查图库数据层。
            check_phase3_routes(browser, shots_dir)
            check_phase3_normal_images(browser, shots_dir)
            check_phase3_offline(browser, shots_dir)
            check_phase3_entries(browser, shots_dir)
            check_phase3_nsfw(browser, shots_dir)
            check_phase3_pose_interactions(browser, shots_dir)
            check_phase3_costume_interactions(browser, shots_dir)
            check_phase3_portrait_interactions(browser, shots_dir)
            check_phase3_studio_default(browser, shots_dir)

            browser.close()

        live_after = http_get_status(f"http://127.0.0.1:{LIVE_PORT}/")
        check(live_after == 200, "验收结束后 8656 仍可用（未被影响）", f"status={live_after}")
    except Exception as exc:
        check(False, "验收流程异常终止", f"{type(exc).__name__}: {exc}")
    finally:
        stop_instance(proc)

    failed = [r for r in _results if not r[0]]
    print("\n" + "=" * 60)
    print(f"硬检查：{len(_results) - len(failed)} 通过 / {len(failed)} 失败；观察项 {len(_observations)} 条")
    for ok, name, detail in _results:
        if not ok:
            print(f"  FAIL: {name} | {detail}")
    print(f"RESULT: {'PASS' if not failed else 'FAIL'}")
    print(f"截图目录：{shots_dir}")

    report = {
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "base": BASE,
        "checks": [{"ok": ok, "name": name, "detail": detail} for ok, name, detail in _results],
        "observations": [{"name": n, "detail": d} for n, d in _observations],
        "screenshotsDir": str(shots_dir),
        "passed": len(_results) - len(failed),
        "failed": len(failed),
        "verdict": "PASS" if not failed else "FAIL",
    }
    report_path = shots_dir / "run_reference_phase3_result.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"结果 JSON：{report_path}")

    exit_code = 0 if not failed else 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())