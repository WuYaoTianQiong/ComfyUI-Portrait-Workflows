"""外链参考图缓存（CharaDB 素材仅本机参考、禁止再分发）。

`costume-anime` 库的图片在上游 CDN，atelier 只做**只读代理下载 + 本机私有缓存**：

- 只允许配置白名单内的 https 外链（测试环境可 http，但仍必须命中白名单）；
- 缓存命中不发任何网络请求；
- 未命中按缓存键用 `asyncio.Lock` 去重，同一张图并发请求只下载一次；
- `httpx` 流式读取并限制单文件大小，不跟随重定向（3xx 视为失败）；
- 同目录 `.tmp` + `os.replace` 原子写，失败清理临时文件；
- 缓存目录必须落在 `app_root` 下，且不与 `reference_root`、`data/`、`dist/` 互相包含。

许可边界：CharaDB 素材仅本机参考、禁止再分发；缓存目录已被根 `.gitignore` 排除，
不得复制进 `data/`、`dist/` 或提交入库。
"""
from __future__ import annotations

import asyncio
import logging
import os
import posixpath
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse

import httpx

from app.config import settings
from app.services.paths import is_inside_dir

logger = logging.getLogger("atelier.reference.remote_cache")

#: URL path 可识别的扩展名（优先使用，其次才看 Content-Type）
_URL_EXTENSIONS: frozenset[str] = frozenset({".webp", ".jpg", ".jpeg", ".png", ".gif", ".avif"})

#: Content-Type → 扩展名（URL 无扩展名时兜底；仍无法识别则 `.bin`）
_CONTENT_TYPE_EXTENSIONS: dict[str, str] = {
    "image/webp": ".webp",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/avif": ".avif",
}

_ALLOWED_SCHEMES: frozenset[str] = frozenset({"https", "http"})


class RemoteCacheError(Exception):
    """外链缓存失败：`status_code` 直接映射到 HTTP 状态码。"""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class _RetryableDownloadError(Exception):
    """内部用：HTTP 状态码非 2xx / 3xx / 网络错误可重试，最终统一转 502。"""


# ---------------------------------------------------------------------------
# 缓存路径与安全校验
# ---------------------------------------------------------------------------


def _safe_segment(value: str) -> str:
    """缓存键的单段校验：拒绝空串、`.`、`..`、分隔符、冒号与控制字符。"""
    text = str(value or "")
    if not text or text in (".", ".."):
        raise RemoteCacheError(400, "非法的缓存键")
    if "/" in text or "\\" in text or ":" in text:
        raise RemoteCacheError(400, "非法的缓存键")
    if any(ord(ch) < 32 for ch in text):
        raise RemoteCacheError(400, "非法的缓存键")
    return text


def _ext_from_url(url: str) -> str | None:
    path = unquote(urlparse(url or "").path)
    suffix = posixpath.splitext(path)[1].lower()
    return suffix if suffix in _URL_EXTENSIONS else None


def _ext_from_content_type(content_type: str) -> str | None:
    base = (content_type or "").split(";", 1)[0].strip().lower()
    return _CONTENT_TYPE_EXTENSIONS.get(base)


def cache_root() -> Path:
    """本机缓存根目录；由 `app/config.py` 校验落点，此处不创建目录。"""
    return Path(settings.reference_cache_dir)


def _target_path(library: str, item_id: str, kind: str, ext: str) -> Path:
    root = cache_root()
    target = (
        root
        / _safe_segment(library)
        / _safe_segment(item_id)
        / f"{_safe_segment(kind)}{ext}"
    )
    if not is_inside_dir(root, target):
        raise RemoteCacheError(400, "非法的缓存键")
    return target


def cache_path(library: str, item_id: str, kind: str, url: str) -> Path:
    """返回缓存目标路径（由 URL 扩展名决定；无法识别时用 `.bin` 占位）。

    下载完成后若 Content-Type 能映射出扩展名，会落到 `kind.ext`；`is_cached()`
    同时兼容这两种落盘方式。
    """
    ext = _ext_from_url(url) or ".bin"
    return _target_path(library, item_id, kind, ext)


def _cached_file(library: str, item_id: str, kind: str, url: str) -> Path | None:
    """查找已缓存且大小 > 0 的文件；不发起网络请求。"""
    hint = cache_path(library, item_id, kind, url)
    candidates: list[Path] = [hint]
    directory = hint.parent
    prefix = _safe_segment(kind) + "."
    try:
        if directory.is_dir():
            for entry in directory.iterdir():
                if entry.name.startswith(prefix) and entry not in candidates:
                    candidates.append(entry)
    except OSError:
        pass

    for candidate in candidates:
        try:
            if candidate.is_file() and candidate.stat().st_size > 0:
                return candidate
        except OSError:
            continue
    return None


def is_cached(library: str, item_id: str, kind: str, url: str) -> bool:
    """缓存是否已就绪（文件存在且大小 > 0）。"""
    return _cached_file(library, item_id, kind, url) is not None


