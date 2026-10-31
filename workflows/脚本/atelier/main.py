"""Atelier 启动壳。

真正的应用（FastAPI 实例、路由、中间件）定义在 app/main.py；
这里只负责把项目根放进 sys.path 并启动 uvicorn，保证 `python main.py`
与 `uvicorn main:app` 两种起法都能用。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.main import app  # noqa: E402,F401

if __name__ == "__main__":
    import uvicorn

    from app.config import settings

    print("=" * 56)
    print("  画室 Atelier (FastAPI)")
    print("=" * 56)

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )
