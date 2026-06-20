"""FastAPI 应用入口"""
import asyncio
import threading
import time
import traceback
import webbrowser
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import FileResponse

from config import settings
from models import init_db, db, GenJob


# ======== 后台任务监控 ========

_last_history_sync = 0.0


async def job_monitor_loop():
    """异步后台任务：每 5 秒同步活跃任务状态，每 30 秒同步一次 ComfyUI 全局历史"""
    global _last_history_sync
    while True:
        await asyncio.sleep(5)
        try:
            from routers.jobs import get_job_status_snapshot, _row_to_dict

            jobs = (
                GenJob.select()
                .where(GenJob.status.in_(["pending", "running"]))
                .order_by(GenJob.id.desc())
                .limit(20)
            )
            for job in jobs:
                try:
                    get_job_status_snapshot(_row_to_dict(job))
                except Exception:
                    traceback.print_exc()

            # 每 30 秒同步一次 ComfyUI 全局历史
            now = time.monotonic()
            if now - _last_history_sync >= 30:
                _last_history_sync = now
                try:
                    from routers.history import _sync_comfyui_history
                    _sync_comfyui_history()
                except Exception:
                    traceback.print_exc()
        except Exception:
            traceback.print_exc()


# ======== 应用生命周期 ========

@asynccontextmanager
async def lifespan(app: FastAPI):
    # === 启动 ===
    init_db()
    print(f"  DB:       {settings.db_path}")
    print(f"  ComfyUI:  {settings.comfyui_api}")
    print(f"  API 文档:  http://{settings.host}:{settings.port}/docs")
    print(f"  本地页面:  http://{settings.host}:{settings.port}")
    print("=" * 56)
    print("  按 Ctrl+C 停止服务")
    print()

    # 启动后台任务监控
    monitor_task = asyncio.create_task(job_monitor_loop())

    # 自动打开浏览器
    threading.Thread(target=_open_browser, daemon=True).start()

    yield

    # === 关闭 ===
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass
    db.close()


def _open_browser():
    time.sleep(0.5)
    webbrowser.open(f"http://{settings.host}:{settings.port}")


# ======== FastAPI 应用 ========

app = FastAPI(
    title="Prompt Browser v4",
    description="提示词管理器 + ComfyUI 启动器",
    version="4.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
from routers.prompts import router as prompts_router
from routers.workflows import router as workflows_router
from routers.jobs import router as jobs_router
from routers.history import router as history_router
from routers.comfyui import router as comfyui_router
from routers.thumbnail import router as thumbnail_router

app.include_router(prompts_router, prefix="/api")
app.include_router(workflows_router, prefix="/api")
app.include_router(jobs_router, prefix="/api")
app.include_router(history_router, prefix="/api")
app.include_router(comfyui_router, prefix="/api")
app.include_router(thumbnail_router, prefix="/api")

# SPA Fallback 中间件：静态文件返回 404 后返回 index.html（支持前端 History API 路由）
class SPAFallbackMiddleware(BaseHTTPMiddleware):
    """在静态文件挂载返回 404 后，返回 index.html 以支持前端路由"""
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if response.status_code == 404 and not request.url.path.startswith("/api/"):
            index_file = settings.static_dir / "index.html"
            if index_file.exists():
                return FileResponse(index_file)
        return response

# 静态文件挂载 + SPA Fallback 中间件
if settings.static_dir.exists():
    app.mount("/", StaticFiles(directory=str(settings.static_dir), html=True), name="static")
    app.add_middleware(SPAFallbackMiddleware)


# ======== 直接运行入口 ========
if __name__ == "__main__":
    import uvicorn

    print("=" * 56)
    print("  Prompt Browser v4 (FastAPI)")
    print("=" * 56)

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )
