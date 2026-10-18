"""统一日志配置 —— UTF-8 文件 + 轮转 + 控制台。

为什么需要它：
- 之前全项目 45 处 `print`，子进程 stdout 重定向到文件时 Windows 用 cp936 编码，
  读方按 utf-8 解就是乱码（`_pb_out.log:4` 实证）；
- 没有请求 ID、没有耗时，出问题只能靠猜。

用法：在应用启动时调用一次 `setup_logging(log_dir)`；其余模块用
`logging.getLogger(__name__)` 即可，不要再用 print。
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"
_configured = False


def setup_logging(log_dir: Path, level: int = logging.INFO) -> logging.Logger:
    """幂等：重复调用不会重复挂 handler。返回应用根 logger。"""
    global _configured
    logger = logging.getLogger("prompt_browser")
    if _configured:
        return logger

    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    file_handler = RotatingFileHandler(
        log_dir / "app.log", maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # 控制台保持可读；Windows 控制台编码问题由 PYTHONUTF8=1 / chcp 65001 解决
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    _configured = True
    logger.info("日志已启用: %s", log_dir / "app.log")
    return logger
