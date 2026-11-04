"""AI 参考图库 · 拼图参考板（M5）。

把参考库条目拼成 1800×1200 的 PNG，只做**导出**，不进 `gen_history`，
也不作为出图输入（atelier 出图直接吃 3–4 张原图，信息量更高）。

版式沿用上游 Web 端（`aiGenerator.ts` 的 `stitchRecipeCanvas`）：
- 画布 1800×1200，深色底；
- 三张图三列、四张图四列；每格等比缩放后居中留边，不裁切、不变形；
- `labels=1` 每格顶部画「图N · 类型」+ 名称，`labels=0` 纯图拼接。

顺序固定为 **人像 → 服装 → 姿势 → 附加**，与上游出图的图1/图2/图3/图4 对齐；
参数里的 `extra` 是第 4 张上传图（M3 落盘在 `library_root/uploads/`），
只接受该目录内的本地文件，避免端点变成任意文件读取器。
"""
from __future__ import annotations

import io
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.services import reference_library, uploads
from app.services.paths import IMAGE_EXTENSIONS, _resolve_if_reparse

#: 导出尺寸：与上游参考板比例一致，不随图片数量变化。
SHEET_WIDTH = 1800
SHEET_HEIGHT = 1200
PADDING = 20

CANVAS_BG = (17, 19, 24)
CARD_BG = (30, 34, 43)
IMAGE_BG = (244, 245, 247)
TAG_COLOR = (161, 161, 170)
NAME_COLOR = (255, 255, 255)

_FONT_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
_FONT_CANDIDATES = (
    _FONT_DIR / "msyhbd.ttc",
    _FONT_DIR / "msyh.ttc",
    _FONT_DIR / "simhei.ttf",
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
)


class SheetError(ValueError):
    """可读的拼图错误：路由统一映射为 400（remote / 缺图 / 非法附加图）。"""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class SheetSlot:
    """一格：类型标签（人像/服装/姿势/附加）、显示名、本地图片路径。"""

    kind: str
    name: str
    path: Path


# ---------------------------------------------------------------------------
# 入参解析
# ---------------------------------------------------------------------------


def _plain(path: Path) -> Path:
    """去掉 `\\\\?\\` 前缀并解析 junction，避免 commonpath 比较错位。"""
    resolved = _resolve_if_reparse(path)
    text = str(resolved)
    if text.startswith("\\\\?\\"):
        return Path(text[4:])
    return resolved


def _inside(base: Path, candidate: Path) -> bool:
    try:
        root = os.path.abspath(os.path.normcase(str(base)))
        target = os.path.abspath(os.path.normcase(str(candidate)))
        return os.path.commonpath([root, target]) == root
    except (OSError, ValueError):
        return False


def _library_slot(kind: str, library: str, item_id: str) -> SheetSlot:
    """按库 id 取 DTO 与本地原图；remote / 不存在 / 缺图统一转 SheetError。"""
    item = reference_library.get_item(library, item_id)
    if item is None:
        raise SheetError(f"{kind}条目不存在：{library}/{item_id}")
    if item["remote"]:
        raise SheetError(f"{kind}条目是外链，不能拼进参考板：{item_id}")

    try:
        path = reference_library.resolve_image(library, item_id, "image")
    except reference_library.ReferenceImageError as exc:
        raise SheetError(f"{kind}图片不可用：{exc.detail}（{item_id}）") from None

    name = item["name"] or item_id
    if library == "pose" and item["angle"]:
        name = f"{name}（{item['angle']}）"
    return SheetSlot(kind=kind, name=name, path=path)


def _extra_slot(raw: str) -> SheetSlot:
    """第 4 张上传图：只允许 `library_root/uploads` 内的本地图片。"""
    base = _plain(uploads.uploads_dir())
    path = Path(raw)
    candidate = _plain(path if path.is_absolute() else base / path)

    if not _inside(base, candidate):
        raise SheetError("附加图必须是上传目录（uploads）内的文件")
    if candidate.suffix.lower() not in IMAGE_EXTENSIONS:
        raise SheetError("附加图不是支持的图片类型")
    try:
        if not candidate.is_file():
            raise SheetError("附加图不存在")
    except OSError:
        raise SheetError("附加图不可读") from None
    return SheetSlot(kind="附加", name="自定义参考图", path=candidate)


def build_slots(
    pose: str = "",
    costume: str = "",
    portrait: str = "",
    extra: str = "",
) -> list[SheetSlot]:
    """按出图顺序收集 1–4 格；一个都没有时 400。"""
    slots: list[SheetSlot] = []
    if portrait.strip():
        slots.append(_library_slot("人像", "portrait", portrait.strip()))
    if costume.strip():
        slots.append(_library_slot("服装", "costume", costume.strip()))
    if pose.strip():
        slots.append(_library_slot("姿势", "pose", pose.strip()))
    if extra.strip():
        slots.append(_extra_slot(extra.strip()))
    if not slots:
        raise SheetError("至少选择一张参考图")
    return slots


# ---------------------------------------------------------------------------
# 绘制
# ---------------------------------------------------------------------------


