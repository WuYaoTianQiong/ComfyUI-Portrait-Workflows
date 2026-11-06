"""工作流尺寸能力探测：独立 latent / linked-image 与图生图的判定边界。

2026-11-05 契约变更：
- `linked-image` 模式：Empty*Latent 的 width/height 指向 GetImageSize 时，
  向上回溯到 LoadImage，用图片实际像素作为默认值（文件缺失时用 1024² 占位）；
- 图生图工作流不再一律关闭画质/方向旋钮：只要独立 latent 的宽高可覆盖就继续判定；
- Qwen 系（latent 来自文本编码器）：`resolution` 可映射成像素总量档（quality=True），
  比例仍跟随第一张参考图（orientation=False）。
"""
from __future__ import annotations

from PIL import Image as PILImage

from app.config import settings
from app.services.workflow_parser import (
    _latent_info,
    detect_workflow_caps,
    detect_workflow_params,
    inject_prompt,
    load_workflow,
)

QWEN21 = "图库专用工作流/图库专用_Qwen21+VNCCS_三图_25步_单人.api.json"
#: 该工作流 2026-11-06 因视觉质量不合格已归档（不在 studio 下拉），
#: 但「linked-image 尺寸旋钮」这条 caps 解析路径只有它能覆盖，所以从归档区读。
PORNMASTER = (
    "历史工作流/未采用/PornMaster_Flux2Klein9B_三图角色合成_6步_自动尺寸.api.json"
)


def _load_real(name: str) -> dict:
    path = settings.library_root / name
    assert path.is_file(), f"缺少真实工作流：{path}"
    return load_workflow(str(path))


def _linked_image_workflow() -> dict:
    """最小 PornMaster 结构：LoadImage → ImageScale → GetImageSize → EmptyFlux2Latent。"""
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": "portrait_ref.png"}},
        "5": {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": ["1", 0]}},
        "38": {"class_type": "GetImageSize", "inputs": {"image": ["5", 0]}},
        "39": {
            "class_type": "EmptyFlux2LatentImage",
            "inputs": {"width": ["38", 0], "height": ["38", 1], "batch_size": 1},
        },
    }


def test_qwen21_encoder_resolution_exposes_quality_only():
    """Qwen21 的 latent 在文本编码器内部：resolution 映射像素档，比例仍跟随参考图。"""
    workflow = _load_real(QWEN21)
    info = _latent_info(workflow)
    assert info is not None
    assert info["mode"] == "resolution"
    assert info["base_resolution"] == 1024

    caps = detect_workflow_caps(workflow)
    assert caps["quality"] is True
    assert caps["orientation"] is False

    params = detect_workflow_params(workflow)
    assert params["quality_mode"] == "megapixels"
    assert params["base_megapixels"] == 1.049
    assert params["mp_unit"] == "mp"
    assert params["aspect_ratios"] == []
    assert params["orientation_mode"] == "none"


def test_qwen21_encoder_resolution_injection_scales_linearly():
    """quality 档按线性倍率写到 TextEncodeQwenImage21.resolution；比例输入被忽略。"""
    cases = {"0.75x": 768, "1.0x": 1024, "1.25x": 1280, "1.5x": 1536, "2.0x": 2048}
    for quality, expected in cases.items():
        workflow = _load_real(QWEN21)
        inject_prompt(workflow, {
            "prompt": "测试",
            "seed": 1,
            "quality": quality,
            # 比例在这里无法生效：输出跟随第一张参考图，不能因此报错
            "aspect_ratio": "16:9",
            "orientation": "landscape",
        })
        assert workflow["8"]["inputs"]["resolution"] == expected


def test_qwen21_encoder_resolution_zero_disables_quality():
    """resolution=0 表示参考图各保持原尺寸，没有稳定基准 → 不暴露画质档。"""
    workflow = _load_real(QWEN21)
    workflow["8"]["inputs"]["resolution"] = 0
    assert _latent_info(workflow) is None
    assert detect_workflow_caps(workflow)["quality"] is False
    assert detect_workflow_params(workflow)["quality_mode"] == "none"


