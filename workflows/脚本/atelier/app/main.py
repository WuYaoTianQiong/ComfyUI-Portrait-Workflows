"""FastAPI 应用入口"""
import asyncio
import logging
import mimetypes
import threading
import time
import uuid
import webbrowser
from contextlib import asynccontextmanager
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit

import httpx
import websockets
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse

from app import __version__
from app.config import settings
from app.models import init_db, db
from app.services.paths import _resolve_if_reparse
from app.services.logging_setup import setup_logging
from app.services.workflow_parser import RatioNotSupported

logger = logging.getLogger("atelier")

# Windows 的 mimetypes 注册表不一定认识 webp/avif，补上避免静态挂载返回 text/plain。
for _ext, _type in (
    (".webp", "image/webp"),
    (".avif", "image/avif"),
    (".woff2", "font/woff2"),
):
    mimetypes.add_type(_type, _ext)


# ======== 应用生命周期 ========

@asynccontextmanager
async def lifespan(app: FastAPI):
    # === 启动 ===
    setup_logging(settings.app_root / "logs")
    init_db()
    # 启动维护：在线备份 → 备份归档/轮转 → 回收超过保留期的墓碑。
    # 必须在写者线程启动前跑完，避免和同步/巡检抢写锁。
    from app.services.maintenance import run_startup_maintenance

    run_startup_maintenance()
    print(f"  DB:       {settings.db_path}")
    print(f"  ComfyUI:  {settings.comfyui_api}")
    print(f"  API 文档:  http://{settings.host}:{settings.port}/docs")
    print(f"  本地页面:  http://{settings.host}:{settings.port}")
    print("=" * 56)
    print("  按 Ctrl+C 停止服务")
    print()

    # 任务写者：普通守护线程，不是 async task。
    # 旧实现把同步 HTTP/DB 塞进事件循环，ComfyUI 一慢，所有请求一起卡住。
    from app.services.job_state import recover_queued_submissions, writer_loop
    from app.services.submission import start_submit_worker, stop_submit_worker

    recovered = recover_queued_submissions()
    if recovered:
        logger.info("启动恢复：%s 个任务的未提交条目已标记中断", recovered)

    stop_event = threading.Event()
    writer = threading.Thread(
        target=writer_loop, args=(stop_event,), daemon=True, name="job-writer"
    )
    writer.start()
    start_submit_worker()

    # 自动打开浏览器（ATELIER_NO_BROWSER=1 时跳过，供冒烟/测试使用）
    if not settings.no_browser:
        threading.Thread(target=_open_browser, daemon=True).start()

    yield

    # === 关闭 ===
    stop_submit_worker()
    stop_event.set()
    writer.join(timeout=5)
    if _comfy_http is not None and not _comfy_http.is_closed:
        await _comfy_http.aclose()
    db.close()


def _open_browser():
    time.sleep(0.5)
    webbrowser.open(f"http://{settings.host}:{settings.port}")


# ======== FastAPI 应用 ========

app = FastAPI(
    title="Atelier",
    description="提示词工作台 + ComfyUI 出图控制台",
    version=__version__,
    lifespan=lifespan,
)


@app.exception_handler(RatioNotSupported)
async def _ratio_not_supported(_request, exc: RatioNotSupported):
    """比例超出工作流安全范围时直接拒绝，前端根据 detail 提示换工作流。"""
    return JSONResponse(status_code=400, content={"detail": str(exc)})

# CORS：前端与后端同源部署，开发期走 Vite 代理，本来不需要跨域。
# 保留本机开发来源即可；绝不能用 "*" —— 否则任意网页都能借本机浏览器读接口响应。
_ALLOWED_ORIGINS = sorted({
    "http://127.0.0.1:8656",
    "http://localhost:8656",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    f"http://{settings.host}:{settings.port}",
})
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RequestLogMiddleware(BaseHTTPMiddleware):
    """请求 ID + 耗时日志：出问题时能按 rid 串起一次操作的所有请求。"""

    async def dispatch(self, request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:8]
        request.state.request_id = rid
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("未处理异常 %s %s rid=%s", request.method, request.url.path, rid)
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = rid
        if request.url.path.startswith("/api/"):
            logger.log(
                logging.WARNING if response.status_code >= 500 else logging.INFO,
                "%s %s -> %d %.0fms rid=%s",
                request.method, request.url.path, response.status_code, elapsed_ms, rid,
            )
        elif elapsed_ms > 1500:
            logger.warning("慢请求 %s %s -> %d %.0fms rid=%s",
                           request.method, request.url.path, response.status_code, elapsed_ms, rid)
        return response


app.add_middleware(RequestLogMiddleware)

# 注册路由
from app.routers.prompts import router as prompts_router
from app.routers.jobs import router as jobs_router
from app.routers.images import router as images_router
from app.routers.comfyui import router as comfyui_router
from app.routers.media import router as media_router
from app.routers.categories import router as categories_router
from app.routers.tags import router as tags_router
from app.routers.composer import router as composer_router
from app.routers.composition import router as composition_router
from app.routers.templates import router as templates_router
from app.routers.fragments import router as fragments_router
from app.routers.system import router as system_router
from app.routers.editor import router as editor_router
from app.routers.reference_library import router as reference_library_router
from app.routers.reference_upload import router as reference_upload_router
from app.routers.reference_sheet import router as reference_sheet_router
from app.routers.reference_fragments import router as reference_fragments_router

app.include_router(prompts_router, prefix="/api")
app.include_router(jobs_router, prefix="/api")
app.include_router(images_router, prefix="/api")
app.include_router(comfyui_router, prefix="/api")
app.include_router(media_router, prefix="/api")
app.include_router(categories_router, prefix="/api")
app.include_router(tags_router, prefix="/api")
app.include_router(composer_router, prefix="/api")
app.include_router(composition_router, prefix="/api")
app.include_router(templates_router, prefix="/api")
app.include_router(fragments_router, prefix="/api")
app.include_router(system_router, prefix="/api")
app.include_router(editor_router, prefix="/api")

# AI 参考图库：只读素材层。开关关闭时不注册路由（/api/reference/* 直接 404），
# 回滚只需要 ATELIER_REFERENCE_ENABLED=0，无数据库变更。
if settings.reference_enabled:
    app.include_router(reference_library_router, prefix="/api")
    app.include_router(reference_upload_router, prefix="/api")
    app.include_router(reference_sheet_router, prefix="/api")
    app.include_router(reference_fragments_router, prefix="/api")

# 旧路径 308 别名必须最后注册：注册在前面会抢走新路径的请求。
from app.routers.legacy import router as legacy_router

app.include_router(legacy_router, prefix="/api")

# 参考图库旧前缀。阶段 4.3 删除 React 子应用与 `/ref-web` 静态挂载后，
# 该前缀只用于把旧书签重定向到 `/reference`（施工手册 §6）。
# 用精确路径段判断，避免 /ref-webevil 被误匹配。
_REF_WEB_PREFIX = "/ref-web"

def _is_ref_web_path(path: str) -> bool:
    return path == _REF_WEB_PREFIX or path.startswith(_REF_WEB_PREFIX + "/")

# 旧深链段 → 新页签键（与前端 referenceDeepLink.ts 的映射保持一致）。
_REF_WEB_TAB_BY_SEGMENT = {
    "poses": "pose",
    "costumes": "costume",
    "portraits": "portrait",
    "studio": "studio",
    "settings": "settings",
}