@lru_cache(maxsize=16)
def _font(size: int):
    """中文字体：优先微软雅黑，缺失时退回 Pillow 内置字体（不阻塞导出）。"""
    for candidate in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(str(candidate), size=size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _flatten(image: Image.Image) -> Image.Image:
    """统一成 RGB；带透明的 PNG 贴白底，避免透明区域变黑。"""
    if image.mode == "P" and "transparency" in image.info:
        image = image.convert("RGBA")
    if image.mode in ("RGBA", "LA"):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(background, rgba).convert("RGB")
    return image.convert("RGB")


def _load_cell(path: Path, box_w: int, box_h: int) -> Image.Image:
    """读取 + 等比缩放（不裁切、不变形），返回可直接 paste 的 RGB 图。"""
    try:
        with Image.open(path) as source:
            # draft 只对 JPEG 有效：先按目标尺寸粗解码，能省一半以上内存和时间
            source.draft("RGB", (box_w * 2, box_h * 2))
            frame = ImageOps.exif_transpose(source)
            frame.load()
            frame = _flatten(frame)
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise SheetError(f"无法读取图片：{path.name}（{exc or type(exc).__name__}）") from None

    if not frame.width or not frame.height:
        raise SheetError(f"图片尺寸异常：{path.name}")

    scale = min(box_w / frame.width, box_h / frame.height)
    size = (
        max(1, min(box_w, round(frame.width * scale))),
        max(1, min(box_h, round(frame.height * scale))),
    )
    # reducing_gap 先做整数倍预缩小：大图降到 573 宽时能省一半时间，且质量不降
    return frame.resize(size, Image.Resampling.LANCZOS, reducing_gap=2.0)


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    """按像素宽度截断并补省略号（中文按字符数粗截，避免长名称反复测量）。"""
    text = text.strip()
    if not text:
        return ""
    if len(text) > 40:
        text = text[:40]
    if draw.textlength(text, font=font) <= max_width:
        return text
    suffix = "…"
    while text and draw.textlength(text + suffix, font=font) > max_width:
        text = text[:-1]
    return (text + suffix) if text else ""


def _draw_label(
    draw: ImageDraw.ImageDraw,
    slot: SheetSlot,
    tag: str,
    x: int,
    y: int,
    width: int,
    head_height: int,
) -> None:
    inset = max(10, round(width * 0.03))
    tag_font = _font(max(12, round(width * 0.026)))
    name_font = _font(max(16, round(width * 0.036)))
    max_width = width - inset * 2

    draw.text(
        (x + inset, y + round(head_height * 0.16)),
        _fit_text(draw, tag, tag_font, max_width),
        font=tag_font,
        fill=TAG_COLOR,
    )
    draw.text(
        (x + inset, y + round(head_height * 0.48)),
        _fit_text(draw, slot.name, name_font, max_width),
        font=name_font,
        fill=NAME_COLOR,
    )


def render(slots: list[SheetSlot], labels: bool = True) -> Image.Image:
    """把 1–4 格拼成 1800×1200；列宽按数量均分，整体水平居中。"""
    count = len(slots)
    column_width = (SHEET_WIDTH - PADDING * (count + 1)) // count
    total_width = column_width * count + PADDING * (count + 1)
    left = (SHEET_WIDTH - total_width) // 2

    card_height = SHEET_HEIGHT - PADDING * 2
    head_height = max(52, min(88, round(column_width * 0.13))) if labels else 0
    image_height = card_height - head_height
    if image_height <= 0:
        raise SheetError("参考板尺寸不足以容纳标题条")

    canvas = Image.new("RGB", (SHEET_WIDTH, SHEET_HEIGHT), CANVAS_BG)
    draw = ImageDraw.Draw(canvas)

    for index, slot in enumerate(slots):
        x = left + PADDING + index * (column_width + PADDING)
        y = PADDING
        right = x + column_width - 1
        bottom = y + card_height - 1

        draw.rectangle([x, y, right, bottom], fill=CARD_BG if labels else IMAGE_BG)
        if labels:
            draw.rectangle([x, y + head_height, right, bottom], fill=IMAGE_BG)

        cell = _load_cell(slot.path, column_width, image_height)
        canvas.paste(
            cell,
            (
                x + (column_width - cell.width) // 2,
                y + head_height + (image_height - cell.height) // 2,
            ),
        )

        if labels:
            _draw_label(draw, slot, f"图{index + 1} · {slot.kind}", x, y, column_width, head_height)

    return canvas


#: 最近导出缓存：同一组合重复下载不必重新解码 4 张大图（8 组约 7MB）。
_OUTPUT_CACHE: "OrderedDict[tuple, bytes]" = OrderedDict()
_CACHE_LOCK = threading.RLock()
_CACHE_SIZE = 8


def _mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return -1


def _cache_key(slots: list[SheetSlot], labels: bool) -> tuple:
    marks = tuple(
        (str(slot.path), _mtime_ns(slot.path), slot.kind, slot.name)
        for slot in slots
    )
    return (marks, labels)


def clear_cache() -> None:
    """测试与热更新用：清空导出缓存。"""
    with _CACHE_LOCK:
        _OUTPUT_CACHE.clear()


def render_png(
    pose: str = "",
    costume: str = "",
    portrait: str = "",
    extra: str = "",
    labels: bool = True,
) -> bytes:
    """返回 PNG 字节；`compress_level=3` 在体积与 300ms 目标之间取平衡。

    同一组合（路径 + mtime 不变）命中缓存，换图后 mtime 变化自动失效。
    """
    slots = build_slots(pose, costume, portrait, extra)
    key = _cache_key(slots, labels)

    with _CACHE_LOCK:
        cached = _OUTPUT_CACHE.get(key)
        if cached is not None:
            _OUTPUT_CACHE.move_to_end(key)
            return cached

    image = render(slots, labels=labels)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=3)
    data = buffer.getvalue()

    with _CACHE_LOCK:
        _OUTPUT_CACHE[key] = data
        _OUTPUT_CACHE.move_to_end(key)
        while len(_OUTPUT_CACHE) > _CACHE_SIZE:
            _OUTPUT_CACHE.popitem(last=False)
    return data