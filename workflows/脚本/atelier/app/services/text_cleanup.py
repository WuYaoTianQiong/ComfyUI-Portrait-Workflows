"""后期清理：检测红印章/文字并做局部擦除。

负向提示词只能概率性减少杂字；这里提供确定性兜底：
- 红印章：HSV 红色掩膜 + 轮廓，适合落款印章、红色小字；
- 文字：RapidOCR 检测文本框，适合「绝对不要文字」的图；
- 擦除：OpenCV inpaint（TELEA），只改掩膜区域，生成新图不覆盖原图。

OCR 依赖是可选安装：缺失时 seals 模式仍可用，text 模式返回明确错误。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover - requirements 已声明，保留降级提示
    cv2 = None
    np = None

_ENGINE = None


@dataclass(frozen=True)
class CleanupBox:
    x1: int
    y1: int
    x2: int
    y2: int
    kind: str
    text: str = ""
    score: float = 0.0

    def as_dict(self) -> dict:
        return {
            "x1": self.x1,
            "y1": self.y1,
            "x2": self.x2,
            "y2": self.y2,
            "kind": self.kind,
            "text": self.text,
            "score": round(self.score, 4),
        }


def capabilities() -> dict:
    """前端据此隐藏不可用的清理模式。"""
    import importlib.util

    return {
        "seals": cv2 is not None and np is not None,
        "text": importlib.util.find_spec("rapidocr_onnxruntime") is not None,
    }


def _require_cv() -> None:
    if cv2 is None or np is None:
        raise RuntimeError("缺少 opencv/numpy，无法执行后期清理；请安装 requirements.txt")


def _read(image_path: str | Path):
    _require_cv()
    # Windows 下 cv2.imread 对中文/× 等 Unicode 路径会静默失败，用 fromfile+imdecode。
    data = np.fromfile(str(image_path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
    if image is None:
        raise FileNotFoundError(f"图片无法读取: {image_path}")
    return image


def detect_red_seals(image_path: str | Path, min_area: int = 30) -> list[CleanupBox]:
    """检测红色印章/红色落款；限制面积，避免把红色衣服/妆容整块擦掉。"""
    image = _read(image_path)
    h, w = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 90, 60), (10, 255, 255)) | cv2.inRange(
        hsv, (170, 90, 60), (180, 255, 255)
    )
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    max_area = max(1, int(h * w * 0.02))
    boxes: list[CleanupBox] = []
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        area = bw * bh
        if area < min_area or area > max_area:
            continue
        if bw < 4 or bh < 4:
            continue
        boxes.append(CleanupBox(x, y, x + bw, y + bh, "seal"))
    boxes.sort(key=lambda b: (b.y1, b.x1))
    return boxes


def _get_engine():
    global _ENGINE
    if _ENGINE is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "缺少 rapidocr-onnxruntime，无法检测文字；可只用「去红印章」"
            ) from exc
        _ENGINE = RapidOCR()
    return _ENGINE


def detect_text_boxes(image_path: str | Path, min_score: float = 0.5) -> list[CleanupBox]:
    engine = _get_engine()
    result, _ = engine(str(image_path))
    boxes: list[CleanupBox] = []
    for item in result or []:
        try:
            points, text, score = item
            score = float(score)
        except (TypeError, ValueError):
            continue
        if score < min_score or not str(text).strip():
            continue
        xs = [float(p[0]) for p in points]
        ys = [float(p[1]) for p in points]
        boxes.append(
            CleanupBox(
                int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)),
                "text", str(text).strip(), score,
            )
        )
    boxes.sort(key=lambda b: (b.y1, b.x1))
    return boxes


def detect_boxes(image_path: str | Path, mode: str = "seals") -> list[CleanupBox]:
    mode = (mode or "seals").lower()
    if mode == "seals":
        return detect_red_seals(image_path)
    if mode == "text":
        return detect_text_boxes(image_path)
    if mode == "all":
        seals = detect_red_seals(image_path)
        texts = detect_text_boxes(image_path)
        # 印章区域内的 OCR 框不重复擦除
        kept: list[CleanupBox] = list(seals)
        for box in texts:
            cx, cy = (box.x1 + box.x2) / 2, (box.y1 + box.y2) / 2
            if any(s.x1 <= cx <= s.x2 and s.y1 <= cy <= s.y2 for s in seals):
                continue
            kept.append(box)
        return kept
    raise ValueError(f"未知清理模式: {mode}")


def build_mask(shape: tuple[int, int], boxes: list[CleanupBox], padding: int = 6):
    _require_cv()
    h, w = shape
    mask = np.zeros((h, w), dtype=np.uint8)
    pad = max(0, int(padding))
    for box in boxes:
        x1 = max(0, min(w - 1, box.x1 - pad))
        y1 = max(0, min(h - 1, box.y1 - pad))
        x2 = max(0, min(w, box.x2 + pad))
        y2 = max(0, min(h, box.y2 + pad))
        if x2 > x1 and y2 > y1:
            cv2.rectangle(mask, (x1, y1), (x2, y2), 255, thickness=-1)
    if boxes:
        mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)
    return mask


def cleanup_image(
    image_path: str | Path,
    output_path: str | Path,
    mode: str = "seals",
    padding: int = 6,
    boxes: list[CleanupBox] | None = None,
) -> tuple[int, list[CleanupBox]]:
    """检测并擦除，返回 (擦除区域数, 检测框)；没有检测到时也会写出原图副本。"""
    image = _read(image_path)
    if boxes is None:
        boxes = detect_boxes(image_path, mode)
    mask = build_mask((image.shape[0], image.shape[1]), boxes, padding)
    cleaned = cv2.inpaint(image, mask, 3, cv2.INPAINT_TELEA) if boxes else image
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(output.suffix or ".png", cleaned)
    if not ok:
        raise OSError(f"无法写入清理结果: {output}")
    encoded.tofile(str(output))
    return len(boxes), boxes
