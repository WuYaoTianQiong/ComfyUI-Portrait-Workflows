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

阶段四（T13）追加检查（`C-REF-RECIPES@2` / `C-JOB-PROGRESS@1` / `C-BUILD-ARTIFACT@1`）：

   1. 后端 TestClient：三图 dry_run 节点 1/2/3 + 三图工作流；第 4 张节点 78 +
      四图工作流；`costume_library=costume-anime` + 已缓存条目成功；未知库 400；
      另加缺 `extra_library`、未知画风、未知条目三项对抗探针。
   2. Playwright 全新 context，8766：从人像/服装/姿势三个图库各选一条
      （服装选二次元 CharaDB 条目），点击生成；网络记录必须出现
      `POST /api/reference/recipes` 且请求体含 portrait_id/costume_id/pose_id/
      costume_library/style，不得出现 POST /prompt、:8188、/comfy 提交；
      必须出现 `GET /api/jobs/{id}` 轮询，进度文案与百分比可见。
   3. 真实 ComfyUI 任务 5 分钟内完成时校验结果图 `naturalWidth > 0`；未完成或
      后端失败时如实记录“真实出图未验证”，并改用 route mock
      （mock recipes/jobs/media）独立验证结果图渲染。
   4. 任务中心链接必须是原生 `a[href="/jobs"]`，点击可达 atelier 任务页；
      失败分支（recipes 400 `{"detail":"测试用失败"}`）必须显示 detail 且
      `isGenerating` 结束；上传槽位提示可见且提交被拦截；
      参数面板冻结说明、只读提示词 + 独立补充要求、画风仅 none/realistic。

   只跑阶段四可设置 `T3_E2E_ONLY=phase4`（仍执行静态检查与 dist 产物检查）。

    T29/T30（embedded 去重）专项：`T3_E2E_ONLY=nav` 额外校验 iframe 内不再出现
    侧栏品牌块、「返回画廊」、顶栏「画室画廊」与面包屑根，同时保留 SidebarTrigger、
    三组侧栏导航与角色配方 footer；外层 Vue 仍保持 9 项导航。
    T31/T32（统一入口）专项：`T3_E2E_ONLY=nav` 追加校验直接访问 /ref-web/、
    /ref-web/poses 会整页归壳到 /reference?path=...，/reference 无 path 时仍为外壳；
    三入口外层仅一套 9 项导航、iframe 内无品牌/返回入口/全局导航；非法 ?path=
    回落 /ref-web/?embedded=1 且 console 0；390x844 无横向溢出。

    T34（页签内导航回归）专项：`T3_E2E_ONLY=nav` 追加校验 /reference iframe 内
    依次点击侧栏六个页签（图库总览、AI 角色合成台、动作姿势库、服装穿搭库、
    人像颜值库、ComfyUI 连接）后，即使 TanStack Router 丢掉 `embedded=1`，
    `nav[aria-label="画室全局导航"]`、`[data-slot="sidebar-header"]`、「返回画廊」、
    「画室画廊」仍全部为 0，面包屑只显示当前页、SidebarTrigger 仍在；
    对抗场景覆盖顶层 `/ref-web/?embedded=1`（self === top，保留 React 独立导航）
    与深链 `/ref-web/poses` 归壳；390x844 外层/iframe 均无横向溢出、
    iframe 首页与 poses 裂图 0、console/pageerror 0；并对运行中的 8656 做只读
    复核（不重启，点击至少 3 个页签，PID 前后不变）。

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
from urllib.parse import parse_qs, urlsplit

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

#: 阶段四：只跑阶段四时可设置 `T3_E2E_ONLY=phase4`（默认仍跑全量）。
P4_ONLY = os.environ.get("T3_E2E_ONLY", "").strip().lower() == "phase4"
#: mock 任务 id：仅用于结果图渲染验证，不写入真实后端。
P4_MOCK_JOB_ID = 900001
P4_PNG_BYTES = base64.b64decode(TINY_PNG_B64)


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

    # 说明：这里检查的是 React 侧栏 brand（仍为原生 a，文本含「画室」与「参考图库」）。
    # 外层 Vue 顶栏的「参考图库」在 iframe 方案下已改为 button，其语义由
    # check_embed_nav() 单独断言；若在此直接改成 button，会让默认全量的 React 页面
    # 断言 count==1 失败（React 侧栏没有 button 入口）。
    brand = page.locator('[data-slot="sidebar"] a[href="/gallery"]').filter(has_text="画室")
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
# 阶段四（T13）：合成台提交 -> 轮询 -> 结果图 -> 任务中心
#
# 真实提交使用临时实例（8766）；ComfyUI 真实任务 5 分钟内未完成或失败时，
# 结果图渲染改用 Playwright route mock 独立验证。报告中区分：
#   - 实测确认：POST 请求体、GET /api/jobs 轮询、进度 UI、失败分支、上传拦截；
#   - mock 确认：结果图 <img> 渲染与百分比进度条（仅 mock 场景）；
#   - 真实出图是否完成：按后端 job 快照与页面实际状态如实输出。
# ---------------------------------------------------------------------------
_P4_PROGRESS_INIT_JS = r"""() => {
    window.__p4Progress = { messages: [], percents: [] };
    const add = (arr, value) => { if (!arr.includes(value)) arr.push(value); };
    window.__p4Snap = () => {
        const bar = document.querySelector('[aria-label="生成进度"]');
        if (bar) add(window.__p4Progress.percents, Number(bar.getAttribute('aria-valuenow')));
        const text = document.body.innerText || '';
        for (const m of ['正在提交出图任务', '任务已提交，等待后端处理', '任务已提交，正在排队',
                         '正在出图', '任务已完成，正在获取生成结果', '任务已结束']) {
            if (text.includes(m)) add(window.__p4Progress.messages, m);
        }
    };
    if (window.__p4Mo) window.__p4Mo.disconnect();
    window.__p4Mo = new MutationObserver(window.__p4Snap);
    window.__p4Mo.observe(document.body, { subtree: true, childList: true,
                                            characterData: true, attributes: true });
    window.__p4Snap();
}"""

_P4_PROGRESS_READ_JS = r"""() => {
    if (window.__p4Snap) window.__p4Snap();
    return window.__p4Progress || { messages: [], percents: [] };
}"""

_P4_RESULT_STATE_JS = r"""() => {
    const img = document.querySelector('img[alt="生成结果"]');
    const text = document.body.innerText || '';
    const generating = text.includes('正在生成角色图…')
        || Array.from(document.querySelectorAll('button'))
            .some((b) => (b.textContent || '').includes('生成中…'));
    return {
        src: img ? (img.currentSrc || img.src) : '',
        loaded: Boolean(img && img.complete && img.naturalWidth > 0),
        generating,
        error: text.includes('生成失败'),
        noImage: text.includes('任务完成但未找到结果图'),
    };
}"""

_P4_RECIPE_JS = r"""() => {
    try {
        const raw = JSON.parse(localStorage.getItem('pose_atlas_recipe_v3') || '{}');
        return {
            portrait: raw.portrait || null,
            costume: raw.costume || null,
            pose: raw.pose || null,
        };
    } catch (e) {
        return { portrait: null, costume: null, pose: null };
    }
}"""


class _P4Network:
    """阶段四网络记录：提交、轮询、结果图与直连 ComfyUI 违规。"""

    def __init__(self, page) -> None:
        self.requests: list[tuple[str, str]] = []
        self.recipe_requests: list[dict] = []
        self.recipe_responses: list[dict] = []
        self.job_requests: list[str] = []
        self.media_requests: list[str] = []
        self.forbidden: list[str] = []
        page.on("request", self._on_request)
        page.on("response", self._on_response)

    def _on_request(self, req) -> None:
        method = req.method.upper()
        url = req.url
        parsed = urlsplit(url)
        path = parsed.path
        self.requests.append((method, url))

        if path == "/api/reference/recipes" and method == "POST":
            body: object
            try:
                body = json.loads(req.post_data or "{}")
            except Exception:
                body = {"__unparsed__": req.post_data}
            self.recipe_requests.append({"url": url, "body": body})
        if method == "GET" and re.fullmatch(r"/api/jobs/\d+", path):
            self.job_requests.append(url)
        if path.startswith("/api/media/image"):
            self.media_requests.append(url)

        # 计划 C-JOB-PROGRESS@1-5：不得直连 ComfyUI 提交
        if method == "POST" and path.rstrip("/").endswith("/prompt"):
            self.forbidden.append(f"POST {url}")
        if method in ("POST", "PUT", "PATCH") and (
                path.startswith("/comfy") or "/comfy/" in path):
            self.forbidden.append(f"{method} {url}")
        if parsed.port == 8188:
            self.forbidden.append(f"{method} {url}")

    def _on_response(self, resp) -> None:
        try:
            path = urlsplit(resp.url).path
        except Exception:
            return
        if path == "/api/reference/recipes" and resp.request.method.upper() == "POST":
            entry = {"status": resp.status, "body": None, "error": ""}
            try:
                entry["body"] = resp.json()
            except Exception as exc:
                entry["error"] = f"{type(exc).__name__}: {exc}"
            self.recipe_responses.append(entry)


def _p4_wait_cards(page, timeout_ms: int = 45000) -> None:
    page.get_by_role("button", name="加入配方", exact=True).first.wait_for(
        state="visible", timeout=timeout_ms)


def _p4_read_recipe(page) -> dict:
    return page.evaluate(_P4_RECIPE_JS)


def _p4_pick_three_slots(page, shots_dir: Path) -> dict:
    """从三个图库各选一条（服装必须是已缓存的二次元条目），最后回到合成台。"""
    current = _p4_read_recipe(page)

    if not current.get("portrait"):
        goto_settle(page, "/ref-web/portraits", "人像颜值库")
        _p4_wait_cards(page)
        page.get_by_role("button", name="加入配方", exact=True).first.click()
        page.wait_for_timeout(600)

    costume = current.get("costume") or {}
    if not costume or costume.get("library") != "costume-anime":
        goto_settle(page, "/ref-web/costumes", "服装穿搭库")
        _p4_wait_cards(page)
        page.get_by_role("button", name="二次元", exact=True).click()
        page.wait_for_timeout(1000)
        _p4_wait_cards(page)
        texts = _p3_card_texts(page)
        idx = next((i for i, text in enumerate(texts) if "CharaDB" in text), 0)
        buttons = page.get_by_role("button", name="加入配方", exact=True)
        if buttons.count() > 0:
            buttons.nth(min(idx, buttons.count() - 1)).click()
        page.wait_for_timeout(600)

    if not current.get("pose"):
        goto_settle(page, "/ref-web/poses", "动作姿势库")
        _p4_wait_cards(page)
        page.get_by_role("button", name="加入配方", exact=True).first.click()
        page.wait_for_timeout(600)

    goto_settle(page, "/ref-web/studio", "AI 角色合成台")
    try:
        page.wait_for_function(
            """() => {
                try {
                    const r = JSON.parse(localStorage.getItem('pose_atlas_recipe_v3') || '{}');
                    return Boolean(r.portrait && r.costume && r.pose);
                } catch { return false; }
            }""",
            timeout=20000,
        )
    except Exception:
        pass
    return _p4_read_recipe(page)


def _p4_ensure_three_slots(page, shots_dir: Path) -> dict:
    current = _p4_read_recipe(page)
    if current.get("portrait") and current.get("costume") and current.get("pose"):
        return current
    return _p4_pick_three_slots(page, shots_dir)


def _p4_install_progress_observer(page) -> None:
    page.evaluate(_P4_PROGRESS_INIT_JS)


def _p4_read_progress(page) -> dict:
    return page.evaluate(_P4_PROGRESS_READ_JS)


