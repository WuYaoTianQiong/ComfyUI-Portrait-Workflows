"""幂等键的统一入口：优先 `X-Idempotency-Key` 头，其次请求体里的旧字段。

scope 用来隔离入口：同一把键在「批量」和「试跑」下互不影响。
"""
from __future__ import annotations

SCOPE_RUN_SINGLE = "run_single"
SCOPE_TEXT_RUN = "text_run"
SCOPE_RUN_BATCH = "runs_batch"
SCOPE_COMPOSER_SINGLE = "composer_single"
SCOPE_COMPOSER_BATCH = "composer_batch"
SCOPE_IMAGE_PROCESS = "image_process"
SCOPE_FACESWAP = "faceswap"
SCOPE_RETRY = "retry"


def request_key(header_key: str | None, body_key: str = "") -> str:
    """头优先；两者都空时返回空串（调用方据此跳过幂等查询）。

    路由被其它路由直接调用时，FastAPI 的 Header 默认值是一个 Header 对象而不是 None，
    这里只接受真正的字符串，避免把声明对象当成键。
    """
    for value in (header_key, body_key):
        if isinstance(value, str):
            clean = value.strip()
            if clean:
                return clean
    return ""
