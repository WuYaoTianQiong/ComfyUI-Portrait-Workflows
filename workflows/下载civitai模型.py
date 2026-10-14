# -*- coding: utf-8 -*-
"""Civitai 多线程下载器（走 API token，自动换取 R2 签名直链）

用法示例：
  python 下载civitai模型.py --model-id 2382648                    # 取该模型最新「免费」版本
  python 下载civitai模型.py --model-id 2382648 --prefer int8      # 指定版本名关键字
  python 下载civitai模型.py --version-id 3116481 --threads 16     # 直接指定版本 + 线程数
  python 下载civitai模型.py --version-id 3116481 --out D:\\models  # 指定输出目录

要点：
  1. API key 从环境变量 CIVITAI_API_KEY 或就近的 .env 读取（不硬编码）。
  2. 下载端点返回 307 → R2 预签名直链（24 小时有效）。必须手动处理重定向，
     因为自动跟随会把 Authorization 头也带给 R2，导致 AWS 签名校验失败。
  3. 支持多线程 Range 分块 + 断点续传（.partN 文件），完成后校验 SHA256。
"""
import argparse
import hashlib
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

API = "https://civitai.com/api/v1"
DL = "https://civitai.com/api/download/models/%s?token=%s"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
CHUNK = 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


NO_REDIRECT = urllib.request.build_opener(NoRedirect)


def find_env(start):
    cur = start
    for _ in range(8):
        p = os.path.join(cur, ".env")
        if os.path.isfile(p):
            return p
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


