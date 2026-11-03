"""HEIC/HEIF 支持：格式识别、缩略图/预览、投喂前转 PNG。"""
import shutil

from PIL import Image

from app.services import image_formats  # noqa: F401  确保解码器已注册
from app.services.paths import IMAGE_EXTENSIONS
from app.services.workflow_parser import inject_input_image


def make_heic(path, size=(64, 48), color=(100, 50, 200)):
    Image.new("RGB", size, color).save(path, format="HEIF")
    return path


def test_heic_is_whitelisted_and_detected_by_content(tmp_path):
    assert ".heic" in IMAGE_EXTENSIONS
    assert ".heif" in IMAGE_EXTENSIONS

    heic = make_heic(tmp_path / "原图.heic")
    renamed = tmp_path / "111.jpg"
    shutil.copy2(heic, renamed)

    assert image_formats.is_heif(heic)
    # 扩展名改成 .jpg，仍要按文件头识别为 HEIC
    assert image_formats.is_heif(renamed)


def test_inject_input_image_converts_heic_to_png(tmp_path):
    wf = {"1": {"class_type": "LoadImage", "inputs": {"image": "x"}}}
    source = make_heic(tmp_path / "原名.heic")
    dest_dir = tmp_path / "input"

    name = inject_input_image(
        wf, str(source), str(dest_dir),
        node_id="1", dest_name="atelier_upscale/hash/原名.heic",
    )

    assert wf["1"]["inputs"]["image"] == name
    assert name.endswith(".png")
    assert "/" in name, "input 子目录写法不能被 Path 改成分隔符"
    converted = dest_dir / name
    assert converted.is_file()
    with Image.open(converted) as im:
        assert im.format == "PNG"
        assert im.size == (64, 48)


def test_inject_input_image_handles_misnamed_jpg(tmp_path):
    wf = {"1": {"class_type": "LoadImage", "inputs": {"image": "x"}}}
    heic = make_heic(tmp_path / "tmp.heic")
    source = tmp_path / "111.jpg"
    shutil.copy2(heic, source)

    name = inject_input_image(
        wf, str(source), str(tmp_path / "input"),
        node_id="1", dest_name="atelier_fs_abc_111.jpg",
    )
    assert name == "atelier_fs_abc_111.png"
    with Image.open(tmp_path / "input" / name) as im:
        assert im.format == "PNG"


def test_browser_endpoints_support_heic(api, tmp_path):
    make_heic(tmp_path / "a.heic")
    shutil.copy2(tmp_path / "a.heic", tmp_path / "b.jpg")

    listing = api.get("/api/browser/list", params={"path": str(tmp_path)})
    assert listing.status_code == 200
    names = [item["name"] for item in listing.json()["images"]]
    assert "a.heic" in names and "b.jpg" in names

    # 缩略图必须是真的 WebP（RIFF 头），而不是 PNG 占位图
    thumb = api.get("/api/browser/thumb", params={"path": str(tmp_path / "a.heic"), "size": 120})
    assert thumb.status_code == 200
    assert thumb.headers["content-type"] == "image/webp"
    assert thumb.content[:4] == b"RIFF"

    # 原图预览：HEIC 在浏览器里不可渲染，接口应返回转换后的 WebP
    view = api.get("/api/browser/image", params={"path": str(tmp_path / "b.jpg")})
    assert view.status_code == 200
    assert view.headers["content-type"] == "image/webp"
    assert view.content[:4] == b"RIFF"
