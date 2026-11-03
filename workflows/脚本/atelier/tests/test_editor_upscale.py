"""批量超分页复用的后端能力：保留源图名、档位注入、保存节点子目录。"""
import json

from app.models import GenJob
from app.services.image_inputs import clean_dest_name
from app.services.workflow_parser import set_save_subfolder

WORKFLOW = {
    "1": {"class_type": "LoadImage", "inputs": {"image": "example.png"}},
    "2": {
        "class_type": "SaveImageFromSource",
        "inputs": {
            "images": ["1", 0], "suffix": "超分-7BQ4", "subfolder": "",
            "with_source_name": True, "with_size": True, "with_datetime": False,
        },
    },
    "3": {
        "class_type": "SeedVR2VideoUpscaler",
        "inputs": {"image": ["1", 0]},
    },
}


def _write_images(tmp_path):
    paths = []
    for name in ("原图A.png", "原图B.png"):
        path = tmp_path / name
        path.write_bytes(b"not-a-real-image")
        paths.append(str(path))
    return paths


def test_clean_dest_name_keeps_original_basename():
    first = clean_dest_name({"path": r"F:\pics\A.png", "name": "A.png"})
    second = clean_dest_name({"path": r"f:\PICS\a.png", "name": "A.png"})
    assert first == second, "同一素材必须得到同一个 input 路径，否则会被重复拷贝"
    assert first.startswith("atelier_upscale/")
    assert first.split("/")[-1] == "A.png"
    # 不同源图即使同名，也要落在不同子目录，避免互相覆盖
    other = clean_dest_name({"path": r"F:\other\A.png", "name": "A.png"})
    assert other != first


def test_set_save_subfolder_only_touches_saveimage_from_source():
    wf = {
        "1": {"class_type": "SaveImageFromSource", "inputs": {"subfolder": ""}},
        "2": {"class_type": "SaveImage", "inputs": {"filename_prefix": "orig"}},
    }
    assert set_save_subfolder(wf, "2026-11-01/超分") == 1
    assert wf["1"]["inputs"]["subfolder"] == "2026-11-01/超分"
    assert wf["2"]["inputs"]["filename_prefix"] == "orig"

    assert set_save_subfolder(wf, "") == 0
    assert wf["1"]["inputs"]["subfolder"] == "2026-11-01/超分"


def test_faceswap_batch_dry_run_flags_keep_source_name(api, tmp_path):
    paths = _write_images(tmp_path)
    resp = api.post(
        "/api/editor/faceswap/batch",
        json={
            "workflow_content": json.dumps(WORKFLOW),
            "main_paths": paths,
            "quality": "6K",
            "job_label": "批量超分",
            "clean_source_name": True,
            "dry_run": True,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] == 2
    assert all(item["metas"][0]["keep_source_name"] is True for item in data["plan"])


def test_faceswap_batch_prepare_injects_quality_and_clean_name(api, tmp_path, monkeypatch):
    """真跑提交前的 prepare：档位、input 文件名、保存子目录、任务标题都要生效。"""
    import app.routers.editor as editor_router

    captured = {}
    monkeypatch.setattr(editor_router, "enqueue_submission", lambda task: captured.setdefault("task", task))

    paths = _write_images(tmp_path)
    resp = api.post(
        "/api/editor/faceswap/batch",
        json={
            "workflow_content": json.dumps(WORKFLOW),
            "main_paths": paths,
            "quality": "6K",
            "job_label": "批量超分",
            "clean_source_name": True,
            "output_subfolder": "测试输出",
        },
    )
    assert resp.status_code == 200, resp.text
    job = GenJob.get(GenJob.id == resp.json()["job_id"])
    assert job.title == "批量超分 2"
    assert job.quality == "1.25x"
    # 超分工作流没有文本编码节点：不能挂上编辑用的默认提示词
    item = json.loads(job.items)[0]
    assert json.loads(item["prompt_params"])["prompt"] == ""

    api_wf = captured["task"].prepare(0)
    expected = clean_dest_name({"path": paths[0], "name": "原图A.png"})
    assert api_wf["1"]["inputs"]["image"] == expected
    assert api_wf["3"]["inputs"]["resolution"] == 3200
    assert api_wf["3"]["inputs"]["max_resolution"] == 5120
    assert api_wf["2"]["inputs"]["subfolder"] == "测试输出"


def test_combo_limit_is_100(api, tmp_path):
    """多角色全组合上限是 100：100 张可提交，101 张以上拒绝。"""
    two_inputs = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "a.png"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": "b.png"}},
    }

    def make(prefix: str, count: int) -> list[str]:
        out = []
        for i in range(count):
            path = tmp_path / f"{prefix}{i}.png"
            path.write_bytes(b"x")
            out.append(str(path))
        return out

    target = make("t", 11)
    ref = make("r", 10)
    payload = {
        "workflow_content": json.dumps(two_inputs),
        "main_paths": target,
        "ref_paths": ref,
        "dry_run": True,
    }
    resp = api.post("/api/editor/faceswap/batch", json=payload)
    assert resp.status_code == 400
    assert "100" in resp.text

    payload["main_paths"] = target[:10]
    resp = api.post("/api/editor/faceswap/batch", json=payload)
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 100


def test_edit_workflow_still_gets_default_prompt(api, tmp_path, monkeypatch):
    """有文本编码节点的编辑工作流，留空提示词时仍要套默认编辑提示。"""
    import app.routers.editor as editor_router

    captured = {}
    monkeypatch.setattr(editor_router, "enqueue_submission", lambda task: captured.setdefault("task", task))

    wf = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "example.png"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": ""}},
        "3": {"class_type": "CLIPLoader", "inputs": {}},
        "4": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "edit"}},
    }
    image = tmp_path / "目标.png"
    image.write_bytes(b"not-a-real-image")
    resp = api.post(
        "/api/editor/faceswap/batch",
        json={"workflow_content": json.dumps(wf), "main_paths": [str(image)]},
    )
    assert resp.status_code == 200, resp.text
    job = GenJob.get(GenJob.id == resp.json()["job_id"])
    item = json.loads(job.items)[0]
    assert json.loads(item["prompt_params"])["prompt"] == (
        "只修改提示词中描述的部分，其余人物相貌、姿势、构图、服装、背景与光线保持与目标图一致，"
        "自然真实，高清细节"
    )
