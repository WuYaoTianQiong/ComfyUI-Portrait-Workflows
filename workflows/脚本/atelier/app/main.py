"""FastAPI 应用入口"""
import logging
import threading
import time
import uuid
import webbrowser
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import FileResponse

from app import __version__
from app.config import settings
from app.models import init_db, db
from app.services.paths import _resolve_if_reparse
from app.services.logging_setup import setup_logging

logger = logging.getLogger("atelier")


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

# 旧路径 308 别名必须最后注册：注册在前面会抢走新路径的请求。
from app.routers.legacy import router as legacy_router

app.include_router(legacy_router, prefix="/api")

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
        if response.status_code == 404 and not request.url.path.startswith("/api/"):
            index_file = self._index_file or (settings.web_dir / "index.html")
            if index_file.exists():
                resp = FileResponse(index_file)
                resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                return resp
        return response

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

if _front_index.exists():
    if (_front_dir / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(_front_dir / "assets")), name="assets")
    app.add_middleware(SPAFallbackMiddleware, index_file=_front_index)
    print(f"  前端:     {_front_dir.name}/（npm run build 产物）")
else:
    print(f"  前端:     ⚠ 缺少 {_front_index} —— 请在 frontend/ 执行 npm run build")