def load_api_key():
    key = (os.environ.get("CIVITAI_API_KEY") or "").strip()
    if key:
        return key
    env = find_env(os.path.dirname(os.path.abspath(__file__)))
    if env:
        with open(env, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("CIVITAI_API_KEY="):
                    return line.split("=", 1)[1].strip()
    sys.exit("[错误] 未找到 CIVITAI_API_KEY（环境变量或 .env）")


def api_get(path, key):
    req = urllib.request.Request(
        API + path, headers={"Authorization": "Bearer " + key, "User-Agent": UA}
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def default_out_dir():
    """workflows/xxx.py → ComfyUI 根/models/diffusion_models"""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    return os.path.join(root, "models", "diffusion_models")


def pick_version(model_id, key, prefer):
    model = api_get("/models/%d" % model_id, key)
    versions = model.get("modelVersions") or []
    if not versions:
        sys.exit("[错误] 该模型没有版本")
    if prefer:
        for v in versions:
            if prefer.lower() in (v.get("name") or "").lower():
                return v
        sys.exit("[错误] 未找到名称包含 %r 的版本" % prefer)
    for v in versions:
        if not v.get("paidAccess"):
            return v
    sys.exit("[错误] 该模型没有免费版本（全部为付费）")


def pick_file(version, prefer):
    files = version.get("files") or []
    if not files:
        sys.exit("[错误] 该版本没有文件")
    if prefer:
        for f in files:
            if prefer.lower() in (f.get("name") or "").lower():
                return f
    return max(files, key=lambda f: f.get("sizeKB") or 0)


def signed_url(version_id, key):
    url = DL % (version_id, key)
    try:
        NO_REDIRECT.open(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60)
        sys.exit("[错误] 下载端点没有返回重定向，无法获取直链")
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location") or e.headers.get("location") or ""
        if loc.startswith("http"):
            return loc
        if e.code in (301, 302, 303, 307, 308):
            sys.exit("[错误] 该资产需要浏览器登录（Location=%s）" % loc)
        sys.exit("[错误] 请求下载端点失败：HTTP %s" % e.code)
    except Exception as e:
        sys.exit("[错误] 请求下载端点异常：%s: %s" % (type(e).__name__, e))


def remote_size(url, retries=4):
    last = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                cr = r.headers.get("Content-Range") or ""
                if "/" in cr:
                    return int(cr.rsplit("/", 1)[1])
                return int(r.headers.get("Content-Length") or 0)
        except Exception as e:
            last = e
            time.sleep(2)
    print("[提示] 远端大小探测失败（%s），改用 API 记录值" % last)
    return 0


def download_part(url, path, start, end, idx, state, lock, retries=6):
    total = end - start + 1
    have0 = os.path.getsize(path) if os.path.exists(path) else 0
    if have0:
        with lock:
            state["done"] += have0
    for attempt in range(retries):
        have = os.path.getsize(path) if os.path.exists(path) else 0
        if have >= total:
            return True
        req = urllib.request.Request(
            url, headers={"User-Agent": UA, "Range": "bytes=%d-%d" % (start + have, end)}
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as r, open(path, "ab") as f:
                while True:
                    chunk = r.read(CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                    with lock:
                        state["done"] += len(chunk)
        except Exception as e:
            with lock:
                state["errors"].append("part %d 第 %d 次中断：%s" % (idx, attempt + 1, e))
            time.sleep(2)
    return (os.path.getsize(path) if os.path.exists(path) else 0) >= total


def merge(parts, target, sha256_want):
    h = hashlib.sha256()
    with open(target, "wb") as out:
        for p in parts:
            with open(p, "rb") as f:
                while True:
                    chunk = f.read(CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    h.update(chunk)
    digest = h.hexdigest().upper()
    if sha256_want and digest != sha256_want.upper():
        print("[警告] SHA256 不匹配：期望 %s，实际 %s" % (sha256_want, digest))
        return False
    if sha256_want:
        print("[校验] SHA256 一致：%s" % digest)
    return True


def main():
    ap = argparse.ArgumentParser(description="Civitai 多线程下载器")
    ap.add_argument("--model-id", type=int, help="模型 ID，自动取最新免费版本")
    ap.add_argument("--version-id", type=int, help="模型版本 ID，直接下载")
    ap.add_argument("--prefer", default="", help="版本名关键字，如 int8 / fp8")
    ap.add_argument("--file", default="", help="文件名关键字（多文件版本时用）")
    ap.add_argument("--out", default="", help="输出目录，默认 ComfyUI/models/diffusion_models")
    ap.add_argument("--threads", type=int, default=8, help="线程数，默认 8")
    args = ap.parse_args()

    if not args.model_id and not args.version_id:
        sys.exit("[错误] 请给出 --model-id 或 --version-id")

    key = load_api_key()

    if args.version_id:
        version = api_get("/model-versions/%d" % args.version_id, key)
        if version.get("error"):
            sys.exit("[错误] 查询版本失败：%s" % version["error"])
    else:
        version = pick_version(args.model_id, key, args.prefer)

    ver_name = version.get("name") or "?"
    f = pick_file(version, args.file)
    filename = f.get("name") or ("civitai_%s.safetensors" % version.get("id"))
    size_kb = f.get("sizeKB") or 0
    sha256_want = ((f.get("hashes") or {}).get("SHA256") or "").upper()
    size_hint = size_kb / 1048576

    out_dir = args.out or default_out_dir()
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, filename)

    print("版本   : %s" % ver_name)
    print("文件   : %s" % filename)
    print("体积   : %.2f GB" % size_hint)
    print("输出   : %s" % target)

    if os.path.exists(target) and size_kb and abs(os.path.getsize(target) / 1024 - size_kb) < 1024:
        print("[跳过] 文件已存在且体积一致")
        return

    url = signed_url(version.get("id"), key)
    total = remote_size(url) or int(size_kb * 1024)
    print("直链   : 已获取（R2 预签名，24 小时有效）")

    threads = max(1, min(args.threads, 32))
    seg = (total + threads - 1) // threads
    parts = ["%s.part%d" % (target, i) for i in range(threads)]
    ranges = []
    for i in range(threads):
        s = i * seg
        e = min(total - 1, s + seg - 1)
        if s <= e:
            ranges.append((i, s, e))

    state = {"done": 0, "errors": []}
    lock = threading.Lock()
    workers = []
    for idx, s, e in ranges:
        t = threading.Thread(target=download_part, args=(url, parts[idx], s, e, idx, state, lock))
        t.daemon = True
        workers.append(t)

    for t in workers:
        t.start()

    t0 = time.time()
    while any(t.is_alive() for t in workers):
        time.sleep(0.5)
        done = state["done"]
        pct = done * 100.0 / total if total else 0
        spd = done / max(0.001, time.time() - t0) / 1048576
        sys.stdout.write("\r进度: %6.2f%%  %.2f/%.2f GB  %.1f MB/s" % (
            pct, done / 1073741824, total / 1073741824, spd))
        sys.stdout.flush()
    for t in workers:
        t.join()
    print("")

    if state["errors"]:
        for e in state["errors"]:
            print("[重试日志] %s" % e)

    bad = []
    for idx, s, e in ranges:
        want = e - s + 1
        got = os.path.getsize(parts[idx]) if os.path.exists(parts[idx]) else 0
        if got != want:
            bad.append((idx, got, want))
    if bad:
        for idx, got, want in bad:
            print("[错误] 分块 %d 不完整：%d/%d 字节" % (idx, got, want))
        print("[中止] 可重新运行本命令续传（已完成的分块会保留）")
        return

    ok = merge(parts, target, sha256_want)
    if ok:
        for p in parts:
            if os.path.exists(p):
                os.remove(p)
        print("[完成] %.2f GB → %s" % (os.path.getsize(target) / 1073741824, target))
    else:
        print("[保留] 分块文件已保留，便于排查")


if __name__ == "__main__":
    main()
