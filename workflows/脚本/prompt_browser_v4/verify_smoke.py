"""prompt_browser_v4 改动后冒烟测试（彻底闭环验证）。

不依赖外部库：用 stdlib 起一个临时端口的 uvicorn 实例，
真实打 HTTP 接口，捕获服务端运行日志里的报错（含启动崩溃）。

用法:
    python verify_smoke.py            # 默认端口 8765
    PORT=8770 python verify_smoke.py  # 自定义端口

覆盖的端点（含之前漏测的 /api/history/html，即画廊实际渲染的 HTML 片段）：
    - /api/history/facets          方向分面计数
    - /api/history?orientation=... 按方向筛选
    - /api/history/html?...        画廊 HTML 片段（曾因 category_id 缺失 500）
    - /static/*.js                 前端静态资源

- 启动前先清理占用该端口的残留实例，避免结果混淆
- 等待 "Application startup complete" 而非仅看 /docs，确保路由已注册
- 结束兜底释放端口
"""
import subprocess
import sys
import time
import os
import json
import urllib.request
import urllib.parse
import urllib.error

V4 = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8765"))
BASE = f"http://127.0.0.1:{PORT}"
LOG_PATH = os.path.join(V4, "_smoke_server.log")


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


def _get(url, timeout=10):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
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
    bad = [l.strip() for l in txt.splitlines()
           if "Traceback" in l or "ERROR" in l or "Error" in l]
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


def main():
    _kill_port(PORT)
    time.sleep(1)

    env = dict(os.environ)
    env["PORT"] = str(PORT)
    env["HOST"] = "127.0.0.1"

    with open(LOG_PATH, "w", encoding="utf-8") as logf:
        proc = subprocess.Popen(
            [sys.executable, "-u", "-m", "uvicorn", "main:app",
             "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "info"],
            cwd=V4, env=env, stdout=logf, stderr=subprocess.STDOUT,
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
                return _finish(proc)

            checks = []
            code, body = _get(BASE + "/api/history/facets")
            try:
                data = json.loads(body)
                o = data.get("orientation")
            except Exception as e:
                o = "PARSE_ERR:" + repr(e)
            checks.append(("facets.orientation", code, o))

            for label in ("竖图", "横图", "方图", "未记录"):
                q = urllib.parse.quote(label)
                code, body = _get(BASE + f"/api/history?orientation={q}")
                try:
                    total = json.loads(body).get("total")
                except Exception:
                    total = "PARSE_ERR"
                checks.append((f"list orientation={label}", code, total))

            # 画廊实际渲染的 HTML 片段（曾因 category_id 缺失而 500）
            code, body = _get(
                BASE + "/api/history/html?page=1&page_size=50&sort=newest"
                "&favorite=&search=&category_id=&tag_ids=&source=&date=&model="
            )
            html_ok = (code == 200 and b"Internal Server Error" not in body
                       and b"Traceback" not in body)
            checks.append(("history_html(page=1)", code,
                           f"len={len(body)}" if html_ok else "BODY_ERROR"))

            # 历史同步（曾因直接调用 list_history 未传全参数、Query 默认值变 FieldInfo 而 500）
            code, body = _get(BASE + "/api/history_sync?page_size=50")
            try:
                sync_total = json.loads(body).get("total")
            except Exception:
                sync_total = "PARSE_ERR"
            checks.append(("history_sync(page_size=50)", code, sync_total))

            for f in ("/static/gallery.js", "/static/history.js"):
                code, _ = _get(BASE + f)
                checks.append((f"serve {f}", code, ""))

            print("RESULT: checks")
            for name, code, val in checks:
                flag = "OK" if code == 200 else "FAIL"
                print(f"  [{flag}] {name} -> HTTP {code} | {val}")
        finally:
            _finish(proc)


if __name__ == "__main__":
    main()