def _validate_url(url: str) -> str:
    """仅允许 http(s) + 白名单域名；返回去空白后的原始 URL。"""
    text = (url or "").strip()
    if not text:
        raise RemoteCacheError(400, "缺少图片地址")
    parsed = urlparse(text)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise RemoteCacheError(400, "不支持的图片地址")
    host = (parsed.hostname or "").lower()
    if not host:
        raise RemoteCacheError(400, "非法的图片地址")
    if host not in settings.reference_remote_host_set:
        raise RemoteCacheError(400, "不在允许的外链域名内")
    # 禁止 URL 里带用户名/密码，避免凭据被打进日志或缓存键
    if parsed.username or parsed.password:
        raise RemoteCacheError(400, "非法的图片地址")
    return text


# ---------------------------------------------------------------------------
# 事件循环作用域的锁 / 信号量
# ---------------------------------------------------------------------------


@dataclass
class _LoopState:
    loop: asyncio.AbstractEventLoop
    locks: dict[tuple[str, str, str, str], asyncio.Lock] = field(default_factory=dict)
    semaphore: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(1))
    concurrency: int = 1


_LOOP_STATES: dict[int, _LoopState] = {}
_STATE_LOCK = threading.Lock()


def _loop_state() -> _LoopState:
    """按事件循环隔离锁与信号量（asyncio 原语不能跨 loop 复用）。"""
    loop = asyncio.get_running_loop()
    concurrency = max(1, int(settings.reference_remote_max_concurrency))
    with _STATE_LOCK:
        # 顺手清理已经关闭的 loop，避免测试反复 asyncio.run 时状态无限增长
        for key in [k for k, state in _LOOP_STATES.items() if state.loop.is_closed()]:
            _LOOP_STATES.pop(key, None)

        state = _LOOP_STATES.get(id(loop))
        if state is None or state.loop is not loop or state.concurrency != concurrency:
            state = _LoopState(
                loop=loop,
                locks={},
                semaphore=asyncio.Semaphore(concurrency),
                concurrency=concurrency,
            )
            _LOOP_STATES[id(loop)] = state
        return state


def reset_state() -> None:
    """测试/运维用：清空各事件循环的锁与信号量注册表。"""
    with _STATE_LOCK:
        _LOOP_STATES.clear()


def _make_client() -> httpx.AsyncClient:
    """创建下载客户端；不跟随重定向（3xx 一律按失败处理）。"""
    return httpx.AsyncClient(
        timeout=float(settings.reference_remote_timeout_sec),
        follow_redirects=False,
    )


# ---------------------------------------------------------------------------
# 下载与原子写
# ---------------------------------------------------------------------------


async def _download_once(
    library: str,
    item_id: str,
    kind: str,
    url: str,
) -> Path:
    """下载一次并原子落盘；可重试错误抛 `_RetryableDownloadError`。"""
    url = _validate_url(url)
    hint = cache_path(library, item_id, kind, url)
    url_ext = _ext_from_url(url)
    max_bytes = int(settings.reference_remote_max_bytes)

    async with _make_client() as client:
        async with client.stream("GET", url) as response:
            if not 200 <= response.status_code < 300:
                raise _RetryableDownloadError(f"HTTP {response.status_code}")

            content_type = response.headers.get("content-type", "")
            if "image/" not in content_type.lower():
                raise RemoteCacheError(502, "上游返回的不是图片")

            content_length = response.headers.get("content-length", "")
            if content_length.isdigit() and int(content_length) > max_bytes:
                raise RemoteCacheError(502, "外链图片超出大小上限")

            ext = url_ext or _ext_from_content_type(content_type) or ".bin"
            target = _target_path(library, item_id, kind, ext)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise RemoteCacheError(502, "缓存目录不可写") from exc

            if not is_inside_dir(cache_root(), target):
                raise RemoteCacheError(400, "非法的缓存键")

            tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
            total = 0
            try:
                with tmp.open("wb") as handle:
                    async for chunk in response.aiter_bytes():
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > max_bytes:
                            raise RemoteCacheError(502, "外链图片超出大小上限")
                        handle.write(chunk)
                if total <= 0:
                    raise RemoteCacheError(502, "上游返回空图片")
                os.replace(tmp, target)
            except BaseException:
                try:
                    tmp.unlink()
                except OSError:
                    pass
                raise

    return target


async def _download_with_retry(
    library: str,
    item_id: str,
    kind: str,
    url: str,
    retry: int,
) -> Path:
    attempts = max(0, int(retry)) + 1
    last_reason = ""
    for attempt in range(attempts):
        try:
            return await _download_once(library, item_id, kind, url)
        except _RetryableDownloadError as exc:
            last_reason = str(exc)
        except httpx.HTTPError as exc:
            last_reason = f"{type(exc).__name__}: {exc}"
        if attempt + 1 < attempts:
            logger.info(
                "外链图片下载重试 %s/%s：%s %s（%s）",
                attempt + 1,
                attempts - 1,
                item_id,
                kind,
                last_reason,
            )
    logger.warning("外链图片下载失败：%s %s（%s）", item_id, kind, last_reason)
    raise RemoteCacheError(502, "外链图片下载失败")