def _p4_wait_for_recipe_post(page, net: _P4Network, timeout_s: float = 90.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if net.recipe_requests and net.recipe_responses:
            return
        page.wait_for_timeout(400)


def check_phase4_recipe_testclient() -> None:
    section("阶段四-1 后端 recipes TestClient 契约（C-REF-RECIPES@2）")
    if str(V4) not in sys.path:
        sys.path.insert(0, str(V4))
    try:
        from fastapi.testclient import TestClient
        from app.main import app
    except Exception as exc:
        check(False, "[阶段四] 导入 TestClient 与 app.main",
              f"{type(exc).__name__}: {exc}")
        return

    client = TestClient(app)
    try:
        def _items(library: str, size: int = 5) -> list[dict]:
            resp = client.get(f"/api/reference/items?library={library}&page_size={size}")
            check(resp.status_code == 200, f"[阶段四] TestClient items {library} 返回 200",
                  f"status={resp.status_code}")
            return list((resp.json() or {}).get("items") or [])

        portraits = _items("portrait", 1)
        costumes = _items("costume", 1)
        poses = _items("pose", 5)
        anime_items = _items("costume-anime", 200)
        if not (portraits and costumes and poses):
            check(False, "[阶段四] TestClient 取得三个本地库条目",
                  f"portrait={len(portraits)} costume={len(costumes)} pose={len(poses)}")
            return

        cached_ids = _cached_item_ids()
        anime = next((it for it in anime_items if it.get("id") in cached_ids), None)
        check(anime is not None,
              "[阶段四] 找到可见且已缓存的 costume-anime 条目",
              f"visible={len(anime_items)} cached={len(cached_ids)}")

        base = {
            "portrait_id": portraits[0]["id"],
            "costume_id": costumes[0]["id"],
            "pose_id": poses[0]["id"],
            "dry_run": True,
        }

        resp = client.post("/api/reference/recipes", json=base)
        check(resp.status_code == 200, "[阶段四] TestClient 三图 dry_run 200",
              f"status={resp.status_code} body={resp.text[:180]}")
        if resp.status_code == 200:
            result = resp.json()
            nodes = [(n.get("role"), n.get("id")) for n in result.get("nodes", {}).get("inputs", [])]
            check(nodes == [("target", "1"), ("ref1", "2"), ("ref2", "3")],
                  "[阶段四] TestClient 三图节点映射 1/2/3", f"nodes={nodes}")
            check("三图角色合成" in (result.get("workflow_path") or ""),
                  "[阶段四] TestClient 三图工作流", f"workflow={result.get('workflow_path')}")
            check(result.get("dry_run") is True, "[阶段四] TestClient dry_run=true",
                  f"dry_run={result.get('dry_run')}")
            check("job_id" not in result, "[阶段四] TestClient dry_run 响应无 job_id",
                  f"keys={sorted(result)}")

        if len(poses) >= 2:
            resp4 = client.post("/api/reference/recipes", json={
                **base, "extra_library": "pose", "extra_id": poses[1]["id"],
            })
            check(resp4.status_code == 200, "[阶段四] TestClient 第 4 张 dry_run 200",
                  f"status={resp4.status_code} body={resp4.text[:180]}")
            if resp4.status_code == 200:
                result4 = resp4.json()
                nodes4 = [(n.get("role"), n.get("id"))
                          for n in result4.get("nodes", {}).get("inputs", [])]
                check(nodes4 == [("target", "1"), ("ref1", "2"), ("ref2", "3"),
                                 ("ref3", "78")],
                      "[阶段四] TestClient 四图节点映射 1/2/3/78", f"nodes={nodes4}")
                check("四图参考" in (result4.get("workflow_path") or ""),
                      "[阶段四] TestClient 四图工作流",
                      f"workflow={result4.get('workflow_path')}")

        if anime is not None:
            resp_anime = client.post("/api/reference/recipes", json={
                **base, "costume_id": anime["id"], "costume_library": "costume-anime",
            })
            check(resp_anime.status_code == 200,
                  "[阶段四] TestClient 已缓存 anime 服装 200",
                  f"status={resp_anime.status_code} body={resp_anime.text[:200]}")
            if resp_anime.status_code == 200:
                result_anime = resp_anime.json()
                slot = next((s for s in result_anime.get("slots", [])
                             if s.get("role") == "costume"), {})
                check(slot.get("library") == "costume-anime",
                      "[阶段四] TestClient 服装槽 library=costume-anime",
                      f"slot={slot}")
                check(str(CACHE_ROOT).lower() in (slot.get("path") or "").lower(),
                      "[阶段四] TestClient 服装槽解析到本机缓存文件",
                      f"path={slot.get('path')}")

        bad = client.post("/api/reference/recipes", json={
            **base, "costume_library": "bogus",
        })
        check(bad.status_code == 400, "[阶段四] TestClient 未知服装库 400",
              f"status={bad.status_code} body={bad.text[:160]}")
        check("不支持的服装库" in bad.text,
              "[阶段四] TestClient 未知服装库 detail 可读", f"body={bad.text[:160]}")

        # 对抗性探针：缺 extra_library / 未知画风 / 未知条目
        missing_extra_lib = client.post("/api/reference/recipes", json={
            **base, "extra_id": poses[0]["id"],
        })
        check(missing_extra_lib.status_code == 400,
              "[阶段四] TestClient 第 4 张缺库标识 400",
              f"status={missing_extra_lib.status_code} body={missing_extra_lib.text[:160]}")
        check("第 4 张缺少参考库标识" in missing_extra_lib.text,
              "[阶段四] TestClient 第 4 张缺库标识 detail",
              f"body={missing_extra_lib.text[:160]}")

        bad_style = client.post("/api/reference/recipes", json={
            **base, "style": "fashion",
        })
        check(bad_style.status_code == 400, "[阶段四] TestClient 未知画风 400",
              f"status={bad_style.status_code} body={bad_style.text[:160]}")
        check("不支持的画风" in bad_style.text,
              "[阶段四] TestClient 未知画风 detail", f"body={bad_style.text[:160]}")

        bad_item = client.post("/api/reference/recipes", json={
            **base, "costume_id": "no-such-item", "costume_library": "costume-anime",
        })
        check(bad_item.status_code == 404, "[阶段四] TestClient 未知 anime 条目 404",
              f"status={bad_item.status_code} body={bad_item.text[:160]}")
    finally:
        client.close()


def check_phase4_real_submit(browser, shots_dir: Path):
    """真实提交：三图库选择 -> POST recipes -> GET jobs 轮询 -> 结果图。返回 storage_state。"""
    section("阶段四-2 合成台真实提交（三图库选择 / POST recipes / GET jobs）")
    ctx = browser.new_context(viewport={"width": 1500, "height": 950})
    errors: list[str] = []
    page = new_page(ctx, errors, "p4-real")
    net = _P4Network(page)
    state = None
    try:
        pick: dict = {"portrait": None, "costume": None, "pose": None}
        try:
            pick = _p4_pick_three_slots(page, shots_dir)
        except Exception as exc:
            check(False, "[阶段四] 从三个图库选择条目",
                  f"{type(exc).__name__}: {exc}")

        check(pick.get("portrait") is not None, "[阶段四] 已选人像条目",
              f"name={(pick.get('portrait') or {}).get('发型名称')}")
        check(pick.get("costume") is not None, "[阶段四] 已选服装条目",
              f"name={(pick.get('costume') or {}).get('服装名称')}")
        check(pick.get("pose") is not None, "[阶段四] 已选姿势条目",
              f"name={(pick.get('pose') or {}).get('姿势名称')}")
        check((pick.get("costume") or {}).get("library") == "costume-anime",
              "[阶段四] 所选服装来自 costume-anime（CharaDB）",
              f"library={(pick.get('costume') or {}).get('library')}")

        initial_src = page.evaluate(
            """() => {
                const img = document.querySelector('img[alt="生成结果"]');
                return img ? (img.currentSrc || img.src) : '';
            }"""
        )
        _p4_install_progress_observer(page)
        page.screenshot(path=str(shots_dir / "phase4_studio_selected.png"))

        if not all(pick.get(k) for k in ("portrait", "costume", "pose")):
            observe("未选齐三个槽位，跳过真实提交", f"pick={pick}")
        else:
            page.get_by_role("button", name="生成角色图", exact=True).click()
            _p4_wait_for_recipe_post(page, net, timeout_s=90.0)

            check(bool(net.recipe_requests),
                  "[阶段四] 出现 POST /api/reference/recipes",
                  f"requests={[r['url'] for r in net.recipe_requests][:2]}")
            body = net.recipe_requests[0]["body"] if net.recipe_requests else {}
            if not isinstance(body, dict):
                body = {}
            for field in ("portrait_id", "costume_id", "pose_id",
                          "costume_library", "style"):
                check(bool(body.get(field)),
                      f"[阶段四] 请求体含 {field}", f"value={body.get(field)!r}")
            expected_library = (pick.get("costume") or {}).get("library") or "costume"
            check(body.get("costume_library") == expected_library,
                  "[阶段四] costume_library 与所选服装一致",
                  f"request={body.get('costume_library')!r} selected={expected_library!r}")
            check(body.get("style") in ("none", "realistic"),
                  "[阶段四] style 仅 none/realistic", f"style={body.get('style')!r}")
            check("prompt" not in body,
                  "[阶段四] 请求体不含完整 prompt 字段",
                  f"keys={sorted(body)}")
            check(body.get("seed_mode") in ("fixed", "random", "increment"),
                  "[阶段四] 请求体含合法 seed_mode", f"seed_mode={body.get('seed_mode')!r}")

            check(bool(net.recipe_responses), "[阶段四] 收到 recipes 响应",
                  f"responses={len(net.recipe_responses)}")
            resp = net.recipe_responses[0] if net.recipe_responses else {}
            check(resp.get("status") == 200, "[阶段四] recipes 返回 200",
                  f"status={resp.get('status')} body={str(resp.get('body'))[:180]}")
            job_id = 0
            try:
                job_id = int((resp.get("body") or {}).get("job_id") or 0)
            except Exception:
                job_id = 0
            check(job_id > 0, "[阶段四] recipes 返回 job_id",
                  f"job_id={job_id} error={resp.get('error')}")

            if job_id > 0:
                deadline = time.time() + 60
                while time.time() < deadline and not any(
                        url.endswith(f"/api/jobs/{job_id}") for url in net.job_requests):
                    page.wait_for_timeout(300)
                check(any(url.endswith(f"/api/jobs/{job_id}") for url in net.job_requests),
                      f"[阶段四] 出现 GET /api/jobs/{job_id} 轮询",
                      f"job_requests={net.job_requests[:3]}")

                progress = {"messages": [], "percents": []}
                deadline = time.time() + 30
                while time.time() < deadline:
                    progress = _p4_read_progress(page)
                    if progress.get("messages") and progress.get("percents"):
                        break
                    page.wait_for_timeout(250)
                check(bool(progress.get("messages")),
                      "[阶段四] UI 出现进度文案", f"messages={progress.get('messages')}")
                check(any(m != "正在提交出图任务"
                          for m in progress.get("messages", [])),
                      "[阶段四] 进度文案包含后端任务阶段",
                      f"messages={progress.get('messages')}")
                check(bool(progress.get("percents")),
                      "[阶段四] total>0 时 UI 出现百分比进度条",
                      f"percents={progress.get('percents')}")
                check(all(0 <= int(p) <= 100 for p in progress.get("percents", [])
                          if p == p),
                      "[阶段四] 百分比范围 0-100",
                      f"percents={progress.get('percents')}")
                if progress.get("percents"):
                    try:
                        page.locator('[aria-label="生成进度"]').first.scroll_into_view_if_needed(
                            timeout=5000)
                    except Exception:
                        pass
                    check(page.locator('[aria-label="生成进度"]').count() > 0
                          and page.locator('[aria-label="生成进度"]').first.is_visible(),
                          "[阶段四] 百分比进度条在视口内可见", "")
                page.screenshot(path=str(shots_dir / "phase4_progress_live.png"))

                outcome = "timeout"
                final_state: dict = {}
                deadline = time.time() + 300
                while time.time() < deadline:
                    final_state = page.evaluate(_P4_RESULT_STATE_JS)
                    changed = bool(final_state.get("src")) and \
                        final_state.get("src") != initial_src
                    if changed and final_state.get("loaded"):
                        outcome = "image"
                        break
                    if final_state.get("noImage"):
                        outcome = "no-image"
                        break
                    if final_state.get("error") and not final_state.get("generating"):
                        outcome = "error"
                        break
                    page.wait_for_timeout(2000)

                snapshot = None
                try:
                    snapshot = api_json(f"/api/jobs/{job_id}")
                except Exception as exc:
                    observe("读取后端任务快照失败", f"{type(exc).__name__}: {exc}")
                status = (snapshot or {}).get("status", "")
                try:
                    page.locator('img[alt="生成结果"]').first.scroll_into_view_if_needed(
                        timeout=5000)
                except Exception:
                    pass
                page.screenshot(path=str(shots_dir / "phase4_result_after_wait.png"))

                if outcome == "image":
                    check(final_state.get("loaded") is True,
                          "[阶段四] 真实任务结果图 naturalWidth > 0",
                          f"src={final_state.get('src')}")
                    check("/api/media/image" in (final_state.get("src") or ""),
                          "[阶段四] 真实结果图走 /api/media/image",
                          f"src={final_state.get('src')}")
                    check(bool(net.media_requests),
                          "[阶段四] 结果图请求已发生", f"count={len(net.media_requests)}")
                    observe("真实出图在 5 分钟内完成",
                            f"job={job_id} status={status} src={final_state.get('src')}")
                else:
                    detail = (f"job={job_id} status={status or '未知'} "
                              f"outcome={outcome} "
                              f"err={generation_error_text(page)[:120]!r}")
                    if outcome == "error":
                        observe("真实出图未验证：后端任务失败或出图失败，前端已显示失败文案", detail)
                    elif outcome == "no-image":
                        observe("真实出图未验证：任务完成但未找到结果图", detail)
                    else:
                        observe("真实出图未验证：ComfyUI 真实任务 5 分钟内未完成", detail)
                    if status == "done":
                        check(False, "[阶段四] 后端任务 done 时 UI 必须渲染结果图",
                              detail)

        forbidden = sorted(set(net.forbidden))
        check(not forbidden,
              "[阶段四] 无直连 ComfyUI 提交（POST /prompt、/comfy、:8188）",
              f"violations={forbidden[:5]}")
        check(not errors, "[阶段四] 真实提交链路无 console error / pageerror",
              "; ".join(errors[:5]))
    finally:
        try:
            state = ctx.storage_state()
        except Exception:
            state = None
        page.close()
        ctx.close()
    return state


def generation_error_text(page) -> str:
    try:
        return page.locator("p.whitespace-pre-wrap").first.inner_text()
    except Exception:
        return ""


def check_phase4_mock_result(browser, shots_dir: Path, storage_state) -> None:
    """route mock 验证结果图 <img> 渲染与百分比进度（真实出图未完成时的兜底证据）。"""
    section("阶段四-3 结果图渲染（route mock: recipes/jobs/media）")
    ctx = browser.new_context(viewport={"width": 1500, "height": 950},
                              storage_state=storage_state)
    errors: list[str] = []
    page = new_page(ctx, errors, "p4-mock")
    net = _P4Network(page)
    counter = {"n": 0}

    def recipes(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "success": True, "job_id": P4_MOCK_JOB_ID, "total": 1, "submitted": 1,
            "queued": 1, "errors": [], "async": True, "prompt": "mock prompt",
            "workflow_path": "mock-workflow.json", "slots": [], "references": {},
        }, ensure_ascii=False))

    def jobs(route):
        counter["n"] += 1
        running = counter["n"] <= 2
        snapshot = {
            "id": P4_MOCK_JOB_ID, "job_type": "faceswap",
            "status": "running" if running else "done", "title": "mock 任务",
            "total": 1, "done_count": 0 if running else 1, "error_count": 0,
            "items": [{
                "prompt_id": 0, "status": "running" if running else "done",
                "images": [] if running else [{
                    "filename": "mock-result.png", "subfolder": "", "type": "output",
                }],
            }],
            "workflow_path": "mock-workflow.json", "extra": None,
            "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:01",
        }
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(snapshot, ensure_ascii=False))

    def media(route):
        route.fulfill(status=200, content_type="image/png", body=P4_PNG_BYTES)

    page.route(re.compile(r".*/api/reference/recipes$"), recipes)
    page.route(re.compile(r".*/api/jobs/\d+$"), jobs)
    page.route(re.compile(r".*/api/media/image.*"), media)

    try:
        goto_settle(page, "/ref-web/studio", "AI 角色合成台")
        pick = _p4_ensure_three_slots(page, shots_dir)
        check(all(pick.get(k) for k in ("portrait", "costume", "pose")),
              "[阶段四-mock] 三个槽位已就绪", f"pick={ {k: bool(v) for k, v in pick.items()} }")
        initial_src = page.evaluate(
            """() => {
                const img = document.querySelector('img[alt="生成结果"]');
                return img ? (img.currentSrc || img.src) : '';
            }"""
        )
        _p4_install_progress_observer(page)
        page.get_by_role("button", name="生成角色图", exact=True).click()
        _p4_wait_for_recipe_post(page, net, timeout_s=30.0)
        check(bool(net.recipe_requests),
              "[阶段四-mock] mock 拦截到 POST /api/reference/recipes",
              f"count={len(net.recipe_requests)}")

        try:
            page.wait_for_function(
                """(initial) => {
                    const img = document.querySelector('img[alt="生成结果"]');
                    return Boolean(img && img.complete && img.naturalWidth > 0
                        && (img.currentSrc || img.src) !== initial);
                }""",
                arg=initial_src,
                timeout=30000,
            )
        except Exception as exc:
            check(False, "[阶段四-mock] 结果图在 30 秒内渲染", f"{type(exc).__name__}: {exc}")

        state = page.evaluate(_P4_RESULT_STATE_JS)
        check(state.get("loaded") is True,
              "[阶段四-mock] 结果图 naturalWidth > 0", f"src={state.get('src')}")
        check("/api/media/image" in (state.get("src") or ""),
              "[阶段四-mock] 结果图 URL 走 /api/media/image", f"src={state.get('src')}")
        check(bool(net.media_requests), "[阶段四-mock] 已请求 mock 媒体端点",
              f"count={len(net.media_requests)}")
        check(len(net.job_requests) >= 2, "[阶段四-mock] 轮询至少两次（running -> done）",
              f"count={len(net.job_requests)}")

        progress = _p4_read_progress(page)
        check(bool(progress.get("messages")),
              "[阶段四-mock] progress 文案可见", f"messages={progress.get('messages')}")
        check(bool(progress.get("percents")),
              "[阶段四-mock] 百分比进度条可见", f"percents={progress.get('percents')}")
        check(all(0 <= int(p) <= 100 for p in progress.get("percents", []) if p == p),
              "[阶段四-mock] 百分比范围 0-100", f"percents={progress.get('percents')}")
        check(not state.get("error"), "[阶段四-mock] 未出现失败文案", "")
        try:
            page.locator('img[alt="生成结果"]').first.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            pass
        page.screenshot(path=str(shots_dir / "phase4_mock_result.png"))
        check(not errors, "[阶段四-mock] 无 console error / pageerror",
              "; ".join(errors[:5]))
    finally:
        page.close()
        ctx.close()


