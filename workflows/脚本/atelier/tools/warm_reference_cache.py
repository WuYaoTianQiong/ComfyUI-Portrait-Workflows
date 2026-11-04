"""CharaDB 外链素材缓存预热工具。

CharaDB 素材仅本机参考，禁止再分发。

读取 ``data/costume-anime-zh.json`` 的 440 套条目，枚举缩略图/原图字段，
通过 ``app.services.reference_remote_cache.warm_many`` 并发下载到本机私有缓存：

- 默认处理全部条目；``--limit`` 只取文件前 N 套，便于抽样与重复执行；
- 已缓存条目通过 ``is_cached`` 跳过，重复执行不会重复下载；
- ``depth`` / ``depth_thumb`` 对 ``costume-anime`` 不缓存，直接跳过并计入 skipped；
- 单条失败不中断，最终按失败数决定退出码（0 成功 / 1 有条目失败 / 2 无法运行）。

本脚本只读取数据文件，写入完全交给缓存服务（``reference_cache_dir``），
不写入 ``data/``、``dist/`` 或数据库。

用法（在 ``脚本/atelier`` 下）::

    python tools/warm_reference_cache.py --help
    python tools/warm_reference_cache.py --limit 8 --concurrency 4
    python tools/warm_reference_cache.py --kinds thumb,image --rate 5 --retry 3
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

#: 缓存预热固定针对外链服装库
LIBRARY = "costume-anime"

#: atelier 根目录（tools 的上一级），用于 ``python tools/xxx.py`` 时导入 app 包
APP_ROOT = Path(__file__).resolve().parents[1]

#: costume-anime 数据文件（相对 reference_root）
DATA_REL = Path("data") / "costume-anime-zh.json"

#: 上游 JSON 中文键 → 缓存 kind
FIELD_MAP: dict[str, str] = {
    "thumb": "缩略图",
    "image": "原图",
}

#: 契约允许的 kind 全集
ALL_KINDS: tuple[str, ...] = ("thumb", "image", "depth", "depth_thumb")

#: 对 costume-anime 真正会写入缓存的 kind
CACHEABLE_KINDS = frozenset(("thumb", "image"))

#: 深度图跳过原因（按 kind 区分，便于统计）
SKIP_REASON: dict[str, str] = {
    "depth": "costume-anime 不缓存深度图",
    "depth_thumb": "costume-anime 不缓存深度缩略图",
}


class DataLoadError(Exception):
    """数据文件缺失、损坏或无可用条目。"""


@dataclass(frozen=True)
class SkippedJob:
    """不参与缓存、计入 skipped 的候选任务。"""

    item_id: str
    kind: str
    reason: str


@dataclass(frozen=True)
class FailureDetail:
    """单条失败明细：条目 id、图片 kind、可读原因。"""

    item_id: str
    kind: str
    reason: str


@dataclass
class RunStats:
    """汇总统计；total 为「条目 x 请求 kind」的候选总数（含 skipped）。"""

    total: int = 0
    cached: int = 0
    skipped: int = 0
    downloaded: int = 0
    failed: int = 0
    elapsed_sec: float = 0.0
    failures: list[FailureDetail] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------


def _parse_kinds(raw: str) -> tuple[str, ...]:
    """解析逗号分隔的 kind 列表；兼容全角逗号，去重保序。"""
    parts = [p.strip().lower() for p in (raw or "").replace("，", ",").split(",")]
    kinds = [p for p in parts if p]
    if not kinds:
        raise argparse.ArgumentTypeError(
            "--kinds 不能为空，可选：thumb,image,depth,depth_thumb"
        )
    unknown = [p for p in kinds if p not in ALL_KINDS]
    if unknown:
        raise argparse.ArgumentTypeError(
            f"不支持的图片类型：{'、'.join(unknown)}；"
            f"可选：{','.join(ALL_KINDS)}"
        )
    return tuple(dict.fromkeys(kinds))


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(f"需要正整数：{raw}") from exc
    if value < 1:
        raise argparse.ArgumentTypeError(f"需要正整数：{raw}")
    return value


def _non_negative_int(raw: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(f"需要非负整数：{raw}") from exc
    if value < 0:
        raise argparse.ArgumentTypeError(f"需要非负整数：{raw}")
    return value


def _non_negative_float(raw: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(f"需要非负数字：{raw}") from exc
    if value < 0:
        raise argparse.ArgumentTypeError(f"需要非负数字：{raw}")
    return value


def build_parser() -> argparse.ArgumentParser:
    """构造命令行解析器；全部 help 文案使用简体中文。"""
    parser = argparse.ArgumentParser(
        prog="warm_reference_cache.py",
        description=(
            "预热 CharaDB 外链素材（costume-anime）到本机私有缓存。\n"
            "CharaDB 素材仅本机参考，禁止再分发。\n\n"
            "读取 data/costume-anime-zh.json 的条目，枚举缩略图/原图字段，"
            "通过缓存服务并发下载；已缓存条目自动跳过，可重复执行实现断点续跑。\n"
            "本脚本不写入 data/、dist/ 或数据库。"
        ),
        epilog=(
            "示例：\n"
            "  python tools/warm_reference_cache.py --help\n"
            "  python tools/warm_reference_cache.py --limit 8 --concurrency 4\n"
            "  python tools/warm_reference_cache.py --kinds thumb,image --rate 5 --retry 3\n"
            "  python tools/warm_reference_cache.py "
            "--kinds thumb,image,depth,depth_thumb\n\n"
            "退出码：0 全部成功；1 存在失败条目；2 无法运行（数据/服务未就绪）。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--limit",
        type=_non_negative_int,
        default=0,
        metavar="N",
        help="只处理数据文件前 N 套条目（按文件顺序），用于抽样；0 或省略表示全部",
    )
    parser.add_argument(
        "--concurrency",
        type=_positive_int,
        default=8,
        metavar="N",
        help="并发下载数，默认 8；必须大于等于 1",
    )
    parser.add_argument(
        "--rate",
        type=_non_negative_float,
        default=0.0,
        metavar="R",
        help="每秒最多发起的下载请求数；0 表示不限速（默认）",
    )
    parser.add_argument(
        "--retry",
        type=_non_negative_int,
        default=2,
        metavar="N",
        help="单个文件下载失败后的重试次数（不含首次），默认 2",
    )
    parser.add_argument(
        "--kinds",
        type=_parse_kinds,
        default=("thumb", "image"),
        metavar="KINDS",
        help=(
            "逗号分隔的图片类型，可选 thumb,image,depth,depth_thumb；"
            "默认 thumb,image。costume-anime 的 depth/depth_thumb 会跳过并计入 skipped"
        ),
    )
    return parser


# ---------------------------------------------------------------------------
# 数据读取与任务枚举
# ---------------------------------------------------------------------------


def _ensure_app_path() -> None:
    """``python tools/xxx.py`` 时 sys.path[0] 是 tools，需补上 atelier 根。"""
    root = str(APP_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def resolve_data_path() -> Path:
    """定位 costume-anime 数据文件；复用参考库的 reference_root（已解析 junction）。"""
    _ensure_app_path()
    from app.services.reference_library import reference_root

    return reference_root() / DATA_REL


def load_items(path: Path) -> list[dict[str, Any]]:
    """读取并校验数据文件；顶层必须是数组，元素必须是对象。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DataLoadError(f"无法读取数据文件：{path}（{exc}）") from exc
    except ValueError as exc:
        raise DataLoadError(f"数据文件不是合法 JSON：{path}（{exc}）") from exc

    if not isinstance(raw, list):
        raise DataLoadError(f"数据文件顶层不是数组：{path}")

    items = [obj for obj in raw if isinstance(obj, dict)]
    if not items:
        raise DataLoadError(f"数据文件没有可用的对象条目：{path}")
    return items