def _is_safe_reference_path(value: str) -> bool:
    """校验旧 `?path=` 深链的原始值。

    只接受带 `/ref-web` 前缀的值，禁 `..`（穿越）、`//`（协议相对地址）、
    `\\`（浏览器等价 `/`）、`:`（绝对 URL / 端口）；再用 URL 解析后的 pathname
    二次校验，挡掉 `%2e%2e` 这类规范化之后才暴露的穿越。规则与删除前的
    与阶段 4.3 删除的 iframe 壳校验一致，不因解析页签而放宽。
    """
    if not value:
        return False
    if not (
        value == _REF_WEB_PREFIX
        or value.startswith(_REF_WEB_PREFIX + "/")
        or value.startswith(_REF_WEB_PREFIX + "?")
        or value.startswith(_REF_WEB_PREFIX + "#")
    ):
        return False
    if ".." in value or "//" in value or "\\" in value or ":" in value:
        return False

    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return False
    decoded_path = unquote(parsed.path)
    if any(segment in (".", "..") for segment in decoded_path.split("/")):
        return False
    return decoded_path == _REF_WEB_PREFIX or decoded_path.startswith(_REF_WEB_PREFIX + "/")

def _reference_tab_from_path(value: str) -> str | None:
    """合法旧深链 → 页签键；`/ref-web` 本身与未知段返回 None（回落默认页）。"""
    if not _is_safe_reference_path(value):
        return None
    path = unquote(urlsplit(value).path).rstrip("/")
    if path == _REF_WEB_PREFIX:
        return None
    return _REF_WEB_TAB_BY_SEGMENT.get(path[len(_REF_WEB_PREFIX) + 1:])

def _merge_reference_query(raw_query: str, extra: list[tuple[str, str]]) -> str:
    """把页签等参数前置，其余 query 原样保留（同名项以显式参数为准）。"""
    reserved = {key for key, _ in extra}
    pairs = [
        (key, value)
        for key, value in parse_qsl(raw_query, keep_blank_values=True)
        if key not in reserved
    ]
    return urlencode(extra + pairs, doseq=True)

def _drop_query_keys(raw_query: str, keys: set[str]) -> str:
    """删除指定 query 键，其余参数与顺序保持不变。"""
    pairs = [
        (key, value)
        for key, value in parse_qsl(raw_query, keep_blank_values=True)
        if key not in keys
    ]
    return urlencode(pairs, doseq=True)

def _redirect_to_reference(raw_query: str, tab: str | None, status_code: int) -> RedirectResponse:
    """组装 `/reference?tab=...` 重定向地址（保留原 query）。"""
    extra = [("tab", tab)] if tab else []
    merged = _merge_reference_query(raw_query, extra)
    target = "/reference" + (f"?{merged}" if merged else "")
    return RedirectResponse(target, status_code=status_code)

# SPA Fallback 中间件：静态文件返回 404 后返回 index.html（支持前端 History API 路由）
class SPAFallbackMiddleware(BaseHTTPMiddleware):
    """在静态文件挂载返回 404 后，返回 index.html 以支持前端路由"""

    def __init__(self, app, index_file=None):
        super().__init__(app)
        self._index_file = index_file

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        # 静态资源的响应不缓存（html/js/css），方便开发调试
        if response.status_code < 400 and not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        # 数据 API 默认禁止浏览器缓存，避免前端刷新/轮询/翻页时吃到旧数据
        # （缩略图/原图等自带 Cache-Control 长缓存的端点不受影响）
        if request.url.path.startswith("/api/") and "cache-control" not in {k.lower() for k in response.headers.keys()}:
            response.headers["Cache-Control"] = "no-store"
        # /ref-web/* 由下方重定向路由处理，不再走 Vue 的 index.html 兜底：
        # 否则旧深链会被 SPA 接住，书签不会跳到 /reference。
        if (
            response.status_code == 404
            and not request.url.path.startswith("/api/")
            and not _is_ref_web_path(request.url.path)
        ):
            index_file = self._index_file or (settings.web_dir / "index.html")
            if index_file.exists():
                resp = FileResponse(index_file)
                resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                return resp
        return response


# 图片数据外挂到上游目录（只读），junction 先解析，避免 WinError 448。
_ref_dir = _resolve_if_reparse(settings.reference_dir)
for _prefix, _sub in (("/data", "data"), ("/thumbs", "thumbs"), ("/img", "img")):
    _mount_dir = _resolve_if_reparse(_ref_dir / _sub)
    if _mount_dir.is_dir():
        app.mount(_prefix, StaticFiles(directory=str(_mount_dir)), name=_prefix.lstrip("/"))
        print(f"  [mount] {_prefix} -> {_mount_dir}")
    else:
        logger.warning("参考图库目录不存在，跳过 %s 挂载：%s", _prefix, _mount_dir)


