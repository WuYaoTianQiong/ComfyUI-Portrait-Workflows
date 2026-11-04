"""AI 参考图库 Web —— 上游 React 台的正式静态托管服务。

第三阶段（v0.7）形态：浏览/挑图以上游 `ai-pose-gallery-zh` 的 React 台为主，
atelier 继续负责任务队列、SSE、归档与提示词。

路由：
    `/` `/poses` `/costumes` ... → `<gallery>/dist`（SPA fallback）
    `/data/*` `/thumbs/*` `/img/*` → 上游仓库对应目录（只读）
    `/og-cover.jpg` `/robots.txt` `/sitemap.xml` → 上游仓库文件
    `/api/proxy` → 400 JSON（云端 CORS 代理本机不启用）
    `/comfy/*` → 反代 ComfyUI 8188，转发前删除 Origin/Referer

为什么必须删 Origin/Referer：ComfyUI 对异源 Origin 直接返回 403，浏览器从
`127.0.0.1:8760` 访问 `127.0.0.1:8188` 属于异源；同源反代并去掉这两个头可
免去给 ComfyUI 加 `--enable-cors-header` 启动参数。

单文件、仅标准库。用法：
    python serve.py [--port 8760] [--gallery-root <path>] [--comfy <url>]
环境变量（命令行优先）：
    ATELIER_REFERENCE_WEB_PORT
    ATELIER_REFERENCE_GALLERY_ROOT
    ATELIER_COMFYUI_API
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import socket
import socketserver
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_GALLERY_ROOT = r"F:\ComfyUI_Migration\custom_nodes\ai-pose-gallery-zh"
DEFAULT_COMFY = "http://127.0.0.1:8188"
DEFAULT_PORT = 8760

EXTRA_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".avif": "image/avif",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
    ".xml": "application/xml; charset=utf-8",
    ".map": "application/json; charset=utf-8",
}

SPA_FALLBACK = "/index.html"


def guess_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return EXTRA_TYPES.get(ext) or "application/octet-stream"


def _safe_join(base: str, rel: str) -> str | None:
    """把相对路径拼到 base 下，拒绝任何逃逸（含 `..` 与符号链接）。"""
    base_real = os.path.realpath(base)
    target = os.path.realpath(os.path.join(base_real, rel.replace("\\", "/")))
    if target == base_real:
        return None
    if not target.startswith(base_real + os.sep):
        return None
    return target


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _listening_pid(port: int) -> int | None:
    """尽力找出监听端口的 PID；仅用于启动失败时给出可操作提示。"""
    if os.name != "nt":
        return None
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            errors="ignore",
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    token = f":{port}"
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP":
            if parts[1].endswith(token) and "LISTENING" in parts[3]:
                try:
                    return int(parts[-1])
                except ValueError:
                    return None
    return None


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    gallery_root: str = DEFAULT_GALLERY_ROOT
    comfy_url: str = DEFAULT_COMFY

    @property
    def dist_dir(self) -> str:
        return os.path.join(self.gallery_root, "dist")

    static_prefixes = {
        "/data/": "data",
        "/thumbs/": "thumbs",
        "/img/": "img",
    }
    static_files = ("/og-cover.jpg", "/robots.txt", "/sitemap.xml")

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ---------------- 代理 ----------------
    def _proxy(self, method: str):
        target = self.comfy_url + self.path[len("/comfy"):]
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None

        # 只转发必要头；Origin/Referer 一律不带，否则 ComfyUI 403。
        headers = {}
        for key in ("Content-Type", "Accept", "Accept-Encoding"):
            if self.headers.get(key):
                headers[key] = self.headers[key]

        req = urllib.request.Request(target, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                payload = r.read()
                status = r.status
                ctype = r.headers.get("Content-Type", "application/octet-stream")
        except urllib.error.HTTPError as e:
            payload = e.read()
            status = e.code
            ctype = e.headers.get("Content-Type", "application/json")
        except Exception as e:
            payload = json.dumps({"error": f"proxy failed: {e}"}).encode()
            status = 502
            ctype = "application/json"

        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    # ---------------- 静态 ----------------
    def _send_file(self, path: str):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            self._send_text(404, "not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", guess_type(path))
        self.send_header("Content-Length", str(len(data)))
        cache = (
            "public, max-age=604800"
            if path.lower().endswith((".webp", ".jpg", ".jpeg", ".png", ".gif", ".avif"))
            else "no-cache"
        )
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(data)

    def _send_text(self, status: int, text: str, ctype="text/plain; charset=utf-8"):
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _resolve(self, url_path: str) -> str | None:
        clean = urllib.parse.unquote(url_path.split("?", 1)[0].split("#", 1)[0])
        if not clean.startswith("/"):
            return None
        if clean in self.static_files:
            return _safe_join(self.gallery_root, clean.lstrip("/"))
        for prefix, sub in self.static_prefixes.items():
            if clean.startswith(prefix):
                rel = clean[len(prefix):]
                if not rel:
                    return None
                return _safe_join(os.path.join(self.gallery_root, sub), rel)
        # dist 静态资源
        candidate = _safe_join(self.dist_dir, clean.lstrip("/"))
        if candidate and os.path.isfile(candidate):
            return candidate
        return None

    def _is_spa_route(self, url_path: str) -> bool:
        clean = urllib.parse.unquote(url_path.split("?", 1)[0].split("#", 1)[0])
        last = clean.rstrip("/").rsplit("/", 1)[-1]
        return "." not in last

    def do_GET(self):
        if self.path.startswith("/comfy/"):
            return self._proxy("GET")
        if self.path.startswith("/api/proxy"):
            return self._web_proxy_disabled()
        target = self._resolve(self.path)
        if target is None:
            # SPA fallback：/poses /studio /settings 等前端路由都回 index.html。
            # 缺失的静态文件（带扩展名）回 404，避免把 HTML 当 JS/CSS 返回。
            if not self._is_spa_route(self.path):
                return self._send_text(404, "not found")
            return self._send_file(os.path.join(self.dist_dir, SPA_FALLBACK.lstrip("/")))
        return self._send_file(target)

    def do_POST(self):
        if self.path.startswith("/comfy/"):
            return self._proxy("POST")
        if self.path.startswith("/api/proxy"):
            return self._web_proxy_disabled()
        return self._send_text(404, "not found")

    def do_PUT(self):
        if self.path.startswith("/comfy/"):
            return self._proxy("PUT")
        return self._send_text(404, "not found")

    def do_DELETE(self):
        if self.path.startswith("/comfy/"):
            return self._proxy("DELETE")
        return self._send_text(404, "not found")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _web_proxy_disabled(self):
        self._send_text(
            400,
            json.dumps({"error": {"message": "参考图库 Web：云端代理未启用"}}),
            "application/json; charset=utf-8",
        )


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI 参考图库 Web 静态托管服务")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("ATELIER_REFERENCE_WEB_PORT", DEFAULT_PORT)),
        help=f"监听端口（默认 {DEFAULT_PORT}，可设 ATELIER_REFERENCE_WEB_PORT）",
    )
    parser.add_argument(
        "--gallery-root",
        default=os.environ.get("ATELIER_REFERENCE_GALLERY_ROOT", DEFAULT_GALLERY_ROOT),
        help="上游 ai-pose-gallery-zh 仓库根（只读）",
    )
    parser.add_argument(
        "--comfy",
        default=os.environ.get("ATELIER_COMFYUI_API", DEFAULT_COMFY),
        help=f"ComfyUI 地址（默认 {DEFAULT_COMFY}）",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    gallery_root = os.path.realpath(args.gallery_root)
    comfy_url = args.comfy.rstrip("/")

    if not os.path.isdir(gallery_root):
        print(f"上游仓库不存在: {gallery_root}", file=sys.stderr)
        return 1
    if not os.path.isfile(os.path.join(gallery_root, "dist", "index.html")):
        print(
            f"dist/index.html 不存在（{gallery_root}\\dist），先运行 npx vite build",
            file=sys.stderr,
        )
        return 1
    if _port_in_use(args.port):
        pid = _listening_pid(args.port)
        detail = f"，占用 PID={pid}" if pid else ""
        print(f"端口 {args.port} 已被占用{detail}，请先释放或换端口", file=sys.stderr)
        return 1

    Handler.gallery_root = gallery_root
    Handler.comfy_url = comfy_url
    server = Server(("127.0.0.1", args.port), Handler)
    print(
        f"参考图库 Web: http://127.0.0.1:{args.port}/  "
        f"dist={os.path.join(gallery_root, 'dist')}"
    )
    print(f"   /comfy → {comfy_url}（转发时删除 Origin/Referer）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("已停止")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())