def _text(value: Any) -> str:
    """把上游字段归一为非空字符串；None/空值返回空串。"""
    if value is None:
        return ""
    return str(value).strip()


def _item_id(obj: dict[str, Any]) -> str:
    return _text(obj.get("id"))


def _resolve_urls(obj: dict[str, Any]) -> dict[str, str]:
    """按 DTO 契约解析每个 kind 对应的外链 URL。

    C-REF-ITEM-DTO@2：``thumb_url`` 缺失时回退 ``image``，``image_url``
    缺失时回退 ``thumb``；两者都缺失才视为无可用地址。
    """
    thumb = _text(obj.get(FIELD_MAP["thumb"]))
    image = _text(obj.get(FIELD_MAP["image"]))
    return {
        "thumb": thumb or image,
        "image": image or thumb,
    }


def build_jobs(
    items: list[dict[str, Any]],
    kinds: Sequence[str],
    limit: int,
) -> tuple[list[tuple[str, str, str, str]], list[SkippedJob], list[FailureDetail]]:
    """枚举 (library, item_id, kind, url) 任务，并分出 skipped 与数据异常。

    - depth/depth_thumb 对 costume-anime 一律跳过，计入 skipped；
    - 条目缺少 id 属于数据异常，按 kind 记入失败明细（不进入缓存服务）；
    - 图片地址缺失的 kind 计入 skipped；
    - ``limit > 0`` 时只取文件前 N 套，保证重复执行命中同一批缓存。
    """
    selected = items[:limit] if limit > 0 else items
    jobs: list[tuple[str, str, str, str]] = []
    skipped: list[SkippedJob] = []
    data_failures: list[FailureDetail] = []

    for obj in selected:
        item_id = _item_id(obj)
        urls = _resolve_urls(obj)
        display_id = item_id or "<缺少 id>"

        for kind in kinds:
            if kind not in CACHEABLE_KINDS:
                skipped.append(
                    SkippedJob(display_id, kind, SKIP_REASON[kind])
                )
                continue

            if not item_id:
                data_failures.append(
                    FailureDetail(display_id, kind, "条目缺少 id，无法写入缓存")
                )
                continue

            url = urls.get(kind, "")
            if not url:
                skipped.append(
                    SkippedJob(item_id, kind, "条目缺少可用的图片地址")
                )
                continue

            jobs.append((LIBRARY, item_id, kind, url))

    return jobs, skipped, data_failures