# ComfyUI 反代复用同一个 httpx 客户端。
# 旧实现每个请求新建 AsyncClient，而 httpx 会在 __init__ 里**同步**构建 SSLContext
# （Windows 证书库约 1.3–1.5s），在事件循环里阻塞：实测 14 个并发 object_info 被完全串行化
# （总耗时 34s，单请求 2.6s），合成台的 8s 预检超时后报「请求 /comfy 超时」。
# 复用后既省掉这次构建，也拿到连接池：单请求从 2.6s 降到几十毫秒。
_comfy_http: httpx.AsyncClient | None = None


def _comfy_client() -> httpx.AsyncClient:
    global _comfy_http
    if _comfy_http is None or _comfy_http.is_closed:
        _comfy_http = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=10.0),
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
        )
    return _comfy_http


@app.api_route(
    "/comfy/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    # 同源反代不是业务接口，不能进入 OpenAPI 契约（会制造快照漂移）。
    include_in_schema=False,
)
async def _comfy_proxy(path: str, request: Request):
    """同源反代 ComfyUI；上游前端默认把 `/comfy` 当 ComfyUI 地址。"""
    target = f"{settings.comfyui_api.rstrip('/')}/{path}"
    if request.url.query:
        target = f"{target}?{request.url.query}"

    # Origin/Referer 会让 ComfyUI 直接 403；Host/Content-Length 由 httpx 重算。
    _drop = {"host", "origin", "referer", "content-length", "connection", "transfer-encoding"}
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _drop}
    body = await request.body()

    client = _comfy_client()
    try:
        upstream = await client.send(
            client.build_request(request.method, target, headers=headers, content=body),
            stream=True,
        )
    except httpx.HTTPError as exc:
        logger.warning("ComfyUI 反代失败 %s %s: %s", request.method, target, exc)
        return JSONResponse(status_code=502, content={"error": f"ComfyUI 反代失败: {exc}"})

    async def _stream():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()

    _skip = {"content-length", "content-encoding", "transfer-encoding", "connection"}
    resp_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _skip}
    return StreamingResponse(_stream(), status_code=upstream.status_code, headers=resp_headers)


@app.websocket("/comfy/ws")
async def _comfy_ws_proxy(ws: WebSocket):
    """同源反代 ComfyUI 的 /ws：合成台的实时进度、预览、队列状态都走这条。

    上游前端把 `/comfy` 当 ComfyUI 地址时会去连 `ws://<host>/comfy/ws?clientId=...`，
    只代理 HTTP 时这里返回 403（浏览器 9 条 console 报错），进度只能靠轮询兜底。
    """
    query = f"?{ws.url.query}" if ws.url.query else ""
    upstream_url = (
        settings.comfyui_api.rstrip("/").replace("https://", "wss://").replace("http://", "ws://")
        + "/ws"
        + query
    )
    await ws.accept()
    try:
        async with websockets.connect(upstream_url, max_size=None) as upstream:

            async def client_to_upstream():
                while True:
                    message = await ws.receive()
                    if message["type"] == "websocket.disconnect":
                        break
                    if message.get("text") is not None:
                        await upstream.send(message["text"])
                    elif message.get("bytes") is not None:
                        await upstream.send(message["bytes"])

            async def upstream_to_client():
                async for payload in upstream:
                    if isinstance(payload, bytes):
                        await ws.send_bytes(payload)
                    else:
                        await ws.send_text(payload)

            tasks = {
                asyncio.create_task(client_to_upstream()),
                asyncio.create_task(upstream_to_client()),
            }
            _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("ComfyUI WebSocket 反代失败 %s: %s", upstream_url, exc)
    finally:
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass


# 挂载 ComfyUI 输出目录为静态文件（图片直读，不走 Python FileResponse）
# 注意：comfyui_root/output 可能是跨卷 junction，未解析时 .exists() 在 Windows
# “不受信任装入点”上会抛 WinError 448 导致整个服务启动崩溃，必须先解析。
_output_dir = _resolve_if_reparse(settings.output_dir)
if _output_dir.exists():
    app.mount("/output", StaticFiles(directory=str(_output_dir)), name="output")
    print(f"  [mount] /output -> {_output_dir}")
_input_dir = _resolve_if_reparse(settings.input_dir)
if _input_dir.exists():
    app.mount("/input", StaticFiles(directory=str(_input_dir)), name="input")
    print(f"  [mount] /input -> {_input_dir}")
_temp_dir = _resolve_if_reparse(settings.temp_dir)
if _temp_dir.exists():
    app.mount("/temp", StaticFiles(directory=str(_temp_dir)), name="temp")
    print(f"  [mount] /temp -> {_temp_dir}")

# 静态文件挂载 + SPA Fallback 中间件
#
# 前端只有一套：Vue 构建产物（settings.web_dir 指定目录，含 index.html + assets/）。
# 是否挂载以 index.html 是否存在为准，不靠开关、不靠环境变量：
# 未执行 npm run build 时服务照样能起来，只是根路径没有页面（启动日志会提示）。
_front_dir = settings.web_dir
_front_index = _front_dir / "index.html"

# 参考图库旧深链重定向（施工手册 §6）。
#
# 阶段 4.3 删除了 `/ref-web` 的 React 静态挂载，但该前缀必须仍有归宿：
# 不注册这些路由时旧书签会落到 SPA 兜底，书签不会跳到 `/reference`。
# 全部用精确前缀判断，`/ref-webevil` 不匹配 `/ref-web` 或 `/ref-web/{...}`。
@app.api_route(_REF_WEB_PREFIX, methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route(_REF_WEB_PREFIX + "/", methods=["GET", "HEAD"], include_in_schema=False)
def _redirect_ref_web_root(request: Request) -> RedirectResponse:
    """`/ref-web` 与 `/ref-web/` → `/reference`（301）。"""
    return _redirect_to_reference(request.url.query, None, 301)


@app.api_route(
    _REF_WEB_PREFIX + "/{rest:path}",
    methods=["GET", "HEAD"],
    include_in_schema=False,
)
def _redirect_ref_web_deep(rest: str, request: Request) -> RedirectResponse:
    """`/ref-web/<页签>` → `/reference?tab=...`（301）；未知段 302 兜底，不 404。

    `rest` 带前导 `/`（`/ref-web//poses`）或含多段（`/ref-web/poses/extra`）
    都按未知段处理，避免把畸形路径映射成正常页签。
    """
    tab = None
    if not rest.startswith("/"):
        tab = _REF_WEB_TAB_BY_SEGMENT.get(rest.rstrip("/"))
    return _redirect_to_reference(request.url.query, tab, 301 if tab else 302)


@app.api_route("/reference", methods=["GET", "HEAD"], include_in_schema=False)
def _reference_page(request: Request):
    """SPA 入口：`?path=/ref-web/xxx` 翻译为 `?tab=xxx`，其余直接返回 Vue index.html。

    iframe 壳已删除，`?path=` 不再有承载页，必须就地翻译；非法值去掉 `path`
    后回落默认页（图库总览），不白屏、不 404。
    """
    if "path" in request.query_params:
        tab = _reference_tab_from_path(request.query_params.get("path") or "")
        return _redirect_to_reference(
            _drop_query_keys(request.url.query, {"path", "shell"}),
            tab,
            301,
        )
    if not _front_index.exists():
        return JSONResponse({"detail": "前端未构建：缺少 web/index.html"}, status_code=404)
    resp = FileResponse(_front_index)
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


if _front_index.exists():
    if (_front_dir / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(_front_dir / "assets")), name="assets")
    app.add_middleware(SPAFallbackMiddleware, index_file=_front_index)
    print(f"  前端:     {_front_dir.name}/（npm run build 产物）")
else:
    print(f"  前端:     ⚠ 缺少 {_front_index} —— 请在 frontend/ 执行 npm run build")
