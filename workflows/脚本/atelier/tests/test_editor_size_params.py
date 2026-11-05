"""编辑端点尺寸参数：非法值 400、空值保持默认、caps 不支持时后端二次防护。"""


def _batch_payload(**extra) -> dict:
    # 参数校验在读取素材/工作流之前发生，这里的路径不需要真实存在
    return {"main_paths": ["dummy.png"], "workflow_path": "dummy.json", **extra}


def test_invalid_orientation_is_400(api):
    resp = api.post("/api/editor/faceswap/batch", json=_batch_payload(orientation="diagonal"))
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "orientation" in detail
    assert "portrait" in detail and "landscape" in detail


def test_invalid_aspect_ratio_is_400(api):
    resp = api.post("/api/editor/faceswap/batch", json=_batch_payload(aspect_ratio="5:4"))
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "aspect_ratio" in detail
    assert "16:9" in detail and "9:16" in detail


def test_invalid_quality_is_400(api):
    resp = api.post("/api/editor/faceswap/batch", json=_batch_payload(quality="3.0x"))
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "quality" in detail
    assert "0.75x" in detail and "2.0x" in detail



def test_resolve_size_params_defaults_when_caps_unsupported():
    """Qwen21（quality/orientation=false）即使误传三值也一律回默认。"""
    from app.routers import editor as editor_router

    assert editor_router._resolve_size_params(
        {"quality": False, "orientation": False}, "1.5x", "16:9", "landscape",
    ) == (editor_router.QUALITY, "", editor_router.ORIENTATION)


def test_resolve_size_params_keeps_when_supported():
    from app.routers import editor as editor_router

    assert editor_router._resolve_size_params(
        {"quality": True, "orientation": True}, "1.5x", "16:9", "landscape",
    ) == ("1.5x", "16:9", "landscape")


def test_resolve_size_params_partial_caps():
    """只有 quality 旋钮时，比例/朝向仍回默认。"""
    from app.routers import editor as editor_router

    assert editor_router._resolve_size_params(
        {"quality": True, "orientation": False}, "1.5x", "16:9", "landscape",
    ) == ("1.5x", "", editor_router.ORIENTATION)