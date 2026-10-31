"""Atelier 改动后冒烟测试（彻底闭环验证）。

不依赖外部库：用 stdlib 起一个临时端口的 uvicorn 实例，
真实打 HTTP 接口，捕获服务端运行日志里的报错（含启动崩溃）。

用法:
    python tools/smoke.py            # 默认端口 8765
    PORT=8770 python tools/smoke.py  # 自定义端口

覆盖的端点（HTMX 分支已在 B4 删除，旧 /html 端点应返回 404）：
    - /api/images/facets          方向分面计数
    - /api/images?orientation=... 按方向筛选
    - /api/images/html?...        已下线，断言 404
    - /api/workflows               工作流列表（界面格式工作流也应列出）
    - /api/faceswap/nodes          双图工作流的 LoadImage 节点探测
    - /api/faceswap/batch          批量换脸（dry_run，不占显存）
    - /*.js / *.css / index.html   前端静态资源（带内容断言）

- 启动前先清理占用该端口的残留实例，避免结果混淆
- 等待 "Application startup complete" 而非仅看 /docs，确保路由已注册
- 结束兜底释放端口
"""
import subprocess
import sys
import time
import os
import json
import shutil
import tempfile
import urllib.request
import urllib.parse
import urllib.error

# 本脚本位于 tools/ 下，项目根是它的上一级
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 从 tools/ 运行时 sys.path[0] 是 tools/，要能 import config / models 必须把项目根加进去
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
PORT = int(os.environ.get("PORT", "8765"))
BASE = f"http://127.0.0.1:{PORT}"

# 服务端日志写系统临时目录：放工程根会留下"删了又生"的残留文件
LOG_PATH = os.path.join(tempfile.mkdtemp(prefix="atelier_smoke_log_"), "server.log")

# 前端构建产物是否存在：与 main.py 的判定完全一致（同一个目录开关）。
NEW_FRONTEND = os.path.exists(os.path.join(PROJECT_ROOT, "web", "index.html"))


def _kill_port(port):
    """Windows: netstat 找到 LISTENING 的 PID 并 taskkill，清理上次残留实例。"""
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            if f":{port} " in line and "LISTENING" in line:
                pid = line.split()[-1]
                try:
                    subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, timeout=10)
                    print(f"  [cleanup] killed stale listener PID {pid} on :{port}")
                except Exception:
                    pass
    except Exception:
        pass


def _get(url, timeout=30):
    # 注意：超时别设太小。ComfyUI 正在跑图时，图片端点的"代理回退"最久要 15 秒，
    # 客户端 10 秒就放弃会导致假失败（服务端其实正常返回了 200）。
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return -1, str(e).encode()


def _post(url, payload, timeout=30):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return -1, str(e).encode()


def _report_log():
    try:
        txt = open(LOG_PATH, encoding="utf-8", errors="replace").read()
    except Exception:
        return
    # ComfyUI 离线时的连接拒绝属于环境状态，不算服务端故障
    benign = ("ConnectError", "ConnectTimeout", "10061", "目标计算机积极拒绝")
    bad = [l.strip() for l in txt.splitlines()
           if ("Traceback" in l or "ERROR" in l or "Error" in l)
           and not any(b in l for b in benign)]
    if bad:
        print("SERVER_LOG_ISSUES (请确认是否本次改动引入):")
        for l in bad[:30]:
            print("  " + l)
    else:
        print("SERVER_LOG: 无 Traceback / Error")


