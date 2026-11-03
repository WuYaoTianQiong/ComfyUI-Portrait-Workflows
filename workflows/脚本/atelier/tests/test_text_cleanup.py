"""后期清理：红印章检测、掩膜与 inpaint。"""

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from app.services.text_cleanup import (  # noqa: E402
    CleanupBox,
    build_mask,
    cleanup_image,
    detect_boxes,
    detect_red_seals,
)


def _synthetic(path):
    image = np.full((400, 500, 3), 245, dtype=np.uint8)
    # 红色印章
    cv2.rectangle(image, (60, 60), (100, 100), (0, 0, 220), thickness=-1)
    # 黑色文字块
    cv2.rectangle(image, (260, 80), (420, 120), (10, 10, 10), thickness=-1)
    cv2.imwrite(str(path), image)
    return path


def test_detect_red_seals_finds_stamp(tmp_path):
    src = _synthetic(tmp_path / "in.png")
    boxes = detect_red_seals(src)
    assert boxes
    assert any(b.kind == "seal" for b in boxes)
    box = boxes[0]
    assert box.x1 < 100 and box.x2 > 60 and box.y1 < 100 and box.y2 > 60


def test_build_mask_covers_boxes_with_padding():
    boxes = [CleanupBox(10, 10, 20, 20, "seal")]
    mask = build_mask((100, 100), boxes, padding=4)
    assert mask[10, 10] == 255
    assert mask[25, 25] == 255  # padding + dilation
    assert mask[0, 0] == 0


def test_cleanup_seals_removes_red_pixels(tmp_path):
    src = _synthetic(tmp_path / "in.png")
    out = tmp_path / "out.png"
    removed, boxes = cleanup_image(src, out, "seals", padding=4)
    assert removed == len(boxes) >= 1
    assert out.exists()
    cleaned = cv2.imread(str(out))
    # 印章中心不再保持高饱和纯红
    b, g, r = cleaned[80, 80]
    assert not (int(r) > 180 and int(g) < 40 and int(b) < 40)


def test_unknown_mode_is_rejected(tmp_path):
    src = _synthetic(tmp_path / "in.png")
    with pytest.raises(ValueError):
        detect_boxes(src, "paint")


def test_cleanup_with_explicit_boxes_does_not_require_detection(tmp_path):
    src = _synthetic(tmp_path / "in.png")
    out = tmp_path / "out.png"
    removed, used = cleanup_image(
        src, out, "seals", padding=2,
        boxes=[CleanupBox(60, 60, 100, 100, "seal")],
    )
    assert removed == 1
    assert used[0].kind == "seal"
    assert out.exists()
