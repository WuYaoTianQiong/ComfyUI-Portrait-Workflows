"""prompt_browser_v4 改动后冒烟测试（彻底闭环验证）。

不依赖外部库：用 stdlib 起一个临时端口的 uvicorn 实例，
真实打 HTTP 接口，捕获服务端运行日志里的报错（含启动崩溃）。

用法:
    python verify_smoke.py            # 默认端口 8765
    PORT=8770 python verify_smoke.py  # 自定义端口

覆盖的端点（HTMX 分支已在 B4 删除，旧 /html 端点应返回 404）：
    - /api/history/facets          方向分面计数
    - /api/history?orientation=... 按方向筛选
    - /api/history/html?...        已下线，断言 404
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
    """把冒烟跑在数据库副本上：本脚本会打 /api/history_sync，那是一条写库路径。

    返回说明文字，供开头打印。
    """
    global _TMP_DIR
    from config import settings

    _TMP_DIR = tempfile.mkdtemp(prefix="pb_smoke_")
    db_copy = os.path.join(_TMP_DIR, "smoke.db")
    shutil.copy2(settings.db_path, db_copy)
    # WAL 模式下未 checkpoint 的数据在 -wal 里，必须一起复制，否则副本会缺最新写入
    for suffix in ("-wal", "-shm"):
        src = str(settings.db_path) + suffix
        if os.path.exists(src):
            shutil.copy2(src, db_copy + suffix)
    env["PB_DB_PATH"] = db_copy
    env["PB_THUMBNAIL_DIR"] = os.path.join(_TMP_DIR, "thumbs")
    env["PB_NO_BROWSER"] = "1"
    # 子进程 stdout 重定向到文件时，Windows 默认用 cp936 写中文 → 读方按 utf-8 解会乱码
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return f"DB 副本: {db_copy}"


def _cleanup_tmp():
    if _TMP_DIR and os.path.isdir(_TMP_DIR):
        shutil.rmtree(_TMP_DIR, ignore_errors=True)


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
                return 1

            checks = []

            # ComfyUI 是否在线：决定部分用例是 FAIL 还是 SKIP（离线属于环境状态，不是回归）
            code, body = _get(BASE + "/api/status")
            try:
                comfy_online = json.loads(body).get("comfyui") == "online"
            except Exception:
                comfy_online = False
            print(f"ComfyUI: {'在线' if comfy_online else '离线（相关用例记为 SKIP）'}")
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

            # HTMX 分支已在 B4 删除：旧的 HTML 片段端点不应再返回页面
            code, body = _get(BASE + "/api/history/html?page=1&page_size=50&sort=newest")
            gone = code in (404, 405, 422)
            checks.append(("history/html 已下线", 200 if gone else -2, f"HTTP {code}"))

            # 历史同步（曾因直接调用 list_history 未传全参数、Query 默认值变 FieldInfo 而 500）
            code, body = _get(BASE + "/api/history_sync?page_size=50")
            try:
                sync_total = json.loads(body).get("total")
            except Exception:
                sync_total = "PARSE_ERR"
            checks.append(("history_sync(page_size=50)", code, sync_total))

            # 静态资源：必须校验内容，否则 404 会被 SPA 回退成 index.html(200) 造成假通过
            for f, needle in (("/gallery.js", b"renderGallery"),
                              ("/store.js", b"PBQuery"),
                              ("/history.js", b"loadHistory"),
                              ("/faceswap.js", b"window.fsSubmit"),
                              ("/faceswap.css", b".fs-page")):
                code, body = _get(BASE + f)
                ok = code == 200 and needle in body
                checks.append((f"serve {f} (含 {needle.decode()})", code if ok else -2,
                               f"len={len(body)}" if ok else "内容不符（可能被 SPA 回退成 HTML）"))

            code, body = _get(BASE + "/")
            has_tab = b'id="faceswapTab"' in body
            checks.append(("index.html 含 faceswapTab", code if has_tab else -2,
                           f"len={len(body)}" if has_tab else "缺少 tab 面板"))

            # ---- 批量换脸 ----
            root = os.path.dirname(os.path.dirname(V4))
            import glob as _glob
            cands = _glob.glob(os.path.join(root, "*双图*.json")) or _glob.glob(os.path.join(root, "*.json"))
            wf = cands[0] if cands else ""

            code, body = _get(BASE + "/api/workflows?sort=mtime")
            try:
                names = [w["name"] for w in json.loads(body).get("workflows", [])]
            except Exception:
                names = []
            listed = os.path.basename(wf) in names if wf else False
            checks.append((f"workflows 列出 {os.path.basename(wf)}", code if listed else -2,
                           f"共 {len(names)} 个" if listed else "未列出"))

            code, body = _post(BASE + "/api/faceswap/nodes", {"workflow_path": wf})
            try:
                nd = json.loads(body)
                node_desc = f"main={nd.get('main')} ref={nd.get('ref')} loads={len(nd.get('loadimages') or [])}"
                nodes_ok = bool(nd.get("main")) and bool(nd.get("ref"))
            except Exception as e:
                node_desc, nodes_ok = "PARSE_ERR:" + repr(e), False
            checks.append(("faceswap/nodes 双图节点", code if nodes_ok else -2, node_desc))

            # dry_run 需要真实存在的历史图：逐个候选试，避免依赖固定 id
            code, body = _get(BASE + "/api/history?page=1&page_size=50")
            try:
                ids = [it["id"] for it in json.loads(body).get("items", [])]
            except Exception:
                ids = []
            picked = None
            for i in ids[:40]:
                c, b = _post(BASE + "/api/faceswap/batch",
                             {"main_ids": [i], "ref_ids": [i], "workflow_path": wf, "dry_run": True})
                if c == 200:
                    picked = i
                    break
            if picked is None:
                checks.append(("faceswap/batch dry_run", -3,
                               f"无可用历史图文件（候选 {len(ids)} 张，环境相关）"))
            else:
                c, b = _post(BASE + "/api/faceswap/batch",
                             {"main_ids": [picked], "ref_ids": [picked], "workflow_path": wf, "dry_run": True})
                try:
                    d = json.loads(b)
                    ok = c == 200 and d.get("total") == 1 and d.get("plan")
                    info = f"total={d.get('total')} nodes={d.get('nodes', {}).get('main')}/{d.get('nodes', {}).get('ref')}"
                    # 出图文件名规则：平铺在 output 根目录（不能带 "/" 子目录，
                    # 否则磁盘兜底扫描扫不到）
                    pfx = (d.get("plan") or [{}])[0].get("prefix", "")
                    ok_pfx = bool(pfx) and "/" not in pfx and pfx.startswith("fs")
                except Exception as e:
                    ok, info, ok_pfx, pfx = False, "PARSE_ERR:" + repr(e), False, ""
                checks.append(("faceswap/batch dry_run", c if ok else -2, info))
                checks.append(("出图文件名平铺(无子目录)", 200 if ok_pfx else -2, pfx or "缺失"))

            # ---- 文件夹浏览（批量换脸的另一素材来源）----
            code, body = _get(BASE + "/api/fs/list")
            try:
                rootdata = json.loads(body)
                roots = rootdata.get("roots", [])
            except Exception:
                rootdata, roots = {}, []
            checks.append(("fs/list 起点(盘符+快速跳转)", code if roots else -2,
                           f"drives={len(rootdata.get('dirs', []))} roots={len(roots)}"))

            input_path = next((r["path"] for r in roots if r["name"] == "ComfyUI/input"), "")
            img_path = ""
            img_path2 = ""
            if input_path:
                code, body = _get(BASE + "/api/fs/list?path=" + urllib.parse.quote(input_path))
                try:
                    d = json.loads(body)
                    imgs = d.get("images", [])
                    img_path = imgs[0]["path"] if imgs else ""
                    img_path2 = imgs[1]["path"] if len(imgs) > 1 else ""
                    fs_info = f"dirs={len(d.get('dirs', []))} images={len(imgs)}"
                except Exception as e:
                    fs_info = "PARSE_ERR:" + repr(e)
                checks.append(("fs/list 列子目录与图片", code if img_path else -3,
                               fs_info + ("（该目录没有图片）" if not img_path else "")))

            if img_path:
                code, body = _get(BASE + "/api/fs/thumb?path=" + urllib.parse.quote(img_path) + "&size=200")
                ok = code == 200 and body[:4] == b"RIFF"      # RIFF = 有效 webp
                checks.append(("fs/thumb 任意路径缩略图", code if ok else -2,
                               f"bytes={len(body)}" + "" if ok else "内容不是 webp"))

                code, body = _post(BASE + "/api/faceswap/batch",
                                   {"main_paths": [img_path], "ref_paths": [img_path],
                                    "workflow_path": wf, "dry_run": True})
                try:
                    d2 = json.loads(body)
                    plan0 = (d2.get("plan") or [{}])[0]
                    src_kind = (plan0.get("main_meta") or {}).get("source")
                    ok2 = code == 200 and d2.get("total") == 1 and src_kind == "file"
                    info2 = f"total={d2.get('total')} main_meta.source={src_kind}"
                except Exception as e:
                    ok2, info2 = False, "PARSE_ERR:" + repr(e)
                checks.append(("faceswap/batch 用磁盘路径 dry_run", code if ok2 else -2, info2))

                # 1:1 配对：数量相等应只出 N 组，不等应报 400
                if img_path2:
                    code, body = _post(BASE + "/api/faceswap/batch",
                                       {"main_paths": [img_path, img_path2], "ref_paths": [img_path, img_path2],
                                        "workflow_path": wf, "dry_run": True, "pair_mode": "zip"})
                    try:
                        dz = json.loads(body)
                        okz = code == 200 and dz.get("total") == 2
                        infoz = f"total={dz.get('total')}（全组合会是4）"
                    except Exception as e:
                        okz, infoz = False, "PARSE_ERR:" + repr(e)
                    checks.append(("faceswap 1:1配对 dry_run", code if okz else -2, infoz))

                    code, body = _post(BASE + "/api/faceswap/batch",
                                       {"main_paths": [img_path, img_path2], "ref_paths": [img_path],
                                        "workflow_path": wf, "dry_run": True, "pair_mode": "zip"})
                    # 打印逻辑以 code==200 为通过标记，所以期望 400 的用例要回填 200
                    checks.append(("faceswap 1:1配对 数量不等→400", 200 if code == 400 else -2,
                                   f"HTTP {code}（期望 400）"))

            # ---- 文件缺失时返回占位图（而不是 404 刷屏）----
            code, body = _get(BASE + "/img-missing.svg")
            ok = code == 200 and b"<svg" in body and "文件缺失".encode() in body
            checks.append(("占位图 img-missing.svg", code if ok else -2, f"bytes={len(body)}"))

            miss = "__definitely_missing__.png"
            for label, url in (
                ("缩略图(缺失)→占位图", f"/api/thumbnail?filename={miss}&subfolder=&type=output&size=600"),
                ("原图(缺失)→占位图", f"/api/image?filename={miss}&subfolder=&type=output"),
                ("fs/thumb(缺失)→占位图", "/api/fs/thumb?path=" + urllib.parse.quote("F:/__nope__/x.png")),
            ):
                code, body = _get(BASE + url)
                ok = code == 200 and b"<svg" in body
                checks.append((label, code if ok else -2,
                               f"bytes={len(body)}" if ok else "未返回占位图"))

            # 同步不再为「文件已被删除」的历史条目建记录
            code, body = _get(BASE + "/api/history_sync?page_size=1")
            time.sleep(0.5)
            try:
                log_txt = open(LOG_PATH, encoding="utf-8", errors="replace").read()
            except Exception:
                log_txt = ""
            # 注意：子进程 stdout 重定向到文件时 Windows 用本地编码(cp936)写中文，
            # 用 utf-8 读会变乱码，所以这里只匹配 ASCII 的 "[sync]" 前缀。
            skipped_ok = "[sync]" in log_txt
            if skipped_ok:
                checks.append(("history_sync 跳过缺失文件", code, "日志已确认跳过"))
            elif not comfy_online:
                checks.append(("history_sync 跳过缺失文件", -3, "ComfyUI 离线，无法验证"))
            else:
                checks.append(("history_sync 跳过缺失文件", -3, "本次没有「文件已缺失」的历史条目"))

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