# ---------------------------------------------------------------------------
# 缓存服务调用
# ---------------------------------------------------------------------------


def load_cache_module() -> Any | None:
    """延迟导入缓存服务；未就绪（T4 未完成）时返回 None 并打印提示。"""
    _ensure_app_path()
    try:
        from app.services import reference_remote_cache as cache_module
    except Exception as exc:  # noqa: BLE001 - 导入失败原因多样，需完整暴露
        print(
            "[错误] 无法加载缓存服务 app.services.reference_remote_cache："
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        print(
            "[提示] 该服务由阶段二 T4 提供；请先完成 T4 后再执行实际预热。",
            file=sys.stderr,
        )
        return None

    missing = [
        name
        for name in ("is_cached", "warm_many")
        if not callable(getattr(cache_module, name, None))
    ]
    if missing:
        print(
            "[错误] 缓存服务缺少 C-REMOTE-CACHE@1 要求的接口："
            f"{'、'.join(missing)}",
            file=sys.stderr,
        )
        return None
    return cache_module


def _exception_reason(exc: Exception) -> str:
    """把异常转成可读原因；RemoteCacheError 保留状态码与 detail。"""
    status_code = getattr(exc, "status_code", None)
    detail = getattr(exc, "detail", None)
    if isinstance(detail, str) and detail.strip():
        if status_code is not None:
            return f"{status_code} {detail.strip()}"
        return detail.strip()
    message = str(exc).strip()
    if message:
        return f"{type(exc).__name__}: {message}"
    return type(exc).__name__


def _short(text: str, limit: int = 300) -> str:
    """压缩空白并截断过长的失败原因，避免刷屏。"""
    cleaned = " ".join(str(text).split())
    if len(cleaned) > limit:
        return cleaned[: limit - 1] + "…"
    return cleaned


def _pick(raw: Any, names: Sequence[str]) -> Any:
    """从 dict 或对象中按候选字段名取值。"""
    for name in names:
        if isinstance(raw, dict):
            if name in raw:
                return raw[name]
        else:
            value = getattr(raw, name, None)
            if value is not None:
                return value
    return None


def _normalize_failure(raw: Any) -> FailureDetail:
    """兼容缓存服务返回的失败明细结构，尽量还原 id、kind 与原因。

    T4 的 WarmStats.failures 元素结构由契约实现方决定，这里对 dict、
    对象、元组三种常见形态做兼容；无法识别时保留原始文本。
    """
    item_id = _pick(raw, ("item_id", "entry_id", "id"))
    kind = _pick(raw, ("kind", "image_kind"))
    reason = _pick(raw, ("error", "reason", "message", "detail"))
    job = _pick(raw, ("job", "task"))

    # job 可能是 (library, item_id, kind, url)
    if isinstance(job, (tuple, list)) and len(job) >= 3:
        item_id = item_id or job[1]
        kind = kind or job[2]
        reason = reason or job[-1]

    # raw 自身是元组：优先按 (job, error) 解析，其次按 job 四元组 + error
    if isinstance(raw, (tuple, list)):
        values = list(raw)
        if values and isinstance(values[0], (tuple, list)):
            inner = list(values[0])
            item_id = item_id or (inner[1] if len(inner) >= 3 else None)
            kind = kind or (inner[2] if len(inner) >= 3 else None)
            reason = reason or (values[1] if len(values) > 1 else None)
        elif len(values) >= 5:
            item_id = item_id or values[1]
            kind = kind or values[2]
            reason = reason or values[4]
        elif len(values) == 3:
            item_id = item_id or values[0]
            kind = kind or values[1]
            reason = reason or values[2]

    if item_id is None or kind is None or reason is None:
        return FailureDetail(
            item_id=_short(str(item_id)) if item_id else "?",
            kind=_short(str(kind)) if kind else "?",
            reason=_short(str(reason)) if reason else _short(repr(raw)),
        )
    return FailureDetail(
        item_id=_short(str(item_id)),
        kind=_short(str(kind)),
        reason=_short(str(reason)),
    )


async def _warm(
    jobs: list[tuple[str, str, str, str]],
    args: argparse.Namespace,
    cache_module: Any,
) -> Any:
    """并发预热；禁止串行 for + await，实际并发由 warm_many 负责。"""
    return await cache_module.warm_many(
        jobs,
        concurrency=args.concurrency,
        rate_per_sec=args.rate,
        retry=args.retry,
    )


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def _format_rate(rate: float) -> str:
    return "不限" if rate <= 0 else f"{rate:g}/s"


def _print_summary(stats: RunStats) -> None:
    print(
        "[统计] "
        f"total={stats.total} "
        f"cached={stats.cached} "
        f"skipped={stats.skipped} "
        f"downloaded={stats.downloaded} "
        f"failed={stats.failed} "
        f"elapsed_sec={stats.elapsed_sec:.2f}"
    )


def _print_failures(failures: list[FailureDetail]) -> None:
    for failure in sorted(failures, key=lambda f: (f.item_id, f.kind, f.reason)):
        print(
            f"[失败] id={failure.item_id} "
            f"kind={failure.kind} "
            f"原因={failure.reason}"
        )


def _print_skipped(skipped: list[SkippedJob]) -> None:
    """跳过项按 (kind, 原因) 聚合输出，避免 depth 全量时刷屏。"""
    counts = Counter((job.kind, job.reason) for job in skipped)
    for (kind, reason), count in sorted(counts.items()):
        print(f"[跳过] {count} 条 kind={kind} 原因={reason}")


def run(args: argparse.Namespace) -> int:
    started = time.perf_counter()

    data_path = resolve_data_path()
    items = load_items(data_path)
    selected_count = len(items[: args.limit]) if args.limit > 0 else len(items)
    jobs, skipped, data_failures = build_jobs(items, args.kinds, args.limit)

    print(f"[数据] 文件={data_path}")
    print(
        f"[数据] 条目总数={len(items)} 本次处理={selected_count} "
        f"候选任务={len(jobs) + len(skipped) + len(data_failures)}"
    )
    print(
        f"[参数] kinds={','.join(args.kinds)} "
        f"limit={args.limit or '全部'} "
        f"concurrency={args.concurrency} "
        f"rate={_format_rate(args.rate)} "
        f"retry={args.retry}"
    )

    cache_module = load_cache_module()
    if cache_module is None:
        return 2

    failures: list[FailureDetail] = list(data_failures)
    cached_count = 0
    precheck_failed = 0
    pending: list[tuple[str, str, str, str]] = []

    # 断点续跑：命中缓存的条目直接跳过，不进入并发下载队列
    for library, item_id, kind, url in jobs:
        try:
            if cache_module.is_cached(library, item_id, kind, url):
                cached_count += 1
                continue
        except Exception as exc:  # noqa: BLE001 - 单条失败不中断整体
            precheck_failed += 1
            failures.append(FailureDetail(item_id, kind, _exception_reason(exc)))
            continue
        pending.append((library, item_id, kind, url))

    downloaded_count = 0
    warm_cached = 0
    warm_failed = 0

    if pending:
        try:
            warm_stats = asyncio.run(_warm(pending, args, cache_module))

        except Exception as exc:  # noqa: BLE001 - 整体异常也要给出可读失败
            reason = f"warm_many 执行异常：{_exception_reason(exc)}"
            failures.extend(
                FailureDetail(item_id, kind, reason)
                for _library, item_id, kind, _url in pending
            )
            warm_failed = len(pending)
        else:
            warm_cached = int(getattr(warm_stats, "cached", 0) or 0)
            downloaded_count = int(getattr(warm_stats, "downloaded", 0) or 0)
            warm_failed = int(getattr(warm_stats, "failed", 0) or 0)

            warm_total = int(getattr(warm_stats, "total", len(pending)) or 0)
            if warm_total != len(pending):
                print(
                    f"[提示] 缓存服务返回 total={warm_total}，"
                    f"本次提交 {len(pending)} 条；统计以脚本枚举为准。",
                    file=sys.stderr,
                )

            raw_failures = list(getattr(warm_stats, "failures", []) or [])
            for raw in raw_failures:
                failures.append(_normalize_failure(raw))
            if warm_failed < len(raw_failures):
                warm_failed = len(raw_failures)
    else:
        print("[提示] 没有待下载任务：全部命中缓存或不需缓存。")

    elapsed = time.perf_counter() - started
    # 失败数取「服务统计 + 预检/数据异常」与失败明细长度的较大值，
    # 避免服务端 failed 与 failures 明细不一致时低估失败数。
    failed_count = len(data_failures) + precheck_failed + warm_failed
    if failed_count < len(failures):
        failed_count = len(failures)
    stats = RunStats(
        total=len(jobs) + len(skipped) + len(data_failures),
        cached=cached_count + warm_cached,
        skipped=len(skipped),
        downloaded=downloaded_count,
        failed=failed_count,
        elapsed_sec=elapsed,
        failures=failures,
    )

    _print_summary(stats)
    _print_skipped(skipped)
    _print_failures(stats.failures)
    if stats.failed > len(stats.failures):
        print(
            f"[提示] 另有 {stats.failed - len(stats.failures)} 条失败未提供明细。",
            file=sys.stderr,
        )

    # 失败数优先取明细长度，避免服务端 failed 与 failures 不一致时低估
    if stats.failed > 0:
        print(
            f"[结果] 存在 {stats.failed} 条失败，退出码 1。",
            file=sys.stderr,
        )
        return 1

    print("[结果] 全部成功，退出码 0。")
    return 0


def _configure_stdout() -> None:
    """Windows 控制台/管道下尽量使用 UTF-8，避免中文输出乱码。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


def main(argv: Sequence[str] | None = None) -> int:
    _configure_stdout()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return run(args)
    except DataLoadError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(
            "[中断] 用户中止预热；已写入的缓存保留，可直接再次执行续跑。",
            file=sys.stderr,
        )
        return 130
    except Exception as exc:  # noqa: BLE001 - 顶层兜底，保证退出码可读
        print(
            f"[错误] 预热失败：{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())