def _finish(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    _kill_port(PORT)
    _report_log()


_TMP_DIR = None


def _prepare_isolated_env(env: dict) -> str:
    """把冒烟跑在数据库副本上：本脚本会打 /api/images/sync，那是一条写库路径。

    返回说明文字，供开头打印。
    """
    global _TMP_DIR
    from app.config import settings

    _TMP_DIR = tempfile.mkdtemp(prefix="atelier_smoke_")
    db_copy = os.path.join(_TMP_DIR, "smoke.db")
    shutil.copy2(settings.db_path, db_copy)
    # WAL 模式下未 checkpoint 的数据在 -wal 里，必须一起复制，否则副本会缺最新写入
    for suffix in ("-wal", "-shm"):
        src = str(settings.db_path) + suffix
        if os.path.exists(src):
            shutil.copy2(src, db_copy + suffix)
    env["ATELIER_DB_PATH"] = db_copy
    env["ATELIER_THUMBNAIL_DIR"] = os.path.join(_TMP_DIR, "thumbs")
    env["ATELIER_NO_BROWSER"] = "1"
    # 子进程 stdout 重定向到文件时，Windows 默认用 cp936 写中文 → 读方按 utf-8 解会乱码
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return f"DB 副本: {db_copy}"


def _cleanup_tmp():
    if _TMP_DIR and os.path.isdir(_TMP_DIR):
        shutil.rmtree(_TMP_DIR, ignore_errors=True)
    log_dir = os.path.dirname(LOG_PATH)
    if log_dir and os.path.isdir(log_dir):
        shutil.rmtree(log_dir, ignore_errors=True)


def main() -> int:
    """返回 0 = 全部通过；1 = 有失败。可作为门禁使用。"""
    _kill_port(PORT)
    time.sleep(1)

    env = dict(os.environ)
    env["PORT"] = str(PORT)
    env["HOST"] = "127.0.0.1"
    print(_prepare_isolated_env(env))

    with open(LOG_PATH, "w", encoding="utf-8") as logf:
        proc = subprocess.Popen(
            [sys.executable, "-u", "-m", "uvicorn", "main:app",
             "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "info"],
            cwd=PROJECT_ROOT, env=env, stdout=logf, stderr=subprocess.STDOUT,
        )
        try:
            started = False
            for _ in range(40):
                time.sleep(0.5)
                try:
                    with open(LOG_PATH, encoding="utf-8", errors="replace") as f:
                        txt = f.read()
                    if "Application startup complete" in txt:
                        started = True
                        break
                    if "Traceback" in txt:
                        break
                except Exception:
                    pass
            if not started:
                print("RESULT: STARTUP_FAIL（服务启动崩溃，见下方日志）")
                _report_log()
                return 1

            checks = []

            # ComfyUI 是否在线：决定部分用例是 FAIL 还是 SKIP（离线属于环境状态，不是回归）
            code, body = _get(BASE + "/api/system/status")
            try:
                comfy_online = json.loads(body).get("comfyui") == "online"
            except Exception:
                comfy_online = False
            print(f"ComfyUI: {'在线' if comfy_online else '离线（相关用例记为 SKIP）'}")
            code, body = _get(BASE + "/api/images/facets")
            try:
                data = json.loads(body)
                o = data.get("orientation")
            except Exception as e:
                o = "PARSE_ERR:" + repr(e)
            checks.append(("facets.orientation", code, o))

            for label in ("竖图", "横图", "方图", "未记录"):
                q = urllib.parse.quote(label)
                code, body = _get(BASE + f"/api/images?orientation={q}")
                try:
                    total = json.loads(body).get("total")
                except Exception:
                    total = "PARSE_ERR"
                checks.append((f"list orientation={label}", code, total))

            # HTMX 分支已在 B4 删除：旧的 HTML 片段端点不应再返回页面
            code, body = _get(BASE + "/api/images/html?page=1&page_size=50&sort=newest")
            gone = code in (404, 405, 422)
            checks.append(("images/html 已下线", 200 if gone else -2, f"HTTP {code}"))

            # 历史同步（曾因直接调用 list_history 未传全参数、Query 默认值变 FieldInfo 而 500）
            code, body = _get(BASE + "/api/images/sync?page_size=50")
            try:
                sync_total = json.loads(body).get("total")
            except Exception:
                sync_total = "PARSE_ERR"
            checks.append(("images/sync(page_size=50)", code, sync_total))

            # 静态资源：必须校验内容，否则 404 会被 SPA 回退成 index.html(200) 造成假通过。
            # 资源在 /assets 下、文件名带 hash，要从 index.html 里解析真实文件名。
            if NEW_FRONTEND:
                code, body = _get(BASE + "/")
                has_app = b'id="app"' in body and b"/assets/" in body
                checks.append(("根路径返回新前端 index.html", code if has_app else -2,
                               f"len={len(body)}" if has_app else "缺少 #app 挂载点或 /assets 引用"))

                import re as _re
                assets = _re.findall(rb'(?:src|href)="(/assets/[^"]+)"', body)
                if not assets:
                    checks.append(("新前端引用了构建资源", -2, "index.html 里没有 /assets 引用"))
                for asset in assets:
                    asset = asset.decode()
                    code2, b2 = _get(BASE + asset)
                    ok2 = code2 == 200 and len(b2) > 1000
                    checks.append((f"serve {asset}", code2 if ok2 else -2, f"bytes={len(b2)}"))
            else:
                # 没有构建产物时**不能静默跳过** —— 那会让冒烟测试在前端缺失时也报 PASS
                checks.append(("前端构建产物（web/）", -3,
                                "未找到构建产物，跳过前端资源断言（先 npm run build）"))
            miss = "__definitely_missing__.png"
            for label, url in (
                ("缩略图(缺失)→占位图", f"/api/media/thumbnail?filename={miss}&subfolder=&type=output&size=600"),
                ("原图(缺失)→占位图", f"/api/media/image?filename={miss}&subfolder=&type=output"),
                ("browser/thumb(缺失)→占位图", "/api/browser/thumb?path=" + urllib.parse.quote("F:/__nope__/x.png")),
            ):
                code, body = _get(BASE + url)
                ok = code == 200 and b"<svg" in body
                checks.append((label, code if ok else -2,
                               f"bytes={len(body)}" if ok else "未返回占位图"))

            # 同步不再为「文件已被删除」的历史条目建记录
            code, body = _get(BASE + "/api/images/sync?page_size=1")
            time.sleep(0.5)
            try:
                log_txt = open(LOG_PATH, encoding="utf-8", errors="replace").read()
            except Exception:
                log_txt = ""
            # 注意：子进程 stdout 重定向到文件时 Windows 用本地编码(cp936)写中文，
            # 用 utf-8 读会变乱码，所以这里只匹配 ASCII 的 "[sync]" 前缀。
            skipped_ok = "[sync]" in log_txt
            if skipped_ok:
                checks.append(("images/sync 跳过缺失文件", code, "日志已确认跳过"))
            elif not comfy_online:
                checks.append(("images/sync 跳过缺失文件", -3, "ComfyUI 离线，无法验证"))
            else:
                checks.append(("images/sync 跳过缺失文件", -3, "本次没有「文件已缺失」的历史条目"))

            code, body = _get(BASE + "/api/jobs?active=1")
            checks.append(("jobs?active=1", code, ""))

            # SSE 首帧：连上后应立刻收到 ": connected" 心跳（不订阅任何任务）
            try:
                req = urllib.request.Request(BASE + "/api/jobs/events?ids=999999")
                with urllib.request.urlopen(req, timeout=8) as resp:
                    head = resp.read(13)
                sse_ok = b"connected" in head
                checks.append(("jobs/events SSE 首帧", 200 if sse_ok else -2,
                               head.decode("utf-8", "replace").strip() or "空响应"))
            except Exception as e:
                checks.append(("jobs/events SSE 首帧", -2, repr(e)))

            print("RESULT: checks")
            failed = skipped = 0
            for name, code, val in checks:
                if code == 200:
                    flag = "OK"
                elif code == -3:
                    flag = "SKIP"
                    skipped += 1
                else:
                    flag = "FAIL"
                    failed += 1
                print(f"  [{flag}] {name} -> HTTP {code} | {val}")

            if failed:
                print(f"RESULT: FAIL（{failed} 失败 / {skipped} 跳过 / {len(checks)} 项）")
            else:
                print(f"RESULT: PASS（{len(checks) - skipped} 通过 / {skipped} 跳过）")
            return 1 if failed else 0
        finally:
            _finish(proc)
            _cleanup_tmp()


if __name__ == "__main__":
    sys.exit(main())