async def _ensure_cached(
    library: str,
    item_id: str,
    kind: str,
    url: str,
    retry: int,
) -> Path:
    """未命中时按缓存键加锁，只下载一次。"""
    _validate_url(url)
    cached = _cached_file(library, item_id, kind, url)
    if cached is not None:
        return cached

    state = _loop_state()
    key = (library, item_id, kind, url)
    lock = state.locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        state.locks[key] = lock

    async with lock:
        # 等锁期间可能已被同 key 的另一个请求下载完成
        cached = _cached_file(library, item_id, kind, url)
        if cached is not None:
            return cached
        async with state.semaphore:
            return await _download_with_retry(library, item_id, kind, url, retry)


async def ensure_cached(library: str, item_id: str, kind: str, url: str) -> Path:
    """异步入口：命中直接返回；未命中下载并原子写入缓存。"""
    return await _ensure_cached(
        library,
        item_id,
        kind,
        url,
        retry=int(settings.reference_remote_retry),
    )


def ensure_cached_sync(library: str, item_id: str, kind: str, url: str) -> Path:
    """同步入口（供同步路由复用）。

    若当前线程已处于事件循环中，转到独立线程执行 `asyncio.run`，避免
    "asyncio.run() cannot be called from a running event loop"。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(ensure_cached(library, item_id, kind, url))

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(
            lambda: asyncio.run(ensure_cached(library, item_id, kind, url))
        ).result()


# ---------------------------------------------------------------------------
# 预热（供 tools/warm_reference_cache.py 使用）
# ---------------------------------------------------------------------------


@dataclass
class WarmFailure:
    library: str
    item_id: str
    kind: str
    url: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {
            "library": self.library,
            "item_id": self.item_id,
            "kind": self.kind,
            "url": self.url,
            "reason": self.reason,
        }


@dataclass
class WarmProgress:
    """单个任务完成后的进度快照（`on_progress` 回调入参）。"""

    total: int
    done: int
    cached: int
    downloaded: int
    failed: int
    library: str = ""
    item_id: str = ""
    kind: str = ""


@dataclass
class WarmStats:
    total: int
    cached: int
    downloaded: int
    failed: int
    elapsed_sec: float
    failures: list[WarmFailure] = field(default_factory=list)


class _RateLimiter:
    """令牌间隔限速：`rate_per_sec <= 0` 时不限速。"""

    def __init__(self, rate_per_sec: float):
        self._interval = 1.0 / rate_per_sec if rate_per_sec and rate_per_sec > 0 else 0.0
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    @property
    def enabled(self) -> bool:
        return self._interval > 0

    async def wait(self) -> None:
        if not self.enabled:
            return
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            delay = self._next_at - now
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_at = max(now, self._next_at) + self._interval


async def warm_many(
    jobs: list[tuple[str, str, str, str]],
    *,
    concurrency: int = 8,
    rate_per_sec: float = 0.0,
    retry: int = 2,
    on_progress: Callable[[WarmProgress], None] | None = None,
) -> WarmStats:
    """并发预热：`asyncio.gather` + 信号量，单条失败记录后继续。"""
    started = time.perf_counter()
    total = len(jobs)
    limit = max(1, int(concurrency))
    semaphore = asyncio.Semaphore(limit)
    rate_limiter = _RateLimiter(rate_per_sec)
    counter_lock = asyncio.Lock()
    counters = {"done": 0, "cached": 0, "downloaded": 0, "failed": 0}
    failures: list[WarmFailure] = []

    async def run_one(job: tuple[str, str, str, str]) -> None:
        library, item_id, kind, url = job
        failure: WarmFailure | None = None
        outcome = "downloaded"

        async with semaphore:
            try:
                if not (url or "").strip():
                    raise RemoteCacheError(400, "缺少图片地址")
                _validate_url(url)
                if is_cached(library, item_id, kind, url):
                    outcome = "cached"
                else:
                    if rate_limiter.enabled:
                        await rate_limiter.wait()
                    await _ensure_cached(library, item_id, kind, url, retry)
            except RemoteCacheError as exc:
                outcome = "failed"
                failure = WarmFailure(library, item_id, kind, url, exc.detail)
            except Exception as exc:  # 单条异常不能中断整体预热
                outcome = "failed"
                failure = WarmFailure(
                    library, item_id, kind, url, f"{type(exc).__name__}: {exc}"
                )

        async with counter_lock:
            counters["done"] += 1
            counters[outcome] += 1
            if failure is not None:
                failures.append(failure)
            snapshot = WarmProgress(
                total=total,
                done=counters["done"],
                cached=counters["cached"],
                downloaded=counters["downloaded"],
                failed=counters["failed"],
                library=library,
                item_id=item_id,
                kind=kind,
            )
        if on_progress is not None:
            try:
                on_progress(snapshot)
            except Exception:  # 回调异常不影响预热
                logger.exception("预热进度回调异常")

    if jobs:
        await asyncio.gather(*(run_one(job) for job in jobs))

    return WarmStats(
        total=total,
        cached=counters["cached"],
        downloaded=counters["downloaded"],
        failed=counters["failed"],
        elapsed_sec=time.perf_counter() - started,
        failures=failures,
    )