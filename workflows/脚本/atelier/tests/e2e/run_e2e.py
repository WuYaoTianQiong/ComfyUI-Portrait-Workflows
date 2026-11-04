"""前端端到端回归（Playwright + 真实后端 + 数据库副本）。

为什么要有这一层：vitest 只能测纯逻辑与组件，测不到"静态资源 404 了没、
接口路径拼错没、页面整体白屏没、路由挂载顺序对不对"。这些恰恰是重构期
最常翻车的地方（历史事故：/api/images/html 的函数体引用了未传参数 → 500；
直接访问 /gallery 被踢回提示词页）。

跑法：
    python tests/e2e/run_e2e.py
退出码 0 = 全通过（含"环境不具备条件而跳过"）。

安全性：跑在**生产库副本** + 临时端口上，不碰线上数据、不碰 8656。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

V4 = Path(__file__).resolve().parents[2]
PORT = int(os.environ.get("E2E_PORT", "8766"))
BASE = f"http://127.0.0.1:{PORT}"
LOG_PATH = V4 / "_e2e_server.log"

_results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    _results.append((bool(ok), name, detail))
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""))
    return bool(ok)


def kill_port(port: int) -> None:
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            if f":{port} " in line and "LISTENING" in line:
                pid = line.split()[-1]
                subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, timeout=10)
    except Exception:
        pass


def prepare_env(env: dict) -> str:
    """用生产库副本起服务 —— E2E 需要真实数据量（11 张图 / 178 标签 / 331 提示词）。"""
    # 脚本在 tests/e2e/ 下跑，要手动把项目根加进 sys.path 才能 import config
    if str(V4) not in sys.path:
        sys.path.insert(0, str(V4))
    from app.config import settings

    tmp = tempfile.mkdtemp(prefix="atelier_e2e_")
    db_copy = os.path.join(tmp, "e2e.db")
    shutil.copy2(settings.db_path, db_copy)
    for suffix in ("-wal", "-shm"):
        src = str(settings.db_path) + suffix
        if os.path.exists(src):
            shutil.copy2(src, db_copy + suffix)
    env["ATELIER_DB_PATH"] = db_copy
    env["ATELIER_THUMBNAIL_DIR"] = os.path.join(tmp, "thumbs")
    env["ATELIER_NO_BROWSER"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return db_copy


def wait_ready(proc) -> bool:
    for _ in range(60):
        time.sleep(0.5)
        if proc.poll() is not None:
            return False
        try:
            txt = LOG_PATH.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if "Application startup complete" in txt:
            return True
        if "Traceback" in txt:
            return False
    return False


def api(path: str):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read())


def run_browser_checks() -> None:
    from playwright.sync_api import sync_playwright

    errors: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 950})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on(
            "console",
            lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None,
        )

        page.goto(BASE + "/", wait_until="domcontentloaded")
        page.wait_for_selector(".card", timeout=25000)
        page.wait_for_timeout(1200)

        check(page.title() == "画室 · Atelier", "根路径是新前端", f"title={page.title()!r}")

        # ---- 画廊 ----
        cards = page.locator(".card").count()
        expected = api("/api/images?page_size=200")["total"]
        check(cards > 0 and cards <= expected, "画廊渲染出卡片", f"{cards} 张 / 共 {expected}")

        tags = page.locator(".sidebar .tag")
        if tags.count():
            check(True, "标签云有内容", f"{tags.count()} 个")
            tags.first.click()
            page.wait_for_timeout(1200)
            filtered = page.locator(".card").count()
            check(filtered != cards or expected == cards, "点击标签后结果集变化", f"{cards} → {filtered}")
        else:
            # 标签云只展示「确实有图片」的标签。生产库可能一张带标签的图都没有，
            # 这是用户数据状态而不是代码回归；此时验证空状态正常渲染，
            # 避免门禁被数据绑架（旧断言固定要求 >0 个，库一旦清标签就永久 FAIL）。
            empty_text = page.locator(".sidebar .cloud").inner_text().strip()
            check("暂无带图片的标签" in empty_text, "标签云空状态", empty_text[:40] or "空")

        # ---- 提示词 ----
        page.click("button:has-text('提示词')")
        page.wait_for_selector(".row", timeout=15000)
        page.wait_for_timeout(1000)
        rows = page.locator(".row").count()
        check(rows > 0, "提示词列表有内容", f"{rows} 条")
        page.locator(".row").first.click()
        page.wait_for_timeout(900)
        check(page.locator(".name-input").count() == 1, "点条目后右侧详情加载")

        # ---- 组合器 ----
        page.click("button:has-text('组合器')")
        page.wait_for_selector(".reel", timeout=20000)
        page.wait_for_timeout(1200)
        groups = page.locator(".reel").count()
        check(groups == 8, "组合器碎片分 8 类", f"{groups} 组")
        frags = page.locator(".reel-body .card")
        if frags.count():
            frags.first.click()
            page.wait_for_timeout(400)
            check(page.locator(".card.on").count() == 1, "点碎片能填进画布")
            page.click("button:has-text('结果')")
            page.wait_for_selector(".modal-panel .full", timeout=15000)
            check(
                "【" in page.inner_text(".modal-panel .full"),
                "结果中心画布页是【类型】格式",
            )
            page.click(".modal-head button:has-text('关闭')")
            page.wait_for_timeout(300)

        # ---- 图像编辑（P2c 起路径是 /editor，视图 EditorView）----
        # 入口在顶栏「图像编辑」；旧版脚本点的"批量换脸"按钮已被页面重构移除
        page.click("button:has-text('图像编辑')")
        page.wait_for_selector(".picker", timeout=15000)
        page.wait_for_timeout(1200)
        check(page.url.endswith("/editor"), "图像编辑页路由是 /editor", page.url)
        check(page.locator(".picker").count() == 2, "换脸页有主图/参考图两个选择器")
        cells = page.locator(".picker .cell")
        check(cells.count() > 0, "换脸页能列出生图", f"{cells.count()} 张")

        # ---- 参考图库（/reference：Vue 用 iframe 承载上游 React 台 /ref-web）----
        # T23 起顶栏入口由 `<a :href="referenceWebUrl">` 改为 `<button @click="go('reference')">`，
        # `/reference` 由 ReferenceEmbedView 用 iframe 承载 `/ref-web/?embedded=1`。
        # 旧断言（a 标签 + href 指向 /ref-web）随入口改造失效，属**脚本过期**而非回归：
        # 改为验收按钮入口、前端路由、iframe 地址与内嵌内容加载。
        # iframe 内是否隐藏自身导航属 T25（gallery-web 重建）验收项，此处不断言。
        entry = page.locator("button:has-text('参考图库')")
        # 入口由 /api/system/status 的 reference_web_url 驱动，而该接口要先等一次探活
        # （离线实测 ~3s，另有 is_online 的 15s 结果缓存）；e2e 跑到这里可能还没拿到，
        # 必须显式等待而不是靠时序碰运气（修缓存前该接口 8.2s，入口 ~8s 后才出现）。
        try:
            entry.first.wait_for(state="visible", timeout=25000)
        except Exception:
            pass
        check(entry.count() == 1, "顶栏有参考图库入口", f"{entry.count()} 个")

        errors_before_ref = len(errors)
        if entry.count():
            entry.first.click()
        try:
            page.wait_for_selector(".reference-embed iframe", timeout=25000)
        except Exception:
            pass
        page.wait_for_timeout(800)

        # 路由必须是 Vue 的 /reference，不能停在 /gallery，也不能整页跳去 /ref-web。
        ref_path = urlparse(page.url).path.rstrip("/")
        check(ref_path == "/reference", "参考图库入口路由是 /reference", page.url)

        ref_iframe = page.locator(".reference-embed iframe")
        check(ref_iframe.count() == 1, "参考图库页用 iframe 承载", f"{ref_iframe.count()} 个")
        iframe_src = ref_iframe.first.get_attribute("src") if ref_iframe.count() else ""
        # 两个条件缺一不可：指向上游台 + embedded=1（gallery-web 据此隐藏自身导航）。
        check(
            "/ref-web" in (iframe_src or "") and "embedded=1" in (iframe_src or ""),
            "iframe src 指向 /ref-web 且带 embedded=1",
            iframe_src or "无 src",
        )

        # 内嵌内容加载：等 React 挂载（#root 出现子节点）后再取正文，确认不是白屏。
        frame = page.frame_locator(".reference-embed iframe")
        try:
            frame.locator("#root > *").first.wait_for(state="attached", timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(1200)
        frame_body = ""
        try:
            frame_body = frame.locator("body").inner_text(timeout=10000)
        except Exception:
            pass
        check(
            "参考图库" in frame_body,
            "iframe 内参考图库内容已加载",
            frame_body.strip()[:60] or "空",
        )
        page.goto(BASE + "/ref-web/poses", wait_until="domcontentloaded")
        # 阶段三起图库图片统一走后端端点（kind=thumb|image|depth_thumb|depth），
        # 不再有 /thumbs/ 静态路径；选择器必须按端点匹配。
        page.wait_for_selector('img[src*="/api/reference/items/pose/"]', timeout=30000)
        page.wait_for_timeout(1200)
        check(page.url.endswith("/ref-web/poses"), "深链接 /ref-web/poses 不 404", page.url)
        check("动作姿势库" in page.inner_text("body"), "参考图库 poses 页渲染出页头")

        thumbs = page.locator('img[src*="/api/reference/items/pose/"]')
        check(thumbs.count() > 0, "参考图库网格渲染出姿势卡片", f"{thumbs.count()} 张缩略图")
        check(
            page.locator("button:has-text('全部 (')").count() >= 1,
            "体系药丸有「全部 (N)」",
        )

        decoded = page.evaluate(
            """() => Array.from(document.querySelectorAll('img[src*="/api/reference/items/pose/"]'))
                .slice(0, 5)
                .filter((i) => i.complete && i.naturalWidth > 0).length"""
        )
        check(decoded >= 5, "首屏缩略图真实解码", f"{decoded}/5 张 naturalWidth>0")

        page.locator("button:has-text('深度图 (Depth)')").first.click()
        page.wait_for_timeout(1500)
        depth_thumbs = page.locator('img[src*="kind=depth_thumb"]').count()
        check(depth_thumbs > 0, "切深度模式后缩略图换成 depth 版", f"{depth_thumbs} 张")
        page.locator("button:has-text('素体白模')").first.click()
        page.wait_for_timeout(600)

        libs = api("/api/reference/libraries")
        check(
            bool(libs.get("libraries")),
            "/api/reference/* 后端契约仍可用",
            f"{len(libs.get('libraries') or [])} 库",
        )

        page.goto(BASE + "/ref-web/costumes", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        check(page.url.endswith("/ref-web/costumes"), "深链接 /ref-web/costumes 不 404", page.url)

        ref_errors = errors[errors_before_ref:]
        check(not ref_errors, "参考图库无 console 错误", "; ".join(ref_errors[:3]))

        # 回到 atelier 自己的 Vue 应用，后面几段仍用顶栏导航
        page.goto(BASE + "/gallery", wait_until="domcontentloaded")
        page.wait_for_selector(".card", timeout=20000)

        # ---- 批量超分（/upscale）----
        page.click("button:has-text('批量超分')")
        page.wait_for_selector(".upscale", timeout=15000)
        page.wait_for_timeout(800)
        check(page.url.endswith("/upscale"), "批量超分页路由是 /upscale", page.url)
        check(page.locator(".upscale .picker").count() == 1, "批量超分页只有一列图片选择器")
        check(
            page.locator(".upscale .panel select").count() >= 1,
            "批量超分页有工作流下拉",
        )

        # ---- 分类与标签（P2c 由「管理」改名，路径 /taxonomy）----
        page.click("button:has-text('分类与标签')")
        page.wait_for_selector(".taxonomy", timeout=15000)
        page.wait_for_timeout(1000)
        check(page.url.endswith("/taxonomy"), "分类与标签页路由是 /taxonomy", page.url)
        check(page.locator(".taxonomy .row").count() > 0, "分类与标签页列出分类")

        # ---- 任务 ----
        page.click("button:has-text('任务')")
        page.wait_for_selector(".job", timeout=15000)
        page.wait_for_timeout(1000)
        check(page.locator(".job").count() > 0, "任务中心有历史任务")

        # ---- 统计 ----
        page.click("button:has-text('统计')")
        page.wait_for_timeout(1200)
        check(page.url.endswith("/stats"), "统计页路由是 /stats", page.url)

        # ---- 顶栏不再有「设计」，设计预览只在 /dev/design ----
        check(
            page.locator("nav.tabs button:has-text('设计')").count() == 0,
            "顶栏已移除设计入口",
        )
        page.goto(BASE + "/dev/design", wait_until="domcontentloaded")
        page.wait_for_selector(".design", timeout=15000)
        check(page.locator(".design").count() == 1, "/dev/design 可直接访问")

        # ---- 旧路径 redirect（改名后书签不能 404 回画廊）----
        page.goto(BASE + "/faceswap", wait_until="domcontentloaded")
        page.wait_for_selector(".picker", timeout=15000)
        check(page.url.endswith("/editor"), "旧 /faceswap 重定向到 /editor", page.url)
        page.goto(BASE + "/manage", wait_until="domcontentloaded")
        page.wait_for_selector(".taxonomy", timeout=15000)
        check(page.url.endswith("/taxonomy"), "旧 /manage 重定向到 /taxonomy", page.url)
        page.goto(BASE + "/design", wait_until="domcontentloaded")
        page.wait_for_selector(".design", timeout=15000)
        check(page.url.endswith("/dev/design"), "旧 /design 重定向到 /dev/design", page.url)

        page.screenshot(path=str(V4 / "_e2e_shot.png"))
        browser.close()

    check(not errors, "全程无 JS 错误", "; ".join(errors[:3]))


def main() -> int:
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("SKIP: 未安装 playwright，跳过前端 E2E")
        return 0

    kill_port(PORT)
    time.sleep(1)

    env = dict(os.environ)
    env["PORT"] = str(PORT)
    env["HOST"] = "127.0.0.1"
    db_copy = prepare_env(env)
    print(f"E2E: DB 副本 {db_copy}，端口 {PORT}")

    with open(LOG_PATH, "w", encoding="utf-8") as logf:
        proc = subprocess.Popen(
            [sys.executable, "-u", "-m", "uvicorn", "main:app",
             "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "info"],
            cwd=str(V4), env=env, stdout=logf, stderr=subprocess.STDOUT,
        )
        try:
            if not wait_ready(proc):
                print("FAIL: 服务未就绪")
                print(LOG_PATH.read_text(encoding="utf-8", errors="replace")[-2000:])
                return 1
            run_browser_checks()
        except Exception as exc:
            print(f"FAIL: E2E 异常 {type(exc).__name__}: {exc}")
            return 1
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
            kill_port(PORT)

    failed = [r for r in _results if not r[0]]
    print(f"\nRESULT: {'PASS' if not failed else 'FAIL'}"
          f"（{len(_results) - len(failed)} 通过 / {len(failed)} 失败）")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