def test_pornmaster_linked_image_enables_size_knobs():
    """PornMaster 的宽高来自 GetImageSize，但可写字面量覆盖，旋钮必须可用。"""
    workflow = _load_real(PORNMASTER)
    info = _latent_info(workflow)
    assert info is not None, "linked-image 模式不能再返回 None"
    assert info["mode"] == "linked-image"

    caps = detect_workflow_caps(workflow)
    assert caps["quality"] is True
    assert caps["orientation"] is True


def test_linked_image_uses_actual_pixels(tmp_path, monkeypatch):
    """默认图存在时，宽高取图片实际像素。"""
    monkeypatch.setattr(settings, "comfyui_root", tmp_path)
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    PILImage.new("RGB", (640, 960)).save(input_dir / "portrait_ref.png")

    info = _latent_info(_linked_image_workflow())
    assert info is not None
    assert (info["width"], info["height"]) == (640, 960)
    assert info["ratio"] == "2:3"
    assert "size_source" not in info


def test_linked_image_placeholder_when_default_image_missing(tmp_path, monkeypatch):
    """工作流里的默认图名可能只是占位：文件缺失时用 1024² 兜底，旋钮仍可用。"""
    monkeypatch.setattr(settings, "comfyui_root", tmp_path)
    (tmp_path / "input").mkdir()

    info = _latent_info(_linked_image_workflow())
    assert info is not None
    assert (info["width"], info["height"]) == (1024, 1024)
    assert info["size_source"] == "placeholder"
    assert detect_workflow_caps(_linked_image_workflow())["quality"] is True


def test_linked_image_size_can_be_overridden_by_literal(tmp_path, monkeypatch):
    """注入分辨率时把 GetImageSize 链路替换成字面量宽高。"""
    monkeypatch.setattr(settings, "comfyui_root", tmp_path)
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    PILImage.new("RGB", (640, 960)).save(input_dir / "portrait_ref.png")

    workflow = _linked_image_workflow()
    inject_prompt(workflow, {
        "prompt": "测试",
        "seed": 1,
        "quality": "1.0x",
        "orientation": "portrait",
    })
    assert isinstance(workflow["39"]["inputs"]["width"], int)
    assert isinstance(workflow["39"]["inputs"]["height"], int)

def test_pornmaster_keeps_requested_size_params():
    """PornMaster 的 caps 支持尺寸旋钮，请求里的三值必须原样保留。"""
    from app.routers import editor as editor_router

    caps = detect_workflow_caps(_load_real(PORNMASTER))
    assert editor_router._resolve_size_params(
        caps, "1.5x", "16:9", "landscape",
    ) == ("1.5x", "16:9", "landscape")


def test_workflow_list_exposes_input_count(api):
    """/api/workflows 必须同时经过路由层构造与 WorkflowRow 模型两道，不能漏字段。"""
    resp = api.get("/api/workflows", params={"scope": "studio"})
    assert resp.status_code == 200
    rows = resp.json()["workflows"]
    assert rows, "真实库里的合成台工作流不应为空"
    assert all("input_count" in row for row in rows)

    qwen = next(
        row for row in rows if row["name"] == "图库专用_Qwen21+VNCCS_三图_25步_单人.api.json"
    )
    assert qwen["input_count"] == 3

def test_workflow_list_exposes_slots_in_loadimage_order(api):
    """C-REF-WF-SLOTS@1：scope=studio 每项都带 slots，且顺序 = LoadImage 节点顺序。

    默认 Qwen21 的节点顺序是 姿势 → 人像 → 服装（提示词图号并不是节点顺序），
    所以 slots 必须是 ["pose", "portrait", "costume"]，不能按角色优先级重排。
    """
    resp = api.get("/api/workflows", params={"scope": "studio"})
    assert resp.status_code == 200
    rows = resp.json()["workflows"]
    assert rows
    assert all("slots" in row for row in rows), "合成台每一项都必须带 slots"

    qwen = next(
        row for row in rows if row["name"] == "图库专用_Qwen21+VNCCS_三图_25步_单人.api.json"
    )
    assert qwen["slots"] == ["pose", "portrait", "costume"]
    assert qwen["input_count"] == 3


def test_workflow_list_scope_all_keeps_empty_slots(api):
    """scope=all 行为不变：slots 统一空数组，老调用方不受影响。"""
    resp = api.get("/api/workflows")
    assert resp.status_code == 200
    rows = resp.json()["workflows"]
    assert isinstance(rows, list)
    assert all(row["slots"] == [] for row in rows)