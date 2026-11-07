"""缩略图强缓存契约：内容版本 + 分层缓存头。

背景：画廊首屏 60 张图会发 40 个缩略图请求，此前所有分支都是 `no-cache`，
每次刷新都逐个回源，networkidle 要等 2.3s。现在按来源分层：

- `/api/images` 透出 `version`（源文件 `st_mtime_ns` 十进制字符串）→ 前端拼进缩略图 URL；
- `/api/media/thumbnail` 命中本地缩略图缓存 → `immutable`（内容版本已进 URL）；
- 远程回退即时生成（结果不落缩略图缓存）→ `max-age=300`；
- missing 占位图 → `no-store`（否则原图恢复后浏览器仍显示裂图）；
- `/api/media/image`（原图）保持 `no-cache`，原图可能被重新生成，不能长期缓存。
"""

import os

from PIL import Image as PILImage

from app.config import settings

IMMUTABLE = "public, max-age=31536000, immutable"
SHORT_LIVED = "public, max-age=300"


def _write_png(path, color=(200, 30, 30)) -> None:
    """写一张真实（能被 PIL 打开）的小 PNG，缩略图生成才有意义。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with PILImage.new("RGB", (8, 8), color) as img:
        img.save(path, "PNG")


def _output_path(name: str):
    return settings.output_dir / name


# ---------------------------------------------------------------------------
# /api/images 的 version
# ---------------------------------------------------------------------------

def test_history_exposes_source_version_as_string(api, seed_history):
    """version 必须是 st_mtime_ns 的字符串（不是 number），且与磁盘一致。"""
    path = _output_path("version_probe.png")
    _write_png(path)
    try:
        seed_history(filename=path.name)
        item = api.get("/api/images?page_size=5").json()["items"][0]
        assert "version" in item, "画廊响应缺 version 字段"
        assert isinstance(item["version"], str), "version 必须是字符串（避免 JS 精度丢失）"
        assert item["version"] == str(path.stat().st_mtime_ns)
    finally:
        path.unlink(missing_ok=True)


def test_version_changes_when_file_is_overwritten(api, seed_history):
    """同名覆盖：mtime_ns 变化后 version 必须跟着变，缩略图 URL 才会变。"""
    path = _output_path("version_overwrite.png")
    _write_png(path)
    try:
        seed_history(filename=path.name)
        first = api.get("/api/images?page_size=5").json()["items"][0]["version"]
        assert first

        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        second = api.get("/api/images?page_size=5").json()["items"][0]["version"]

        assert second and second != first
        assert second == str(path.stat().st_mtime_ns)
    finally:
        path.unlink(missing_ok=True)


def test_missing_source_falls_back_to_empty_version(api, seed_history):
    """源文件找不到时 version 给空串，前端据此回落记录 id。"""
    seed_history(filename="never_on_disk.png")
    item = api.get("/api/images?page_size=5").json()["items"][0]
    assert item["missing"] is True
    assert item["version"] == ""


# ---------------------------------------------------------------------------
# /api/media/thumbnail 的分层缓存头
# ---------------------------------------------------------------------------

def test_thumbnail_cache_hit_is_immutable(api):
    """本地缩略图缓存命中 → 一年 + immutable，二次刷新直接走浏览器磁盘缓存。"""
    path = _output_path("immutable_hit.png")
    _write_png(path)
    try:
        params = {"filename": path.name, "subfolder": "", "type": "output", "size": 300}
        first = api.get("/api/media/thumbnail", params=params)
        assert first.status_code == 200
        assert first.headers["content-type"] == "image/webp"

        # 第二次必然命中 generate_thumbnail 的磁盘缓存
        second = api.get("/api/media/thumbnail", params=params)
        assert second.status_code == 200
        assert second.headers["cache-control"] == IMMUTABLE
    finally:
        path.unlink(missing_ok=True)


def test_thumbnail_remote_fallback_is_short_lived(api, monkeypatch):
    """本地没有原图、远程即时生成 → 只给 5 分钟，避免长期缓存旧图。"""
    import app.services.assets as assets

    import io

    buf = io.BytesIO()
    with PILImage.new("RGB", (16, 16), (10, 120, 200)) as img:
        img.save(buf, "PNG")

    monkeypatch.setattr(
        assets, "fetch_remote", lambda ref: (buf.getvalue(), "image/png"),
    )

    resp = api.get(
        "/api/media/thumbnail",
        params={"filename": "remote_only.png", "subfolder": "", "type": "output", "size": 300},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/webp"
    assert resp.headers["cache-control"] == SHORT_LIVED


def test_thumbnail_missing_is_no_store(api):
    """文件真的没了 → 占位图必须 no-store，否则原图恢复后仍显示裂图。"""
    resp = api.get(
        "/api/media/thumbnail",
        params={"filename": "gone_forever.png", "subfolder": "", "type": "output", "size": 300},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    assert resp.headers["cache-control"] == "no-store"


# ---------------------------------------------------------------------------
# 原图保持 no-cache（本次不改动）
# ---------------------------------------------------------------------------

def test_original_image_stays_no_cache(api):
    """原图可能被重新生成，/api/media/image 不能跟着上强缓存。"""
    path = _output_path("original_no_cache.png")
    _write_png(path)
    try:
        resp = api.get(
            "/api/media/image",
            params={"filename": path.name, "subfolder": "", "type": "output"},
        )
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-cache"
    finally:
        path.unlink(missing_ok=True)