def check_phase4_failure_branch(browser, shots_dir: Path, storage_state) -> None:
    """recipes 400：UI 显示 detail，isGenerating 必须结束。"""
    section("阶段四-4 失败分支（recipes 400 detail 透传 + 结束生成态）")
    ctx = browser.new_context(viewport={"width": 1500, "height": 950},
                              storage_state=storage_state)
    errors: list[str] = []
    page = new_page(ctx, errors, "p4-failure")
    net = _P4Network(page)

    def recipes(route):
        route.fulfill(status=400, content_type="application/json",
                      body=json.dumps({"detail": "测试用失败"}, ensure_ascii=False))

    page.route(re.compile(r".*/api/reference/recipes$"), recipes)
    try:
        goto_settle(page, "/ref-web/studio", "AI 角色合成台")
        pick = _p4_ensure_three_slots(page, shots_dir)
        check(all(pick.get(k) for k in ("portrait", "costume", "pose")),
              "[阶段四-失败] 三个槽位已就绪",
              f"pick={ {k: bool(v) for k, v in pick.items()} }")
        page.get_by_role("button", name="生成角色图", exact=True).click()

        deadline = time.time() + 30
        detail_visible = False
        while time.time() < deadline:
            if page.get_by_text("测试用失败", exact=False).count() > 0:
                detail_visible = True
                break
            page.wait_for_timeout(300)
        check(detail_visible, "[阶段四-失败] UI 显示后端 detail「测试用失败」", "")
        failure_title = page.get_by_text("生成失败", exact=True)
        check(failure_title.count() >= 1 and failure_title.first.is_visible(),
              "[阶段四-失败] UI 可见「生成失败」区域", "")
        error_para = page.locator("p.whitespace-pre-wrap")
        check(error_para.count() >= 1 and error_para.first.is_visible()
              and "测试用失败" in error_para.first.inner_text(),
              "[阶段四-失败] 错误卡片正文显示 detail（非仅 toast）",
              f"text={(error_para.first.inner_text()[:120] if error_para.count() else '')!r}")

        try:
            page.wait_for_function(
                """() => {
                    const b = Array.from(document.querySelectorAll('button'))
                        .find((x) => (x.textContent || '').trim() === '生成角色图');
                    return Boolean(b && !b.disabled);
                }""",
                timeout=15000,
            )
        except Exception:
            pass
        button = page.get_by_role("button", name="生成角色图", exact=True)
        check(button.count() >= 1 and button.first.is_enabled(),
              "[阶段四-失败] isGenerating 结束（生成按钮恢复可点击）", "")
        check(page.get_by_role("button", name=re.compile("生成中")).count() == 0,
              "[阶段四-失败] 无「生成中…」无限转圈", "")
        check(page.locator('[aria-label="生成进度"]').count() == 0,
              "[阶段四-失败] 失败后不残留进度条", "")
        check(bool(net.recipe_requests),
              "[阶段四-失败] 失败分支仍走 POST /api/reference/recipes",
              f"count={len(net.recipe_requests)}")
        try:
            failure_title.first.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            pass
        page.screenshot(path=str(shots_dir / "phase4_failure_branch.png"))
        # 本用例故意让接口返回 400；Chromium 会把该请求记成一条
        # "Failed to load resource: ... 400"，属于预期噪声，不算页面错误脚本。
        expected_400 = [e for e in errors
                        if "[p4-failure] console.error:" in e and "status of 400" in e]
        unexpected = [e for e in errors if e not in expected_400]
        check(not unexpected, "[阶段四-失败] 无预期外 console error / pageerror",
              f"unexpected={unexpected[:5]} expected_400={len(expected_400)}")
    finally:
        page.close()
        ctx.close()


def check_phase4_upload_slot(browser, shots_dir: Path) -> None:
    """上传槽位提示可见，且提交前被拦截（不发 POST）。"""
    section("阶段四-5 上传槽位提示与提交拦截")
    ctx = browser.new_context(viewport={"width": 1500, "height": 950})
    errors: list[str] = []
    page = new_page(ctx, errors, "p4-upload")
    net = _P4Network(page)
    png_path = shots_dir / "p4_upload_portrait.png"
    png_path.write_bytes(P4_PNG_BYTES)
    try:
        goto_settle(page, "/ref-web/studio", "AI 角色合成台")
        with page.expect_file_chooser() as chooser_info:
            page.get_by_role("button", name="上传人像参考图").click()
        chooser_info.value.set_files(str(png_path))
        page.wait_for_timeout(1500)

        note = page.locator('[role="note"]:has-text("本地图片上传暂未接入后端")')
        check(note.count() >= 1, "[阶段四-上传] 上传后提示文案可见", "")
        note_text = note.first.inner_text() if note.count() else ""
        check("本地图片上传暂未接入后端" in note_text and "人像" in note_text,
              "[阶段四-上传] 提示文案含拦截说明与槽位名", f"text={note_text[:120]}")

        page.get_by_role("button", name="生成角色图", exact=True).click()
        page.wait_for_timeout(1800)
        notices = " | ".join(_notice_texts(page))
        check("请从图库选择参考图" in notices,
              "[阶段四-上传] 提交前 toast 拦截上传图", f"notices={notices[:160]}")
        check(not net.recipe_requests,
              "[阶段四-上传] 上传图未发起 POST /api/reference/recipes",
              f"count={len(net.recipe_requests)}")
        try:
            note.first.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            pass
        page.screenshot(path=str(shots_dir / "phase4_upload_intercept.png"))
        check(not errors, "[阶段四-上传] 无 console error / pageerror",
              "; ".join(errors[:5]))
    finally:
        page.close()
        ctx.close()


def check_phase4_ui_contract(browser, shots_dir: Path) -> None:
    """参数面板冻结说明、只读提示词、补充要求、画风两项、任务中心链接。"""
    section("阶段四-6 参数面板冻结/提示词只读/画风两项/任务中心")
    ctx = browser.new_context(viewport={"width": 1500, "height": 950})
    errors: list[str] = []
    page = new_page(ctx, errors, "p4-ui")
    try:
        goto_settle(page, "/ref-web/studio", "AI 角色合成台")

        frozen = page.get_by_text(
            "参数面板不改变后端出图的节点与工作流（D4 冻结）", exact=False)
        check(frozen.count() >= 1, "[阶段四] 参数面板冻结说明可见", "")

        prompt_area = page.locator('textarea[aria-label="提示词预览（只读，由槽位生成）"]')
        check(prompt_area.count() == 1, "[阶段四] 提示词预览 textarea 存在",
              f"count={prompt_area.count()}")
        if prompt_area.count():
            check(prompt_area.first.evaluate("el => el.readOnly") is True,
                  "[阶段四] 提示词 textarea 只读", "")

        suffix_label = page.locator('label:text-is("补充要求（可选）")')
        check(suffix_label.count() == 1, "[阶段四] 独立「补充要求（可选）」输入存在",
              f"count={suffix_label.count()}")
        suffix_area = page.locator('textarea[placeholder*="prompt_suffix"]')
        check(suffix_area.count() == 1, "[阶段四] 补充要求 textarea 存在",
              f"count={suffix_area.count()}")
        if suffix_area.count():
            check(suffix_area.first.evaluate("el => el.readOnly") is False,
                  "[阶段四] 补充要求 textarea 可编辑", "")

        style_trigger = (
            page.locator('label:text-is("画风预设")')
            .locator("..").locator("..")
            .locator('button[role="combobox"]').first
        )
        check(style_trigger.count() == 1, "[阶段四] 画风下拉存在",
              f"count={style_trigger.count()}")
        if style_trigger.count():
            check("写实人像写真" in style_trigger.inner_text(),
                  "[阶段四] 画风默认显示写实人像写真",
                  f"text={style_trigger.inner_text()!r}")
            style_trigger.click()
            page.wait_for_timeout(500)
            options = page.get_by_role("option")
            texts = [options.nth(i).inner_text().strip() for i in range(options.count())]
            check(len(texts) == 2 and set(texts) == {"无预设（跟随参考图）", "写实人像写真"},
                  "[阶段四] 画风下拉仅 none / realistic 两项", f"options={texts}")
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)

        link = page.locator('a[href="/jobs"]:has-text("任务中心")')
        check(link.count() == 1, "[阶段四] 任务中心是原生 a[href=\"/jobs\"]",
              f"count={link.count()}")
        if link.count():
            check(link.first.get_attribute("href") == "/jobs",
                  "[阶段四] 任务中心 href 精确为 /jobs",
                  f"href={link.first.get_attribute('href')}")
            try:
                with page.expect_navigation(timeout=30000) as nav_info:
                    link.first.click()
                nav = nav_info.value
                check(nav is not None and nav.status == 200,
                      "[阶段四] 点击任务中心返回 200",
                      f"status={nav.status if nav else None}")
            except Exception as exc:
                check(False, "[阶段四] 点击任务中心可导航", f"{type(exc).__name__}: {exc}")
            try:
                page.wait_for_selector(".jobs .title", timeout=20000)
            except Exception:
                pass
            check("/jobs" in page.url, "[阶段四] 已到达 atelier /jobs",
                  f"url={page.url}")
            title = page.locator(".jobs .title").first
            check(title.count() == 1 and title.inner_text().strip() == "任务",
                  "[阶段四] atelier 任务页已渲染",
                  f"title={title.inner_text().strip() if title.count() else 'n/a'}")
            page.screenshot(path=str(shots_dir / "phase4_job_center.png"))

        check(not errors, "[阶段四] UI 契约检查无 console error / pageerror",
              "; ".join(errors[:5]))
    finally:
        page.close()
        ctx.close()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# T21 顶栏合并式改造专项（T22）
# ---------------------------------------------------------------------------
NAV_ONLY = os.environ.get("T3_E2E_ONLY", "").strip().lower() == "nav"

NAV_ITEMS: list[tuple[str, str]] = [
    ("画廊", "/gallery"),
    ("参考图库", "/ref-web"),
    ("提示词", "/prompt"),
    ("组合器", "/composer"),
    ("图像编辑", "/editor"),
    ("批量超分", "/upscale"),
    ("分类与标签", "/taxonomy"),
    ("任务", "/jobs"),
    ("统计", "/stats"),
]


def _nav_scope(page):
    return page.locator('nav[aria-label="画室全局导航"]')


