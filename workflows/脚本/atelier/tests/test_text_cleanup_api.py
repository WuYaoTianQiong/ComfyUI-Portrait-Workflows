"""后期清理 API：生成新图并入库，不覆盖原图。"""

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from app.config import settings  # noqa: E402


def test_cleanup_endpoint_creates_new_image(api, seed_history):
    name = "cleanup_src.png"
    image = np.full((400, 400, 3), 245, dtype=np.uint8)
    cv2.rectangle(image, (50, 50), (90, 90), (0, 0, 220), thickness=-1)
    cv2.imwrite(str(settings.output_dir / name), image)

    row = seed_history(filename=name, subfolder="", img_type="output", source="local")
    resp = api.post(f"/api/images/{row.id}/cleanup", json={"mode": "seals"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["removed"] >= 1
    assert body["filename"].endswith(".png")
    out = settings.output_dir / body["subfolder"] / body["filename"]
    assert out.exists()
    assert out.read_bytes() != (settings.output_dir / name).read_bytes()

    detail = api.get(f"/api/images/{body['image_id']}/detail")
    assert detail.status_code == 200
    assert detail.json()["source"] == "cleanup"


def test_cleanup_endpoint_accepts_manual_boxes(api, seed_history):
    name = "cleanup_manual.png"
    image = np.full((400, 400, 3), 245, dtype=np.uint8)
    cv2.rectangle(image, (120, 120), (200, 180), (30, 30, 30), thickness=-1)
    cv2.imwrite(str(settings.output_dir / name), image)
    row = seed_history(filename=name, subfolder="", img_type="output", source="local")
    resp = api.post(f"/api/images/{row.id}/cleanup", json={
        "boxes": [{"x1": 115, "y1": 115, "x2": 205, "y2": 185}],
        "padding": 4,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["mode"] == "manual"
    assert body["removed"] == 1
    assert body["remaining_red"] == 0
    assert (settings.output_dir / body["subfolder"] / body["filename"]).exists()


def test_manual_box_too_small_warns_remaining_red(api, seed_history):
    name = "cleanup_small_box.png"
    image = np.full((400, 400, 3), 245, dtype=np.uint8)
    cv2.rectangle(image, (120, 120), (180, 180), (0, 0, 220), thickness=-1)
    cv2.imwrite(str(settings.output_dir / name), image)
    row = seed_history(filename=name, subfolder="", img_type="output", source="local")
    resp = api.post(f"/api/images/{row.id}/cleanup", json={
        "boxes": [{"x1": 145, "y1": 145, "x2": 155, "y2": 155}],
        "padding": 2,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["remaining_red"] > 0
    assert "选区可能太小" in body["warning"]


def test_cleanup_endpoint_reports_nothing_detected(api, seed_history):
    name = "cleanup_plain.png"
    image = np.full((120, 160, 3), 245, dtype=np.uint8)
    cv2.imwrite(str(settings.output_dir / name), image)
    row = seed_history(filename=name, subfolder="", img_type="output", source="local")
    resp = api.post(f"/api/images/{row.id}/cleanup", json={"mode": "seals"})
    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert resp.json()["removed"] == 0