def check_nav_merge(browser, shots_dir: Path) -> None:
    """T21 顶栏合并式改造：9 项链接 / 两层高度 / 3 个返回入口 / 跳转 / 窄屏。"""
    section("T21 顶栏合并式改造专项（新 context）")
    ctx = browser.new_context(viewport={"width": 1500, "height": 950})
    errors: list[str] = []
    page = new_page(ctx, errors, "t21-nav")
    try:
        # T31 之后直接访问 `/ref-web/` 会整页归壳到 `/reference`，React 独立导航只在
        # 显式 embedded=1 的顶层页面上保留；本专项验证后者（归壳行为见 check_unified_entry）。
        observe("T21 语义调整：直接 /ref-web 已归壳，本专项改用 /ref-web/?embedded=1 验证 React 独立导航",
                "T31 统一入口后 deep link 不再原地渲染 React 站点")
        status = goto_settle(page, "/ref-web/?embedded=1")
        check(status == 200, "[T21] /ref-web/?embedded=1 返回 200", f"status={status}")

        # 直接访问（非 embedded）时 Vue 侧不参与，仪表盘页签与 React 侧均同步渲染；
        # 仍等待面包屑出现，避免把首屏加载中的空 dom 误判成缺项。
        try:
            page.wait_for_function(
                "() => document.querySelectorAll('nav[aria-label=\"breadcrumb\"]').length >= 1",
                timeout=20000,
            )
        except Exception:
            pass

        nav = _nav_scope(page)
        check(nav.count() == 1, "[T21] 存在画室全局导航", f"count={nav.count()}")

        # a. 9 项导航：文案与 href 精确匹配，仅参考图库 aria-current=page
        nav_items = nav.locator("div > a")
        count = nav_items.count()
        check(count == 9, "[T21] 顶部导航 9 项", f"count={count}")
        for i, (label, href) in enumerate(NAV_ITEMS):
            if i >= count:
                check(False, f"[T21] 导航项缺失：{label}", "")
                continue
            el = nav_items.nth(i)
            text = (el.inner_text() or "").strip()
            actual_href = el.get_attribute("href")
            aria = el.get_attribute("aria-current")
            check(text == label, f"[T21] 导航文案：{label}", f"actual={text!r}")
            check(actual_href == href, f"[T21] 导航 href：{label}", f"actual={actual_href!r}")
            if label == "参考图库":
                check(aria == "page", "[T21] 参考图库 aria-current=page", f"actual={aria!r}")
            else:
                check(aria is None, f"[T21] {label} 无 aria-current", f"actual={aria!r}")

        # b. 两层高度与第二行原元素
        nav_box = nav.bounding_box()
        nav_h = round(nav_box["height"], 1) if nav_box else -1
        check(abs(nav_h - 52) <= 2, "[T21] 第一层高度 52px±2", f"height={nav_h}")
        second = page.locator("header > div").last
        second_box = second.bounding_box()
        second_h = round(second_box["height"], 1) if second_box else -1
        check(second_h >= 56, "[T21] 第二层高度 >=56px", f"height={second_h}")
        check(second.locator('nav[aria-label="breadcrumb"]').count() >= 1,
              "[T21] 第二行面包屑仍在", "")
        check(second.locator("button[title*='安全模式']").count() >= 1,
              "[T21] 第二行安全模式按钮仍在", "")
        check(second.locator("button:has-text('随机捏人')").count() >= 1,
              "[T21] 第二行随机捏人仍在", "")
        check(second.locator("a[aria-label*='AI 合成台']").count() >= 1,
              "[T21] 第二行 AI 合成台仍在", "")
        check(second.locator("button[aria-label='切换主题']").count() >= 1,
              "[T21] 第二行主题切换仍在", "")

        # c. 3 个返回入口：侧栏 brand（画室）、侧栏返回画廊、顶栏画室画廊
        sidebar = page.locator('[data-slot="sidebar"]')
        brand = sidebar.locator('a[href="/gallery"]').filter(has_text="画室")
        back = sidebar.locator('a[href="/gallery"]').filter(has_text="返回画廊")
        top_back = second.locator('a[href="/gallery"]').filter(has_text="画室画廊")
        check(brand.count() >= 1, "[T21] 侧栏 brand 返回入口", f"count={brand.count()}")
        check(back.count() >= 1, "[T21] 侧栏返回画廊入口", f"count={back.count()}")
        check(top_back.count() >= 1, "[T21] 顶栏画室画廊入口", f"count={top_back.count()}")
        hrefs = [
            brand.first.get_attribute("href") if brand.count() else None,
            back.first.get_attribute("href") if back.count() else None,
            top_back.first.get_attribute("href") if top_back.count() else None,
        ]
        check(hrefs == ["/gallery", "/gallery", "/gallery"],
              "[T21] 3 个返回入口 href 均为 /gallery", f"hrefs={hrefs}")

        # T29 回归保护：非 embedded（直接访问 /ref-web/）时面包屑仍正常渲染当前页。
        # 说明：HEAD 基线的 __root.tsx 未声明 staticData.title，crumbs 只含叶子路由，
        # 因此非 embedded 面包屑从来不含「画室画廊」根；T29 只过滤 embedded 分支，
        # 不改变这一既有行为。这里硬检查当前页存在，并对根 crumb 缺失如实观察。
        bc_plain = page.locator('nav[aria-label="breadcrumb"]')
        bc_plain_text = bc_plain.first.inner_text().strip() if bc_plain.count() else ""
        check(bc_plain.count() >= 1, "[T29] 非 embedded 面包屑存在", f"count={bc_plain.count()}")
        check("图库总览" in bc_plain_text, "[T29] 非 embedded 面包屑含当前页『图库总览』",
              f"text={bc_plain_text!r}")
        observe("非 embedded 面包屑根 crumb",
                f"text={bc_plain_text!r}；根路由无 staticData.title，HEAD 基线同样不含「画室画廊」")

        # h. 首页裂图 0
        wait_images_settled(page)
        home_stats = image_stats(page)
        check(home_stats["broken"] == 0, "[T21] /ref-web/ 裂图为 0",
              f"broken={home_stats['broken']}/{home_stats['total']} src={home_stats['brokenSrc']}")
        page.screenshot(path=str(shots_dir / "t21_nav_desktop.png"))

        # d. 点击提示词 -> /prompt 整页跳转（不得拼成 /ref-web/prompt）
        nav_items.nth(2).click()
        page.wait_for_function("() => window.location.pathname === '/prompt'", timeout=30000)
        page.wait_for_timeout(1200)
        prompt_url = page.url
        check("/ref-web/prompt" not in prompt_url, "[T21] 提示词跳转未拼 basepath", prompt_url)
        check(prompt_url.rstrip("/").endswith("/prompt"), "[T21] 提示词跳转到 /prompt", prompt_url)
        prompt_status = ctx.request.get(prompt_url).status
        check(prompt_status == 200, "[T21] /prompt 返回 200", f"status={prompt_status}")
        body_text = page.inner_text("body")
        check("提示词" in body_text, "[T21] /prompt 渲染出提示词标题",
              body_text[:60].replace("\n", " "))

        # e. 点击画廊 -> /gallery 200
        goto_settle(page, "/ref-web/?embedded=1")
        _nav_scope(page).locator("div > a").filter(has_text="画廊").first.click()
        page.wait_for_function("() => window.location.pathname === '/gallery'", timeout=30000)
        page.wait_for_timeout(1200)
        gallery_url = page.url
        check(gallery_url.rstrip("/").endswith("/gallery"),
              "[T21] 画廊跳转到 /gallery", gallery_url)
        gallery_status = ctx.request.get(gallery_url).status
        check(gallery_status == 200, "[T21] /gallery 返回 200", f"status={gallery_status}")
        page.screenshot(path=str(shots_dir / "t21_nav_gallery.png"))

        # e. 点击参考图库：T31 后原生链接会整页归壳到 /reference?path=/ref-web
        goto_settle(page, "/ref-web/?embedded=1")
        _nav_scope(page).locator("div > a").filter(has_text="参考图库").first.click()
        page.wait_for_function("() => location.pathname === '/reference'", timeout=30000)
        page.wait_for_timeout(800)
        ref_url = page.url
        ref_parsed = urlsplit(ref_url)
        check(ref_parsed.path.rstrip("/") == "/reference"
              and parse_qs(ref_parsed.query).get("path") in (["/ref-web"], ["/ref-web/"]),
              "[T21] 参考图库入口归壳到 /reference?path=/ref-web(/)", ref_url)

        # h. poses 裂图 0（不重复跑四页全量）
        poses_status = goto_settle(page, "/ref-web/poses?embedded=1", "动作姿势库")
        check(poses_status == 200, "[T21] /ref-web/poses 返回 200", f"status={poses_status}")
        wait_images_settled(page)
        poses_stats = image_stats(page)
        check(poses_stats["broken"] == 0, "[T21] /ref-web/poses 裂图为 0",
              f"broken={poses_stats['broken']}/{poses_stats['total']} src={poses_stats['brokenSrc']}")

        # g. console error/pageerror 0（本页与跳转后的 Vue 页面）
        check(not errors, "[T21] console error/pageerror 为 0", "; ".join(errors[:3]))

        # f. 窄屏 390x844：导航可横向滚动、页面不横向溢出
        page.set_viewport_size({"width": 390, "height": 844})
        goto_settle(page, "/ref-web/?embedded=1")
        scroll_data = page.evaluate(
            """() => {
                const nav = document.querySelector('nav[aria-label="画室全局导航"]');
                const scroller = nav ? nav.querySelector(':scope > div') : null;
                return {
                    innerWidth: window.innerWidth,
                    docScrollWidth: document.documentElement.scrollWidth,
                    navClientWidth: scroller ? scroller.clientWidth : -1,
                    navScrollWidth: scroller ? scroller.scrollWidth : -1,
                };
            }"""
        )
        check(scroll_data["navScrollWidth"] > scroll_data["navClientWidth"],
              "[T21] 窄屏导航可横向滚动",
              f"scrollWidth={scroll_data['navScrollWidth']} clientWidth={scroll_data['navClientWidth']}")
        check(scroll_data["docScrollWidth"] <= scroll_data["innerWidth"] + 1,
              "[T21] 窄屏页面无横向溢出",
              f"docScrollWidth={scroll_data['docScrollWidth']} innerWidth={scroll_data['innerWidth']}")
        page.screenshot(path=str(shots_dir / "t21_nav_narrow.png"))
    except Exception as exc:
        check(False, "[T21] 顶栏专项执行异常", f"{type(exc).__name__}: {exc}")
        try:
            page.screenshot(path=str(shots_dir / "t21_nav_error.png"))
        except Exception:
            pass
    finally:
        ctx.close()


def check_embed_nav(browser, shots_dir: Path) -> None:
    """T25 跨端无感切换：Vue 外层导航常驻、iframe 内无全局导航、target=_top 跳出。"""
    section("T25 跨端无感切换专项（新 context）")
    ctx = browser.new_context(viewport={"width": 1500, "height": 950})
    # 外层与 iframe 都注入错误收集器：iframe 的 console/pageerror 不会可靠冒泡到
    # page.on()，用 init script 在两种 document 内各自记录，验收时分别读取。
    ctx.add_init_script(
        "window.__t25errs = [];"
        "window.addEventListener('error', (e) => { try { window.__t25errs.push(String(e.message)); } catch (_) {} });"
        "window.addEventListener('unhandledrejection', (e) => { try { window.__t25errs.push(String(e.reason)); } catch (_) {} });"
    )
    errors: list[str] = []
    page = new_page(ctx, errors, "t25-embed")
    try:
        # a. /gallery 写标记，点击参考图库 -> /reference，标记保留（无整页刷新）
        status = goto_settle(page, "/gallery")
        check(status == 200, "[T25] /gallery 返回 200", f"status={status}")
        page.evaluate("() => { window.__atelierNavMark = 1 }")
        check(page.evaluate("() => window.__atelierNavMark") == 1,
              "[T25] 无刷新标记已写入", "mark=1")

        tabs = page.locator("nav.tabs")
        check(tabs.count() == 1, "[T25] 外层顶栏 tabs 存在", f"count={tabs.count()}")
        tabs.locator("button:has-text('参考图库')").first.click()
        page.wait_for_function("() => location.pathname === '/reference'", timeout=30000)
        page.wait_for_timeout(1200)
        check(page.evaluate("() => window.__atelierNavMark") == 1,
              "[T25] 点击参考图库无整页刷新（标记保留）", "mark=1")
        check(urlsplit(page.url).path.rstrip("/") == "/reference",
              "[T25] 参考图库路由为 /reference", page.url)

        # a. 提示词 -> /prompt，标记仍在；再回参考图库，标记仍在
        page.locator("nav.tabs button:has-text('提示词')").first.click()
        page.wait_for_function("() => location.pathname === '/prompt'", timeout=30000)
        page.wait_for_timeout(800)
        check(page.evaluate("() => window.__atelierNavMark") == 1,
              "[T25] 提示词跳转无整页刷新（标记保留）", "mark=1")
        check(urlsplit(page.url).path.rstrip("/") == "/prompt",
              "[T25] 提示词路由为 /prompt", page.url)
        page.locator("nav.tabs button:has-text('参考图库')").first.click()
        page.wait_for_function("() => location.pathname === '/reference'", timeout=30000)
        page.wait_for_timeout(1200)
        check(page.evaluate("() => window.__atelierNavMark") == 1,
              "[T25] 回到参考图库无整页刷新（标记保留）", "mark=1")

        # b. 外层 9 项且参考图库 active；iframe 恰 1 个，src 含 /ref-web 与 embedded=1
        tabs = page.locator("nav.tabs")
        labels = ["画廊", "参考图库", "提示词", "组合器", "图像编辑", "批量超分",
                  "分类与标签", "任务", "统计"]
        btns = tabs.locator("button")
        # Vue 的「参考图库」按钮受 /api/system/status 的 v-if 控制，首屏可能短暂只有
        # 8 项；等 9 项到齐再计数，否则会把加载时序误判为缺项（T30 专项复测时遇到）。
        try:
            page.wait_for_function(
                "() => document.querySelectorAll('nav.tabs button').length >= 9",
                timeout=20000,
            )
        except Exception:
            pass
        count = btns.count()
        check(count == 9, "[T25] 外层顶栏 9 项", f"count={count}")
        for i, label in enumerate(labels):
            if i >= count:
                check(False, f"[T25] 外层导航项缺失：{label}", "")
                continue
            el = btns.nth(i)
            text = (el.inner_text() or "").strip()
            cls = el.get_attribute("class") or ""
            is_active = "active" in cls.split()
            check(text.startswith(label), f"[T25] 外层导航文案：{label}", f"actual={text!r}")
            if label == "参考图库":
                check(is_active, "[T25] 参考图库按钮 active", f"class={cls!r}")
            else:
                check(not is_active, f"[T25] {label} 按钮非 active", f"class={cls!r}")

        iframe = page.locator(".reference-embed iframe")
        check(iframe.count() == 1, "[T25] 参考图库页恰有 1 个 iframe", f"count={iframe.count()}")
        iframe_src = iframe.first.get_attribute("src") if iframe.count() else ""
        check("/ref-web" in (iframe_src or "") and "embedded=1" in (iframe_src or ""),
              "[T25] iframe src 含 /ref-web 与 embedded=1", iframe_src or "无 src")
        page.screenshot(path=str(shots_dir / "t25_embed_desktop.png"))

        frame = page.frame_locator(".reference-embed iframe")
        try:
            frame.locator("#root > *").first.wait_for(state="attached", timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(1200)

        # c. iframe 内不含第一行全局导航；侧栏二级导航仍在
        inner_global = frame.locator('nav[aria-label="画室全局导航"]')
        check(inner_global.count() == 0,
              "[T25] iframe 内不存在第一行全局导航", f"count={inner_global.count()}")
        inner_text = frame.locator("body").inner_text(timeout=15000)
        absent = [w for w in ["提示词", "组合器", "批量超分", "统计"] if w in inner_text]
        check(not absent, "[T25] iframe 正文不含全局导航项", f"命中={absent}")
        check("图库总览" in inner_text, "[T25] iframe 侧栏『图库总览』仍在", "")
        check("AI 角色合成台" in inner_text or "AI 合成台" in inner_text,
              "[T25] iframe 侧栏『AI 合成台』仍在", "")

        # e. iframe 首页裂图 0
        frame.locator("body").evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(800)
        home_stats = frame.locator("body").evaluate(
            """() => {
                const imgs = Array.from(document.images);
                const broken = imgs.filter((i) => i.complete && i.naturalWidth === 0);
                return { total: imgs.length, broken: broken.length };
            }"""
        )
        check(home_stats["broken"] == 0, "[T25] iframe 首页裂图为 0",
              f"broken={home_stats['broken']}/{home_stats['total']}")

        # e. iframe 内 /ref-web/poses 裂图 0（保持 embedded=1 的 iframe 内导航）
        inner_frames = [f for f in page.frames if "/ref-web" in (f.url or "")]
        if inner_frames:
            try:
                inner_frames[0].goto(BASE + "/ref-web/poses?embedded=1",
                                     wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1500)
                inner_frames = [f for f in page.frames if "/ref-web" in (f.url or "")]
                poses_frame = inner_frames[0] if inner_frames else None
                if poses_frame is None:
                    check(False, "[T25] iframe poses frame 丢失", "")
                else:
                    poses_frame.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(800)
                    poses_stats = poses_frame.evaluate(
                        """() => {
                            const imgs = Array.from(document.images);
                            const broken = imgs.filter((i) => i.complete && i.naturalWidth === 0);
                            return { total: imgs.length, broken: broken.length };
                        }"""
                    )
                    check(poses_stats["broken"] == 0,
                          "[T25] iframe /ref-web/poses 裂图为 0",
                          f"broken={poses_stats['broken']}/{poses_stats['total']}")
            except Exception as exc:
                check(False, "[T25] iframe poses 导航失败", f"{type(exc).__name__}: {exc}")
        else:
            check(False, "[T25] 未找到 /ref-web iframe frame", "frames=[]")

        # e. console error/pageerror 0（外层监听 + 两种 document 的注入收集）
        outer_errs = page.evaluate("() => window.__t25errs || []")
        inner_errs: list[str] = []
        try:
            inner_errs = frame.locator("body").evaluate("() => window.__t25errs || []")
        except Exception:
            pass
        check(not errors and not outer_errs and not inner_errs,
              "[T25] console error/pageerror 为 0",
              f"page={errors[:2]} outer={outer_errs[:2]} inner={inner_errs[:2]}")

        # d. T29/T30 清理专项：embedded 时 iframe 内不得再出现重复的品牌块、
        #    「返回画廊」、顶栏「画室画廊」与面包屑根；但侧栏导航与角色配方必须保留。
        inner_frames = [f for f in page.frames if "/ref-web" in (f.url or "")]
        if inner_frames:
            try:
                inner_frames[0].goto(BASE + "/ref-web/?embedded=1",
                                     wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
        page.wait_for_timeout(1200)
        frame = page.frame_locator(".reference-embed iframe")
        try:
            frame.locator("#root > *").first.wait_for(state="attached", timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(800)

        check(frame.locator('[data-slot="sidebar-header"]').count() == 0,
              "[T30] iframe 侧栏品牌块不存在（sidebar-header count 0）",
              f"count={frame.locator('[data-slot=\"sidebar-header\"]').count()}")
        inner_gallery_links = frame.locator('a[href="/gallery"]')
        check(inner_gallery_links.count() == 0,
              "[T30] iframe 内跨应用返回链接 count 0",
              f"count={inner_gallery_links.count()} texts="
              f"{[inner_gallery_links.nth(i).inner_text() for i in range(inner_gallery_links.count())]}")
        back_text_count = frame.locator('text="返回画廊"').count()
        check(back_text_count == 0, "[T30] iframe 内『返回画廊』文本 count 0",
              f"count={back_text_count}")
        gallery_text_count = frame.locator('text="画室画廊"').count()
        check(gallery_text_count == 0, "[T30] iframe 内『画室画廊』文本 count 0",
              f"count={gallery_text_count}")
        studio_brand_count = frame.locator('[data-slot="sidebar"]').locator('text="画室"').count()
        check(studio_brand_count == 0, "[T30] iframe 侧栏『画室』品牌文本 count 0",
              f"count={studio_brand_count}")

        inner_bc = frame.locator('nav[aria-label="breadcrumb"]')
        inner_bc_text = inner_bc.first.inner_text().strip() if inner_bc.count() else ""
        check(inner_bc.count() >= 1, "[T30] iframe 面包屑存在", f"count={inner_bc.count()}")
        check("画室画廊" not in inner_bc_text, "[T30] iframe 面包屑不含『画室画廊』根",
              f"text={inner_bc_text!r}")
        check(inner_bc_text == "图库总览", "[T30] iframe 面包屑只剩当前页『图库总览』",
              f"text={inner_bc_text!r}")

        # T29 明确要求保留的部分：折叠触发器、三组侧栏导航、角色配方 footer。
        check(frame.locator('[data-slot="sidebar-trigger"]').count() == 1,
              "[T30] iframe SidebarTrigger 仍在",
              f"count={frame.locator('[data-slot=\"sidebar-trigger\"]').count()}")
        inner_group_labels = [
            frame.locator('[data-slot="sidebar-group-label"]').nth(i).inner_text()
            for i in range(frame.locator('[data-slot="sidebar-group-label"]').count())
        ]
        check(inner_group_labels == ["工作台", "三大参考图库", "配置"],
              "[T30] iframe 侧栏三组仍在", f"labels={inner_group_labels}")
        inner_body_text = frame.locator("body").inner_text(timeout=15000)
        required_items = ["图库总览", "AI 角色合成台", "动作姿势库", "服装穿搭库",
                          "人像颜值库", "ComfyUI 连接"]
        missing_items = [item for item in required_items if item not in inner_body_text]
        check(not missing_items, "[T30] iframe 侧栏导航项完整", f"缺失={missing_items}")
        footer_text = (
            frame.locator('[data-slot="sidebar-footer"]').first.inner_text()
            if frame.locator('[data-slot="sidebar-footer"]').count() else ""
        )
        check("角色配方槽" in footer_text, "[T30] iframe 角色配方 footer 仍在",
              f"text={footer_text!r}")

        # T29 清理后，跨应用返回入口只由外层 Vue 提供；iframe 内不得有 target=_top 残留。
        inner_top_targets = frame.locator('a[target="_top"]')
        check(inner_top_targets.count() == 0, "[T30] iframe 内无 target=_top 返回入口",
              f"count={inner_top_targets.count()}")

        # f. 桌面 1280x800：无横向溢出、9 项、iframe embedded、iframe 内无全局导航
        page.set_viewport_size({"width": 1280, "height": 800})
        page.goto(BASE + "/reference", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector(".reference-embed iframe", timeout=25000)
        page.wait_for_timeout(1500)
        # 整页重载后 status 查询返回前「参考图库」按钮不渲染（v-if），
        # 必须等 9 项全部出现再计数，否则会把加载过程误判为缺项。
        try:
            page.wait_for_function(
                "() => document.querySelectorAll('nav.tabs button').length >= 9",
                timeout=20000,
            )
        except Exception:
            pass
        desk_scroll = page.evaluate(
            """() => ({
                innerWidth: window.innerWidth,
                docScrollWidth: document.documentElement.scrollWidth,
            })"""
        )
        check(desk_scroll["docScrollWidth"] <= desk_scroll["innerWidth"] + 1,
              "[T25] 桌面 1280 无横向溢出",
              f"docScrollWidth={desk_scroll['docScrollWidth']} innerWidth={desk_scroll['innerWidth']}")
        desk_btns = page.locator("nav.tabs button")
        check(desk_btns.count() == 9, "[T25] 桌面 1280 顶栏 9 项", f"count={desk_btns.count()}")
        desk_ref_cls = page.locator("nav.tabs button:has-text('参考图库')").first.get_attribute("class") or ""
        check("active" in desk_ref_cls.split(), "[T25] 桌面 1280 参考图库 active", f"class={desk_ref_cls!r}")
        desk_src = page.locator(".reference-embed iframe").first.get_attribute("src") or ""
        check("/ref-web" in desk_src and "embedded=1" in desk_src,
              "[T25] 桌面 1280 iframe 含 embedded=1", desk_src)
        desk_frame = page.frame_locator(".reference-embed iframe")
        try:
            desk_frame.locator("#root > *").first.wait_for(state="attached", timeout=30000)
        except Exception:
            pass
        check(desk_frame.locator('nav[aria-label="画室全局导航"]').count() == 0,
              "[T25] 桌面 1280 iframe 内无全局导航", "")
        page.screenshot(path=str(shots_dir / "t25_embed_desktop1280.png"))

        # f. 窄屏 390x844：外层无横向溢出、tabs 可滚动、9 项仍 active；iframe 可见
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(BASE + "/reference", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector(".reference-embed iframe", timeout=25000)
        page.wait_for_timeout(1500)
        try:
            page.wait_for_function(
                "() => document.querySelectorAll('nav.tabs button').length >= 9",
                timeout=20000,
            )
        except Exception:
            pass
        scroll_data = page.evaluate(
            """() => {
                const tabs = document.querySelector('nav.tabs');
                return {
                    innerWidth: window.innerWidth,
                    docScrollWidth: document.documentElement.scrollWidth,
                    tabsClientWidth: tabs ? tabs.clientWidth : -1,
                    tabsScrollWidth: tabs ? tabs.scrollWidth : -1,
                };
            }"""
        )
        check(scroll_data["docScrollWidth"] <= scroll_data["innerWidth"] + 1,
              "[T25] 窄屏外层无横向溢出",
              f"docScrollWidth={scroll_data['docScrollWidth']} innerWidth={scroll_data['innerWidth']}")
        check(scroll_data["tabsScrollWidth"] > scroll_data["tabsClientWidth"],
              "[T25] 窄屏 tabs 可横向滚动",
              f"scrollWidth={scroll_data['tabsScrollWidth']} clientWidth={scroll_data['tabsClientWidth']}")
        narrow_btns = page.locator("nav.tabs button")
        check(narrow_btns.count() == 9, "[T25] 窄屏顶栏 9 项", f"count={narrow_btns.count()}")
        narrow_ref_cls = page.locator("nav.tabs button:has-text('参考图库')").first.get_attribute("class") or ""
        check("active" in narrow_ref_cls.split(), "[T25] 窄屏参考图库 active", f"class={narrow_ref_cls!r}")
        iframe_box = page.locator(".reference-embed iframe").bounding_box()
        check(bool(iframe_box) and iframe_box["width"] > 0 and iframe_box["height"] > 0,
              "[T25] 窄屏 iframe 内容可见", f"box={iframe_box}")
        page.screenshot(path=str(shots_dir / "t25_embed_narrow.png"))
    except Exception as exc:
        check(False, "[T25] 无感切换专项执行异常", f"{type(exc).__name__}: {exc}")
        try:
            page.screenshot(path=str(shots_dir / "t25_embed_error.png"))
        except Exception:
            pass
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# T31/T32 统一入口深链专项
# ---------------------------------------------------------------------------
#: 外层 Vue 顶栏 9 项（与 check_nav_merge 的 NAV_ITEMS 文案一致）。
T32_OUTER_LABELS = ["画廊", "参考图库", "提示词", "组合器", "图像编辑", "批量超分",
                    "分类与标签", "任务", "统计"]
#: 外层与 iframe 两份 document 各自记录错误，避免 iframe 的 pageerror 不冒泡。
T32_INIT_SCRIPT = (
    "window.__t32errs = [];"
    "window.addEventListener('error', (e) => { try { window.__t32errs.push(String(e.message)); } catch (_) {} });"
    "window.addEventListener('unhandledrejection', (e) => { try { window.__t32errs.push(String(e.reason)); } catch (_) {} });"
)


def _t32_new_page(browser, tag: str, viewport: dict | None = None):
    """新 context + 错误收集（外层/iframe 各一份），返回 (ctx, page, errors, navs)。"""
    ctx = browser.new_context(viewport=viewport or {"width": 1500, "height": 950})
    ctx.add_init_script(T32_INIT_SCRIPT)
    errors: list[str] = []
    page = new_page(ctx, errors, tag)
    navs: list[str] = []
    page.on("framenavigated", lambda frame: navs.append(frame.url or ""))
    return ctx, page, errors, navs


def _t32_wait_shell(page, timeout: int = 30000) -> None:
    """等待非 embedded 深链整页 replace 到 Vue 外壳，并等外层 9 项到齐。"""
    page.wait_for_function("() => location.pathname === '/reference'", timeout=timeout)
    page.wait_for_timeout(1200)
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('nav.tabs button').length >= 9",
            timeout=20000,
        )
    except Exception:
        pass


def _t32_inner_frame(page):
    """拿到 iframe 的 FrameLocator 并等 React 根挂载。"""
    frame = page.frame_locator(".reference-embed iframe")
    try:
        frame.locator("#root > *").first.wait_for(state="attached", timeout=30000)
    except Exception:
        pass
    page.wait_for_timeout(1200)
    return frame


def _t32_inner_image_stats(frame) -> dict:
    return frame.locator("body").evaluate(
        """() => {
            const imgs = Array.from(document.images);
            const broken = imgs.filter((i) => i.complete && i.naturalWidth === 0);
            return {
                total: imgs.length,
                broken: broken.length,
                src: broken.slice(0, 3).map((i) => i.currentSrc || i.src),
            };
        }"""
    )


def _t32_inner_errors(frame) -> list[str]:
    try:
        return frame.locator("body").evaluate("() => window.__t32errs || []")
    except Exception:
        return []


def _t32_outer_injected_errors(page) -> list[str]:
    try:
        return page.evaluate("() => window.__t32errs || []")
    except Exception:
        return []


def _t32_assert_shell_chrome(page, frame, label: str) -> None:
    """外层单导航 + iframe 内无品牌/返回入口/全局导航（三入口共用断言）。"""
    btns = page.locator("nav.tabs button")
    labels = [(btns.nth(i).inner_text() or "").strip() for i in range(btns.count())]
    check(btns.count() == 9, f"[T32] {label} 外层顶栏 9 项", f"count={btns.count()}")
    # 「任务」按钮会追加进行中任务数徽标（如「任务 1」），文案断言不能精确等于标签，
    # 只剥离尾部数字徽标再比对，避免后端瞬时任务数让既有门禁随机失败。
    normalized_labels = [re.sub(r"\s+\d+$", "", text).strip() for text in labels]
    check(normalized_labels == T32_OUTER_LABELS,
          f"[T32] {label} 外层顶栏文案完整", f"labels={labels}")
    active = [
        text for i, text in enumerate(labels)
        if "active" in (btns.nth(i).get_attribute("class") or "").split()
    ]
    check(active == ["参考图库"], f"[T32] {label} 仅参考图库 active", f"active={active}")

    outer_nav = page.locator('nav[aria-label="画室全局导航"]')
    check(outer_nav.count() == 0, f"[T32] {label} 外层无 React 独立全局导航",
          f"count={outer_nav.count()}")

    check(frame.locator("nav.tabs").count() == 0,
          f"[T32] {label} iframe 内 nav.tabs 为 0",
          f"count={frame.locator('nav.tabs').count()}")
    check(frame.locator('[data-slot="sidebar-header"]').count() == 0,
          f"[T32] {label} iframe 内 sidebar-header 为 0",
          f"count={frame.locator('[data-slot=\"sidebar-header\"]').count()}")
    check(frame.locator('nav[aria-label="画室全局导航"]').count() == 0,
          f"[T32] {label} iframe 内无全局导航",
          f"count={frame.locator('nav[aria-label=\"画室全局导航\"]').count()}")
    check(frame.locator('text="返回画廊"').count() == 0,
          f"[T32] {label} iframe 内『返回画廊』为 0",
          f"count={frame.locator('text=\"返回画廊\"').count()}")
    check(frame.locator('text="画室画廊"').count() == 0,
          f"[T32] {label} iframe 内『画室画廊』为 0",
          f"count={frame.locator('text=\"画室画廊\"').count()}")
    check(frame.locator('a[href="/gallery"]').count() == 0,
          f"[T32] {label} iframe 内 `/gallery` 返回链接为 0",
          f"count={frame.locator('a[href=\"/gallery\"]').count()}")

    inner_text = frame.locator("body").inner_text(timeout=15000)
    leaked = [word for word in ["提示词", "组合器", "批量超分", "统计"] if word in inner_text]
    check(not leaked, f"[T32] {label} iframe 正文无外层导航项", f"命中={leaked}")

    # 侧栏核心导航仍在，证明 iframe 不是空壳/白屏。
    for item in ["图库总览", "动作姿势库", "服装穿搭库", "人像颜值库"]:
        check(item in inner_text, f"[T32] {label} iframe 侧栏含『{item}』", "")
    check(frame.locator('[data-slot="sidebar-trigger"]').count() == 1,
          f"[T32] {label} iframe SidebarTrigger 仍在",
          f"count={frame.locator('[data-slot=\"sidebar-trigger\"]').count()}")


def _t32_finish_entry(page, frame, errors: list[str], label: str, shot: Path) -> None:
    """iframes 裂图 0 + 外层/iframe console 0 + 截图。"""
    stats = _t32_inner_image_stats(frame)
    check(stats["broken"] == 0, f"[T32] {label} iframe 裂图为 0",
          f"broken={stats['broken']}/{stats['total']} src={stats['src']}")
    inner_errs = _t32_inner_errors(frame)
    outer_injected = _t32_outer_injected_errors(page)
    check(not errors and not inner_errs and not outer_injected,
          f"[T32] {label} 外层与 iframe console/pageerror 为 0",
          f"page={errors[:2]} outer={outer_injected[:2]} inner={inner_errs[:2]}")
    try:
        page.screenshot(path=str(shot))
    except Exception as exc:
        observe(f"[T32] {label} 截图失败", f"{type(exc).__name__}: {exc}")


def _t32_entry(browser, label: str, path: str, expected_path: str | None,
               shots_dir: Path, shot_name: str) -> dict | None:
    """打开一个入口并断言：最终 URL、外层单导航、iframe 单导航、深链内容。"""
    ctx, page, errors, navs = _t32_new_page(browser, f"t32-{label}")
    try:
        resp = page.goto(BASE + path, wait_until="domcontentloaded", timeout=60000)
        status = resp.status if resp else None
        check(status == 200, f"[T32] {label} 返回 200", f"status={status}")
        _t32_wait_shell(page)

        final_path = urlsplit(page.url).path.rstrip("/") or "/"
        check(final_path == "/reference", f"[T32] {label} 最终 URL 为 /reference",
              page.url)

        iframe = page.locator(".reference-embed iframe")
        check(iframe.count() == 1, f"[T32] {label} 恰有 1 个 iframe", f"count={iframe.count()}")
        src = (iframe.first.get_attribute("src") or "") if iframe.count() else ""
        check("embedded=1" in src, f"[T32] {label} iframe src 含 embedded=1", src or "无 src")

        frame = _t32_inner_frame(page)
        _t32_assert_shell_chrome(page, frame, label)
        _t32_finish_entry(page, frame, errors, label, shots_dir / shot_name)
        return {"url": page.url, "src": src, "navs": list(navs), "errors": list(errors)}
    except Exception as exc:
        check(False, f"[T32] {label} 专项执行异常", f"{type(exc).__name__}: {exc}")
        try:
            page.screenshot(path=str(shots_dir / f"t32_{label}_error.png"))
        except Exception:
            pass
        return None
    finally:
        ctx.close()


def _t32_entry_home(browser, shots_dir: Path) -> None:
    section("T32-a 直接访问 /ref-web/ 自动归壳")
    ctx, page, errors, navs = _t32_new_page(browser, "t32-home")
    try:
        resp = page.goto(BASE + "/ref-web/", wait_until="domcontentloaded", timeout=60000)
        check(resp is not None and resp.status == 200, "[T32-a] /ref-web/ 返回 200",
              f"status={resp.status if resp else None}")
        _t32_wait_shell(page)
        query = page.evaluate("() => new URLSearchParams(location.search).get('path')")
        check(urlsplit(page.url).path.rstrip("/") == "/reference",
              "[T32-a] 最终 URL 为 /reference", page.url)
        check(query == "/ref-web/", "[T32-a] path 参数为原始深链 /ref-web/", f"path={query!r}")

        iframe = page.locator(".reference-embed iframe")
        check(iframe.count() == 1, "[T32-a] 恰有 1 个 iframe", f"count={iframe.count()}")
        src = (iframe.first.get_attribute("src") or "") if iframe.count() else ""
        check(urlsplit(src or "/").path == "/ref-web/", "[T32-a] iframe 指向 /ref-web/", src)
        check("embedded=1" in src, "[T32-a] iframe src 含 embedded=1", src)

        frame = _t32_inner_frame(page)
        _t32_assert_shell_chrome(page, frame, "a.home")
        check(frame.locator('nav[aria-label="breadcrumb"]').first.inner_text().strip() == "图库总览",
              "[T32-a] iframe 面包屑为『图库总览』",
              frame.locator('nav[aria-label="breadcrumb"]').first.inner_text().strip())
        _t32_finish_entry(page, frame, errors, "a.home", shots_dir / "t32_entry_home.png")
    except Exception as exc:
        check(False, "[T32-a] 专项执行异常", f"{type(exc).__name__}: {exc}")
        try:
            page.screenshot(path=str(shots_dir / "t32_home_error.png"))
        except Exception:
            pass
    finally:
        ctx.close()


def _t32_entry_poses(browser, shots_dir: Path) -> None:
    section("T32-b 直接访问 /ref-web/poses 深链归壳并渲染姿势内容")
    ctx, page, errors, navs = _t32_new_page(browser, "t32-poses")
    try:
        resp = page.goto(BASE + "/ref-web/poses", wait_until="domcontentloaded", timeout=60000)
        check(resp is not None and resp.status == 200, "[T32-b] /ref-web/poses 返回 200",
              f"status={resp.status if resp else None}")
        _t32_wait_shell(page)
        query = page.evaluate("() => new URLSearchParams(location.search).get('path')")
        check(urlsplit(page.url).path.rstrip("/") == "/reference",
              "[T32-b] 最终 URL 为 /reference", page.url)
        check(query == "/ref-web/poses", "[T32-b] path 参数保留 poses 深链", f"path={query!r}")

        iframe = page.locator(".reference-embed iframe")
        check(iframe.count() == 1, "[T32-b] 恰有 1 个 iframe", f"count={iframe.count()}")
        src = (iframe.first.get_attribute("src") or "") if iframe.count() else ""
        check("/ref-web/poses" in src, "[T32-b] iframe src 含 /ref-web/poses", src)
        check("embedded=1" in src, "[T32-b] iframe src 含 embedded=1", src)

        frame = _t32_inner_frame(page)
        _t32_assert_shell_chrome(page, frame, "b.poses")

        inner_text = frame.locator("body").inner_text(timeout=15000)
        check("动作姿势库" in inner_text, "[T32-b] iframe 渲染『动作姿势库』标题", "")
        check(frame.locator("h1").filter(has_text="动作姿势库").count() >= 1,
              "[T32-b] iframe h1 为动作姿势库",
              f"count={frame.locator('h1').filter(has_text='动作姿势库').count()}")
        join_cards = frame.locator("button:has-text('加入配方')").count()
        check(join_cards >= 10, "[T32-b] iframe 姿势卡片可见", f"加入配方按钮={join_cards}")
        breadcrumb = frame.locator('nav[aria-label="breadcrumb"]').first.inner_text().strip()
        check(breadcrumb == "动作姿势库", "[T32-b] iframe 面包屑为『动作姿势库』",
              f"breadcrumb={breadcrumb!r}")
        _t32_finish_entry(page, frame, errors, "b.poses", shots_dir / "t32_entry_poses.png")

        # T32-d：iframe 内不得再发生二次重定向，也不得嵌套 /reference iframe。
        frames = [f.url for f in page.frames]
        inner_frames = [url for url in frames if "/ref-web" in url]
        check(len(inner_frames) == 1, "[T32-d] 仅 1 个 /ref-web iframe frame",
              f"frames={frames}")
        if inner_frames:
            check("embedded=1" in inner_frames[0],
                  "[T32-d] iframe frame URL 保持 embedded=1", inner_frames[0])
            check("/reference" not in inner_frames[0],
                  "[T32-d] iframe frame URL 未变成 /reference", inner_frames[0])
        nested = frame.locator('iframe[src*="/reference"]').count()
        check(nested == 0, "[T32-d] iframe 内无 /reference 嵌套 iframe", f"count={nested}")
        inner_navs = [url for url in navs if "/ref-web" in url]
        inner_embedded_navs = [url for url in inner_navs if "embedded=1" in url]
        check(set(inner_embedded_navs) == {BASE + "/ref-web/poses?embedded=1"},
              "[T32-d] iframe 仅加载过一次 embedded=1 深链",
              f"navs={inner_embedded_navs}")
        check(not any("/reference" in url for url in inner_embedded_navs),
              "[T32-d] iframe 未二次导航到 /reference", f"navs={inner_embedded_navs}")
    except Exception as exc:
        check(False, "[T32-b] 专项执行异常", f"{type(exc).__name__}: {exc}")
        try:
            page.screenshot(path=str(shots_dir / "t32_poses_error.png"))
        except Exception:
            pass
    finally:
        ctx.close()


def _t32_entry_reference(browser, shots_dir: Path) -> None:
    section("T32-c 直接访问 /reference（无 path 参数）")
    ctx, page, errors, navs = _t32_new_page(browser, "t32-reference")
    try:
        resp = page.goto(BASE + "/reference", wait_until="domcontentloaded", timeout=60000)
        check(resp is not None and resp.status == 200, "[T32-c] /reference 返回 200",
              f"status={resp.status if resp else None}")
        _t32_wait_shell(page)
        check(urlsplit(page.url).path.rstrip("/") == "/reference",
              "[T32-c] 最终 URL 为 /reference", page.url)
        query = page.evaluate("() => new URLSearchParams(location.search).get('path')")
        check(query is None, "[T32-c] 无 path 参数", f"path={query!r}")

        iframe = page.locator(".reference-embed iframe")
        check(iframe.count() == 1, "[T32-c] 恰有 1 个 iframe", f"count={iframe.count()}")
        src = (iframe.first.get_attribute("src") or "") if iframe.count() else ""
        check(urlsplit(src or "/").path.rstrip("/") == "/ref-web",
              "[T32-c] iframe 指向 /ref-web/", src)
        check("embedded=1" in src, "[T32-c] iframe src 含 embedded=1", src)
        check(urlsplit(src or "/").query == "embedded=1",
              "[T32-c] iframe src 精确为 /ref-web/?embedded=1", src)

        frame = _t32_inner_frame(page)
        _t32_assert_shell_chrome(page, frame, "c.reference")
        _t32_finish_entry(page, frame, errors, "c.reference", shots_dir / "t32_entry_reference.png")
    except Exception as exc:
        check(False, "[T32-c] 专项执行异常", f"{type(exc).__name__}: {exc}")
        try:
            page.screenshot(path=str(shots_dir / "t32_reference_error.png"))
        except Exception:
            pass
    finally:
        ctx.close()


def _t32_fallback(browser, shots_dir: Path, raw_query: str, slug: str) -> None:
    """非法 `?path=` 必须回落到 /ref-web/，且 console 为 0。"""
    ctx, page, errors, _navs = _t32_new_page(browser, f"t32-fb-{slug}")
    try:
        resp = page.goto(f"{BASE}/reference?path={raw_query}",
                         wait_until="domcontentloaded", timeout=60000)
        check(resp is not None and resp.status == 200, f"[T32-e] 回退探针 {slug} 返回 200",
              f"status={resp.status if resp else None}")
        page.wait_for_selector(".reference-embed iframe", timeout=25000)
        page.wait_for_timeout(1500)
        iframe = page.locator(".reference-embed iframe")
        check(iframe.count() == 1, f"[T32-e] 回退探针 {slug} 恰有 1 个 iframe",
              f"count={iframe.count()}")
        src = (iframe.first.get_attribute("src") or "") if iframe.count() else ""
        check(src == "/ref-web/?embedded=1",
              f"[T32-e] 回退探针 {slug} iframe 回落 /ref-web/", src or "无 src")
        bad_marks = [mark for mark in ["passwd", "evil.example", "..", "%2e%2e", "ref-webevil", "\\"]
                     if mark in src]
        check(not bad_marks, f"[T32-e] 回退探针 {slug} 未指向非法地址", f"命中={bad_marks}")
        frame = _t32_inner_frame(page)
        inner_errs = _t32_inner_errors(frame)
        outer_injected = _t32_outer_injected_errors(page)
        check(not errors and not inner_errs and not outer_injected,
              f"[T32-e] 回退探针 {slug} console/pageerror 为 0",
              f"page={errors[:2]} outer={outer_injected[:2]} inner={inner_errs[:2]}")
        page.screenshot(path=str(shots_dir / f"t32_fallback_{slug}.png"))
    except Exception as exc:
        check(False, f"[T32-e] 回退探针 {slug} 执行异常", f"{type(exc).__name__}: {exc}")
        try:
            page.screenshot(path=str(shots_dir / f"t32_fallback_{slug}_error.png"))
        except Exception:
            pass
    finally:
        ctx.close()


def _t32_multi_path(browser, shots_dir: Path) -> None:
    """重复 path 参数只取第一个合法值（对抗探针）。"""
    ctx, page, errors, _navs = _t32_new_page(browser, "t32-multi-path")
    try:
        page.goto(BASE + "/reference?path=/ref-web/poses&path=/etc/passwd",
                  wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector(".reference-embed iframe", timeout=25000)
        page.wait_for_timeout(1500)
        src = page.locator(".reference-embed iframe").first.get_attribute("src") or ""
        check(src == "/ref-web/poses?embedded=1",
              "[T32-e+] 重复 path 只取第一个合法值", src or "无 src")
        check(not errors, "[T32-e+] 重复 path console 为 0", f"page={errors[:2]}")
        page.screenshot(path=str(shots_dir / "t32_multi_path.png"))
    except Exception as exc:
        check(False, "[T32-e+] 重复 path 执行异常", f"{type(exc).__name__}: {exc}")
    finally:
        ctx.close()


def _t32_narrow(browser, shots_dir: Path) -> None:
    """390x844 深链入口：外层无横向溢出、9 项完整、iframe 无裂图。"""
    ctx, page, errors, _navs = _t32_new_page(browser, "t32-narrow",
                                             viewport={"width": 390, "height": 844})
    try:
        resp = page.goto(BASE + "/ref-web/poses", wait_until="domcontentloaded", timeout=60000)
        check(resp is not None and resp.status == 200, "[T32-f] 窄屏 /ref-web/poses 返回 200",
              f"status={resp.status if resp else None}")
        _t32_wait_shell(page)
        check(urlsplit(page.url).path.rstrip("/") == "/reference",
              "[T32-f] 窄屏最终 URL 为 /reference", page.url)
        scroll_data = page.evaluate(
            """() => {
                const tabs = document.querySelector('nav.tabs');
                return {
                    innerWidth: window.innerWidth,
                    docScrollWidth: document.documentElement.scrollWidth,
                    tabsClientWidth: tabs ? tabs.clientWidth : -1,
                    tabsScrollWidth: tabs ? tabs.scrollWidth : -1,
                };
            }"""
        )
        check(scroll_data["docScrollWidth"] <= scroll_data["innerWidth"] + 1,
              "[T32-f] 窄屏页面无横向溢出",
              f"docScrollWidth={scroll_data['docScrollWidth']} innerWidth={scroll_data['innerWidth']}")
        check(scroll_data["tabsScrollWidth"] > scroll_data["tabsClientWidth"],
              "[T32-f] 窄屏外层 tabs 可横向滚动",
              f"scrollWidth={scroll_data['tabsScrollWidth']} clientWidth={scroll_data['tabsClientWidth']}")
        btns = page.locator("nav.tabs button")
        check(btns.count() == 9, "[T32-f] 窄屏外层顶栏 9 项", f"count={btns.count()}")
        ref_cls = page.locator("nav.tabs button:has-text('参考图库')").first.get_attribute("class") or ""
        check("active" in ref_cls.split(), "[T32-f] 窄屏参考图库 active", f"class={ref_cls!r}")
        box = page.locator(".reference-embed iframe").bounding_box()
        check(bool(box) and box["width"] > 0 and box["height"] > 0,
              "[T32-f] 窄屏 iframe 可见", f"box={box}")
        frame = _t32_inner_frame(page)
        stats = _t32_inner_image_stats(frame)
        check(stats["broken"] == 0, "[T32-f] 窄屏 iframe 裂图为 0",
              f"broken={stats['broken']}/{stats['total']} src={stats['src']}")
        inner_errs = _t32_inner_errors(frame)
        outer_injected = _t32_outer_injected_errors(page)
        check(not errors and not inner_errs and not outer_injected,
              "[T32-f] 窄屏外层与 iframe console/pageerror 为 0",
              f"page={errors[:2]} outer={outer_injected[:2]} inner={inner_errs[:2]}")
        page.screenshot(path=str(shots_dir / "t32_narrow_poses.png"))
    except Exception as exc:
        check(False, "[T32-f] 窄屏专项执行异常", f"{type(exc).__name__}: {exc}")
        try:
            page.screenshot(path=str(shots_dir / "t32_narrow_error.png"))
        except Exception:
            pass
    finally:
        ctx.close()


def check_unified_entry(browser, shots_dir: Path) -> None:
    """T31/T32：三条入口统一归壳，外层单导航、iframe 内无重复导航与品牌入口。"""
    section("T32 统一入口深链专项（/ref-web/、/ref-web/poses、/reference）")
    _t32_entry_home(browser, shots_dir)
    _t32_entry_poses(browser, shots_dir)
    _t32_entry_reference(browser, shots_dir)

    section("T32-e 非法 path 回退探针")
    for raw, slug in [
        ("/etc/passwd", "passwd"),
        ("//evil.example/x", "protocol_relative"),
        ("%2Fref-web%2F%2e%2e%2Fx", "encoded_traversal"),
        ("%2Fref-webevil%2Fx", "refwebevil"),
        ("%2Fref-web%5C..%5Cetc", "backslash"),
    ]:
        _t32_fallback(browser, shots_dir, raw, slug)
    _t32_multi_path(browser, shots_dir)

    section("T32-f 窄屏 390x844 深链入口")
    _t32_narrow(browser, shots_dir)


# ---------------------------------------------------------------------------
# T34 页签内导航回归专项（commit 24f0100）
#
# 回归背景：`isEmbeddedMode()` 曾经依赖地址里的 `embedded=1`。TanStack Router 在
# iframe 内做客户端导航时会丢掉 query（点击侧栏后 URL 变成 `/ref-web/portraits`），
# 组件重渲染时判定退回「非嵌入」，侧栏品牌、返回入口与全局导航重新出现。
# 修复后判定只看 `window.self !== window.top`；本专项逐个点击侧栏页签，验证丢
# query 之后四项仍为 0，并覆盖两个对抗场景（顶层 embedded=1 / 深链归壳）。
# ---------------------------------------------------------------------------
#: 侧栏 6 个页签：(点击文案, 截图 slug, 期望 iframe 路径, 期望 h1, 期望面包屑)
#: 面包屑取路由 staticData.title，因此 studio 页为「AI 合成台」而非 h1 的「AI 角色合成台」。
T34_TABS: list[tuple[str, str, str, str, str]] = [
    ("图库总览", "home", "/ref-web/", "AI 角色参考库", "图库总览"),
    ("AI 角色合成台", "studio", "/ref-web/studio", "AI 角色合成台", "AI 合成台"),
    ("动作姿势库", "poses", "/ref-web/poses", "动作姿势库", "动作姿势库"),
    ("服装穿搭库", "costumes", "/ref-web/costumes", "服装穿搭库", "服装穿搭库"),
    ("人像颜值库", "portraits", "/ref-web/portraits", "人像颜值库", "人像颜值库"),
    ("ComfyUI 连接", "settings", "/ref-web/settings", "ComfyUI 连接", "ComfyUI 连接"),
]


def _t34_inner_url(page) -> str:
    """当前 /ref-web iframe 的绝对 URL（未加载时返回空串）。"""
    for f in page.frames:
        if "/ref-web" in (f.url or ""):
            return f.url or ""
    return ""


def _t34_h1(frame) -> str:
    try:
        loc = frame.locator("h1")
        if loc.count() == 0:
            return ""
        return loc.first.inner_text(timeout=1000).strip()
    except Exception:
        return ""


def _t34_wait_h1(frame, expected: str, timeout_ms: int = 25000) -> str:
    deadline = time.time() + timeout_ms / 1000
    actual = ""
    while time.time() < deadline:
        actual = _t34_h1(frame)
        if actual == expected:
            return actual
        time.sleep(0.25)
    return actual


def _t34_wait_inner_url(page, before: str, expected_path: str,
                        timeout_ms: int = 25000) -> str:
    """等 iframe 发生客户端导航，且路径落到期望值（URL 丢 query 也要能命中）。"""
    deadline = time.time() + timeout_ms / 1000
    actual = before
    while time.time() < deadline:
        actual = _t34_inner_url(page)
        if actual and actual != before and \
                urlsplit(actual).path.rstrip("/") == expected_path.rstrip("/"):
            return actual
        page.wait_for_timeout(150)
    return actual


def _t34_collect_inner_errors(frame, sink: list[str]) -> None:
    """把当前 iframe document 的错误并入总表（客户端导航不会重置 init script）。"""
    for item in _t32_inner_errors(frame):
        text = str(item)
        if text not in sink:
            sink.append(text)


def _t34_assert_no_duplicate_nav(frame, label: str) -> dict:
    """iframe 内四项重复导航必须为 0，SidebarTrigger 必须仍在。"""
    targets = [
        ('nav[aria-label="画室全局导航"]', "画室全局导航"),
        ('[data-slot="sidebar-header"]', "侧栏品牌块"),
        ('text="返回画廊"', "返回画廊"),
        ('text="画室画廊"', "画室画廊"),
    ]
    counts: dict[str, int] = {}
    for selector, human in targets:
        value = frame.locator(selector).count()
        counts[human] = value
        check(value == 0, f"[T34] {label} iframe {human} 为 0", f"count={value}")
    trigger = frame.locator('[data-slot="sidebar-trigger"]').count()
    check(trigger == 1, f"[T34] {label} iframe SidebarTrigger 仍在", f"count={trigger}")
    return counts


def _t34_assert_breadcrumb(frame, label: str, expected: str) -> str:
    """面包屑只显示当前页，且不含「画室画廊」根。"""
    bc_loc = frame.locator('nav[aria-label="breadcrumb"]')
    count = bc_loc.count()
    check(count >= 1, f"[T34] {label} iframe 面包屑存在", f"count={count}")
    text = bc_loc.first.inner_text().strip() if count else ""
    check("画室画廊" not in text, f"[T34] {label} iframe 面包屑不含『画室画廊』",
          f"text={text!r}")
    check(text == expected, f"[T34] {label} iframe 面包屑仅为当前页『{expected}』",
          f"actual={text!r}")
    return text


def _t34_click_tab(page, frame, label: str, slug: str, expected_path: str,
                   expected_h1: str, expected_crumb: str, tag: str,
                   shots_dir: Path, inner_errors: list[str]) -> None:
    """点击 iframe 侧栏页签，等待 h1/URL 到位后断言重复导航未复现。"""
    link = frame.locator('[data-slot="sidebar"] a').filter(has_text=label).first
    link_count = link.count()
    check(link_count == 1, f"[T34] {tag} 侧栏页签『{label}』存在且唯一",
          f"count={link_count}")
    if link_count != 1:
        return

    before_url = _t34_inner_url(page)
    before_h1 = _t34_h1(frame)
    link.click()
    url = _t34_wait_inner_url(page, before_url, expected_path)
    actual_h1 = _t34_wait_h1(frame, expected_h1)
    page.wait_for_timeout(600)

    path = urlsplit(url).path.rstrip("/")
    check(path == expected_path.rstrip("/"),
          f"[T34] {tag} 页签『{label}』iframe 路径为 {expected_path}",
          f"url={url}")
    check(actual_h1 == expected_h1,
          f"[T34] {tag} 页签『{label}』h1 为『{expected_h1}』",
          f"actual={actual_h1!r}")
    if before_h1 == actual_h1:
        observe(f"[T34] {tag} 页签『{label}』h1 未变化",
                f"before={before_h1!r} url={url}")
    else:
        observe(f"[T34] {tag} 页签『{label}』h1 变化", f"{before_h1!r} -> {actual_h1!r}")
    # 丢 query 是本回归的触发条件：如实记录，但不判失败（修复后不依赖 query）。
    if "embedded=1" not in url:
        observe(f"[T34] {tag} 页签『{label}』iframe URL 已丢 embedded=1（预期）", url)
    else:
        observe(f"[T34] {tag} 页签『{label}』iframe URL 仍带 embedded=1", url)

    _t34_assert_no_duplicate_nav(frame, f"{tag}·{label}")
    _t34_assert_breadcrumb(frame, f"{tag}·{label}", expected_crumb)
    _t34_collect_inner_errors(frame, inner_errors)

    try:
        page.screenshot(path=str(shots_dir / f"t34_tab_{tag}_{slug}.png"))
    except Exception as exc:
        observe(f"[T34] {tag} 页签『{label}』截图失败", f"{type(exc).__name__}: {exc}")


def _t34_scroll_metrics(page, frame) -> dict:
    outer = page.evaluate(
        "() => ({ innerWidth: window.innerWidth, "
        "docScrollWidth: document.documentElement.scrollWidth })"
    )
    inner = frame.locator("body").evaluate(
        """() => ({
            innerWidth: window.innerWidth,
            docScrollWidth: document.documentElement.scrollWidth,
        })"""
    )
    return {"outer": outer, "inner": inner}


def _t34_wait_inner_images(frame, timeout_ms: int = 30000) -> dict:
    """滚动 iframe 文档触发懒加载，等全部图片完成后返回裂图统计。"""
    frame.locator("body").evaluate("window.scrollTo(0, document.body.scrollHeight)")
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        try:
            done = frame.locator("body").evaluate(
                "() => Array.from(document.images).every((i) => i.complete)"
            )
        except Exception:
            done = False
        if done:
            break
        time.sleep(0.3)
    frame.locator("body").evaluate("window.scrollTo(0, document.body.scrollHeight)")
    return _t32_inner_image_stats(frame)


def _t34_top_embedded(browser, shots_dir: Path) -> None:
    """T34-c：顶层直接打开 /ref-web/?embedded=1，self === top，保留 React 独立导航。"""
    section("T34-c 顶层 /ref-web/?embedded=1 保留 React 独立导航")
    ctx, page, errors, _navs = _t32_new_page(browser, "t34-top-embedded",
                                             viewport={"width": 1500, "height": 950})
    try:
        resp = page.goto(BASE + "/ref-web/?embedded=1", wait_until="domcontentloaded",
                         timeout=60000)
        check(resp is not None and resp.status == 200,
              "[T34] c 顶层 embedded=1 返回 200",
              f"status={resp.status if resp else None}")
        try:
            page.wait_for_function(
                "() => document.querySelectorAll('nav[aria-label=\"画室全局导航\"]').length >= 1",
                timeout=25000,
            )
        except Exception:
            pass
        page.wait_for_timeout(800)

        check(page.evaluate("() => window.self === window.top"),
              "[T34] c 顶层页面 self === top", "")
        check(urlsplit(page.url).path.rstrip("/") == "/ref-web",
              "[T34] c 顶层 embedded=1 未被归壳", page.url)
        nav = page.locator('nav[aria-label="画室全局导航"]')
        check(nav.count() == 1, "[T34] c 顶层保留 React 全局导航",
              f"count={nav.count()}")
        check(nav.locator("div > a").count() == 9,
              "[T34] c 顶层 React 全局导航 9 项",
              f"count={nav.locator('div > a').count()}")
        header_count = page.locator('[data-slot="sidebar-header"]').count()
        check(header_count == 1, "[T34] c 顶层保留侧栏品牌块", f"count={header_count}")
        back_count = page.locator('text="返回画廊"').count()
        check(back_count == 1, "[T34] c 顶层保留『返回画廊』", f"count={back_count}")
        studio_count = page.locator('text="画室画廊"').count()
        check(studio_count == 1, "[T34] c 顶层保留『画室画廊』", f"count={studio_count}")
        check(not errors, "[T34] c 顶层 embedded=1 console/pageerror 为 0",
              "; ".join(errors[:3]))
        page.screenshot(path=str(shots_dir / "t34_top_embedded.png"))
    except Exception as exc:
        check(False, "[T34] c 顶层 embedded=1 专项执行异常",
              f"{type(exc).__name__}: {exc}")
        try:
            page.screenshot(path=str(shots_dir / "t34_top_embedded_error.png"))
        except Exception:
            pass
    finally:
        ctx.close()


def _t34_deep_link_poses(browser, shots_dir: Path) -> None:
    """T34-d：直接访问 /ref-web/poses 归壳到 /reference?path=...，iframe 无重复导航。"""
    section("T34-d 直接访问 /ref-web/poses 归壳并渲染『动作姿势库』")
    ctx, page, errors, _navs = _t32_new_page(browser, "t34-deeplink")
    inner_errors: list[str] = []
    try:
        resp = page.goto(BASE + "/ref-web/poses", wait_until="domcontentloaded",
                         timeout=60000)
        check(resp is not None and resp.status == 200,
              "[T34] d /ref-web/poses 返回 200",
              f"status={resp.status if resp else None}")
        _t32_wait_shell(page)
        check(urlsplit(page.url).path.rstrip("/") == "/reference",
              "[T34] d 最终 URL 为 /reference", page.url)
        query = page.evaluate("() => new URLSearchParams(location.search).get('path')")
        check(query == "/ref-web/poses", "[T34] d path 参数保留 poses 深链",
              f"path={query!r}")

        iframe = page.locator(".reference-embed iframe")
        check(iframe.count() == 1, "[T34] d 恰有 1 个 iframe", f"count={iframe.count()}")
        src = (iframe.first.get_attribute("src") or "") if iframe.count() else ""
        check("/ref-web/poses" in src and "embedded=1" in src,
              "[T34] d iframe 指向 /ref-web/poses?embedded=1", src or "无 src")

        frame = _t32_inner_frame(page)
        _t34_assert_no_duplicate_nav(frame, "d·深链")
        _t34_assert_breadcrumb(frame, "d·深链", "动作姿势库")
        actual_h1 = _t34_h1(frame)
        check(actual_h1 == "动作姿势库", "[T34] d iframe h1 为『动作姿势库』",
              f"actual={actual_h1!r}")
        inner_text = frame.locator("body").inner_text(timeout=15000)
        check("动作姿势库" in inner_text, "[T34] d iframe 正文含『动作姿势库』", "")
        _t34_collect_inner_errors(frame, inner_errors)

        outer_injected = _t32_outer_injected_errors(page)
        check(not errors and not inner_errors and not outer_injected,
              "[T34] d 深链 console/pageerror 为 0",
              f"page={errors[:2]} outer={outer_injected[:2]} inner={inner_errors[:2]}")
        page.screenshot(path=str(shots_dir / "t34_deeplink_poses.png"))
    except Exception as exc:
        check(False, "[T34] d 深链 poses 专项执行异常", f"{type(exc).__name__}: {exc}")
        try:
            page.screenshot(path=str(shots_dir / "t34_deeplink_error.png"))
        except Exception:
            pass
    finally:
        ctx.close()


def _t34_narrow(browser, shots_dir: Path) -> None:
    """T34-e：390x844 外层/iframe 无横向溢出、裂图 0、console 0。"""
    section("T34-e 390x844 无横向溢出、iframe 首页与 poses 裂图 0")
    ctx, page, errors, _navs = _t32_new_page(browser, "t34-narrow",
                                             viewport={"width": 390, "height": 844})
    inner_errors: list[str] = []
    try:
        resp = page.goto(BASE + "/reference", wait_until="domcontentloaded", timeout=60000)
        check(resp is not None and resp.status == 200,
              "[T34] e 窄屏 /reference 返回 200",
              f"status={resp.status if resp else None}")
        page.wait_for_selector(".reference-embed iframe", timeout=25000)
        frame = _t32_inner_frame(page)

        _t34_assert_no_duplicate_nav(frame, "e·窄屏首页")
        _t34_assert_breadcrumb(frame, "e·窄屏首页", "图库总览")
        metrics = _t34_scroll_metrics(page, frame)
        check(metrics["outer"]["docScrollWidth"] <= metrics["outer"]["innerWidth"] + 1,
              "[T34] e 窄屏外层无横向溢出",
              f"docScrollWidth={metrics['outer']['docScrollWidth']} "
              f"innerWidth={metrics['outer']['innerWidth']}")
        check(metrics["inner"]["docScrollWidth"] <= metrics["inner"]["innerWidth"] + 1,
              "[T34] e 窄屏 iframe 内无横向溢出",
              f"docScrollWidth={metrics['inner']['docScrollWidth']} "
              f"innerWidth={metrics['inner']['innerWidth']}")
        home_stats = _t34_wait_inner_images(frame)
        check(home_stats["broken"] == 0, "[T34] e 窄屏 iframe 首页裂图为 0",
              f"broken={home_stats['broken']}/{home_stats['total']} "
              f"src={home_stats['src']}")
        _t34_collect_inner_errors(frame, inner_errors)
        page.screenshot(path=str(shots_dir / "t34_narrow_home.png"))

        resp = page.goto(BASE + "/ref-web/poses", wait_until="domcontentloaded",
                         timeout=60000)
        check(resp is not None and resp.status == 200,
              "[T34] e 窄屏 /ref-web/poses 返回 200",
              f"status={resp.status if resp else None}")
        _t32_wait_shell(page)
        frame = _t32_inner_frame(page)
        _t34_assert_no_duplicate_nav(frame, "e·窄屏poses")
        _t34_assert_breadcrumb(frame, "e·窄屏poses", "动作姿势库")
        metrics = _t34_scroll_metrics(page, frame)
        check(metrics["outer"]["docScrollWidth"] <= metrics["outer"]["innerWidth"] + 1,
              "[T34] e 窄屏 poses 外层无横向溢出",
              f"docScrollWidth={metrics['outer']['docScrollWidth']} "
              f"innerWidth={metrics['outer']['innerWidth']}")
        check(metrics["inner"]["docScrollWidth"] <= metrics["inner"]["innerWidth"] + 1,
              "[T34] e 窄屏 poses iframe 内无横向溢出",
              f"docScrollWidth={metrics['inner']['docScrollWidth']} "
              f"innerWidth={metrics['inner']['innerWidth']}")
        poses_stats = _t34_wait_inner_images(frame)
        check(poses_stats["broken"] == 0, "[T34] e 窄屏 iframe poses 裂图为 0",
              f"broken={poses_stats['broken']}/{poses_stats['total']} "
              f"src={poses_stats['src']}")
        _t34_collect_inner_errors(frame, inner_errors)

        outer_injected = _t32_outer_injected_errors(page)
        check(not errors and not inner_errors and not outer_injected,
              "[T34] e 窄屏外层与 iframe console/pageerror 为 0",
              f"page={errors[:2]} outer={outer_injected[:2]} inner={inner_errors[:2]}")
        page.screenshot(path=str(shots_dir / "t34_narrow_poses.png"))
    except Exception as exc:
        check(False, "[T34] e 窄屏专项执行异常", f"{type(exc).__name__}: {exc}")
        try:
            page.screenshot(path=str(shots_dir / "t34_narrow_error.png"))
        except Exception:
            pass
    finally:
        ctx.close()


def _pid_on_port(port: int) -> str | None:
    """读取监听指定端口的进程 PID（Windows netstat / POSIX lsof），只读不杀进程。"""
    try:
        if os.name == "nt":
            proc = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=20)
        else:
            proc = subprocess.run(["lsof", "-ti", f"tcp:{port}"], capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=20)
    except Exception:
        return None
    pids: set[str] = set()
    if os.name == "nt":
        for line in (proc.stdout or "").splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0].upper() == "TCP" and "LISTENING" in parts:
                if parts[1].rsplit(":", 1)[-1] == str(port):
                    pids.add(parts[-1])
    else:
        pids = {ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip().isdigit()}
    return ",".join(sorted(pids)) or None


def check_live_8656_tab_nav(browser, shots_dir: Path) -> None:
    """T34-f：8656 只读复核，不重启，验证页签内导航同样不回落独立导航。"""
    section("T34-f 运行中 8656 只读复核（不重启，PID 前后不变）")
    live = f"http://127.0.0.1:{LIVE_PORT}"
    pid_before = _pid_on_port(LIVE_PORT)
    check(pid_before is not None, "[T34] f 记录 8656 监听 PID（前）",
          f"pid={pid_before}")
    status = http_get_status(live + "/")
    check(status == 200, "[T34] f 8656 GET 探活 200（只读）", f"status={status}")
    if status != 200:
        check(False, "[T34] f 8656 不可用，无法复核", f"status={status}")
        return

    ctx, page, errors, _navs = _t32_new_page(browser, "t34-live-8656")
    inner_errors: list[str] = []
    clicked = 0
    try:
        resp = page.goto(live + "/reference", wait_until="domcontentloaded", timeout=60000)
        check(resp is not None and resp.status == 200,
              "[T34] f 8656 /reference 返回 200",
              f"status={resp.status if resp else None}")
        page.wait_for_selector(".reference-embed iframe", timeout=25000)
        frame = _t32_inner_frame(page)
        _t34_assert_no_duplicate_nav(frame, "f·8656 初始")
        _t34_assert_breadcrumb(frame, "f·8656 初始", "图库总览")
        _t34_collect_inner_errors(frame, inner_errors)

        for label, slug, path, h1, crumb in T34_TABS[2:5]:
            _t34_click_tab(page, frame, label, slug, path, h1, crumb, "f·8656",
                           shots_dir, inner_errors)
            clicked += 1
        check(clicked >= 3, "[T34] f 8656 至少点击 3 个页签", f"clicked={clicked}")

        outer_injected = _t32_outer_injected_errors(page)
        check(not errors and not inner_errors and not outer_injected,
              "[T34] f 8656 外层与 iframe console/pageerror 为 0",
              f"page={errors[:2]} outer={outer_injected[:2]} inner={inner_errors[:2]}")
        page.screenshot(path=str(shots_dir / "t34_live_8656.png"))
    except Exception as exc:
        check(False, "[T34] f 8656 只读复核执行异常", f"{type(exc).__name__}: {exc}")
        try:
            page.screenshot(path=str(shots_dir / "t34_live_8656_error.png"))
        except Exception:
            pass
    finally:
        ctx.close()

    pid_after = _pid_on_port(LIVE_PORT)
    check(pid_after is not None, "[T34] f 记录 8656 监听 PID（后）",
          f"pid={pid_after}")
    check(pid_before == pid_after, "[T34] f 8656 PID 前后不变（未重启）",
          f"before={pid_before} after={pid_after}")
    status_after = http_get_status(live + "/")
    check(status_after == 200, "[T34] f 复核后 8656 仍可用", f"status={status_after}")


def check_tab_nav_regression(browser, shots_dir: Path) -> None:
    """T34：/reference 页签内导航后不得回落独立导航，并覆盖两个对抗场景。"""
    section("T34-a 初始 /reference：iframe 内无重复导航")
    ctx, page, errors, _navs = _t32_new_page(browser, "t34-tabs")
    inner_errors: list[str] = []
    try:
        resp = page.goto(BASE + "/reference", wait_until="domcontentloaded", timeout=60000)
        check(resp is not None and resp.status == 200, "[T34] a /reference 返回 200",
              f"status={resp.status if resp else None}")
        page.wait_for_selector(".reference-embed iframe", timeout=25000)
        src = page.locator(".reference-embed iframe").first.get_attribute("src") or ""
        check("embedded=1" in src, "[T34] a 初始 iframe src 含 embedded=1", src)

        frame = _t32_inner_frame(page)
        _t34_assert_no_duplicate_nav(frame, "a·初始")
        _t34_assert_breadcrumb(frame, "a·初始", "图库总览")
        initial_h1 = _t34_h1(frame)
        check(initial_h1 == "AI 角色参考库", "[T34] a 初始 h1 为『AI 角色参考库』",
              f"actual={initial_h1!r}")
        _t34_collect_inner_errors(frame, inner_errors)
        page.screenshot(path=str(shots_dir / "t34_initial.png"))

        section("T34-b 依次点击 iframe 内侧栏六个页签（每次断言四项仍为 0）")
        for label, slug, path, h1, crumb in T34_TABS:
            _t34_click_tab(page, frame, label, slug, path, h1, crumb, "b·8766",
                           shots_dir, inner_errors)

        section("T34-b+ 从 ComfyUI 连接回到图库总览（h1 必须变化）")
        _t34_click_tab(page, frame, "图库总览", "home_back", "/ref-web/",
                       "AI 角色参考库", "图库总览", "b+·8766", shots_dir, inner_errors)

        outer_injected = _t32_outer_injected_errors(page)
        check(not errors and not inner_errors and not outer_injected,
              "[T34] b 页签点击全流程 console/pageerror 为 0",
              f"page={errors[:2]} outer={outer_injected[:2]} inner={inner_errors[:2]}")
    except Exception as exc:
        check(False, "[T34] 页签回归专项执行异常", f"{type(exc).__name__}: {exc}")
        try:
            page.screenshot(path=str(shots_dir / "t34_tabs_error.png"))
        except Exception:
            pass
    finally:
        ctx.close()

    _t34_top_embedded(browser, shots_dir)
    _t34_deep_link_poses(browser, shots_dir)
    _t34_narrow(browser, shots_dir)


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

        if NAV_ONLY:
            observe("T3_E2E_ONLY=nav：跑顶栏合并式、跨端无感切换与统一入口专项",
                    "跳过阶段一/二/三其余检查与阶段四 TestClient")
        else:
            # 阶段四（T13）：后端 recipes 契约用 TestClient 独立验证（与 8766 实例无关）。
            check_phase4_recipe_testclient()

            # 阶段二：断网等价探针需要重启临时实例（只有脚本自己拉起的实例才可重启）
            if P4_ONLY:
                observe("T3_E2E_ONLY=phase4：跳过阶段一/二/三检查",
                        "仅执行静态检查、dist 产物检查、阶段四 TestClient 与 Playwright")
            elif proc is not None:
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

            if not P4_ONLY:
                section("阶段二 HTTP 契约检查（C-REMOTE-CACHE@1 / C-REF-ITEM-DTO@2 / C-REF-RECIPES@2）")
                check_phase2_dto()
                check_phase2_image_cache()
                check_phase2_recipes()
                check_phase2_cache_location()

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            if NAV_ONLY:
                check_nav_merge(browser, shots_dir)
                check_embed_nav(browser, shots_dir)
                check_unified_entry(browser, shots_dir)
                check_tab_nav_regression(browser, shots_dir)
                check_live_8656_tab_nav(browser, shots_dir)
            else:
                if not P4_ONLY:
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

                # 阶段四（T13）关卡：真实提交 -> 轮询 -> 结果图 -> 任务中心。
                phase4_state = check_phase4_real_submit(browser, shots_dir)
                check_phase4_mock_result(browser, shots_dir, phase4_state)
                check_phase4_failure_branch(browser, shots_dir, phase4_state)
                check_phase4_upload_slot(browser, shots_dir)
                check_phase4_ui_contract(browser, shots_dir)

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