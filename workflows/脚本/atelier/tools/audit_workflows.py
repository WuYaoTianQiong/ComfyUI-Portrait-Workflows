"""检查根目录工作流是否符合 Atelier 接入规范。

运行（在 脚本/atelier 下）：
    python tools/audit_workflows.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.services import workflow_catalog  # noqa: E402
from app.services.workflow_manifest import MANIFEST_FILENAME  # noqa: E402
from app.services.workflow_parser import (  # noqa: E402
    CANONICAL_RATIOS,
    detect_workflow_caps,
    detect_workflow_params,
    is_video_workflow,
    load_workflow,
)

LATENT_TYPES = {"EmptyLatentImage", "EmptySD3LatentImage", "EmptyFlux2LatentImage"}
TEXT_NODES = {"CLIPTextEncode", "TextEncodeQwenImage21", "TextEncodeQwenImageEdit",
              "TextEncodeQwenImageEditPlus"}
SPECIAL_NODES = {"SeedVR2VideoUpscaler", "LoadImage"}


def classify(workflow: dict) -> str:
    if is_video_workflow(workflow):
        return "video"
    classes = {n.get("class_type") for n in workflow.values() if isinstance(n, dict)}
    if "LoadImage" in classes or "LoadImageMask" in classes:
        return "special"
    if SPECIAL_NODES & classes and not (classes & LATENT_TYPES):
        return "special"
    if not (classes & TEXT_NODES):
        return "utility"
    return "t2i"


def _audit_dirs() -> list[Path]:
    """通用工作流与图库专用工作流都参与审计；同一文件只算一次。"""
    candidates = [
        *workflow_catalog.search_dirs(),
        settings.library_root / "图库专用工作流",
    ]
    out: list[Path] = []
    seen: set[str] = set()
    for directory in candidates:
        key = str(directory).lower()
        if key in seen or not directory.is_dir():
            continue
        seen.add(key)
        out.append(directory)
    return out


def main() -> int:
    problems: list[str] = []
    warnings: list[str] = []
    rows: list[tuple[str, str, str]] = []
    seen_files: set[str] = set()

    files = []
    for directory in _audit_dirs():
        for file in sorted(directory.glob("*.json")):
            if file.name == MANIFEST_FILENAME or file.name.startswith("."):
                continue
            key = str(file).lower()
            if key in seen_files:
                continue
            seen_files.add(key)
            files.append(file)

    for file in files:
        try:
            workflow = load_workflow(str(file))
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{file.name}: 无法解析：{exc}")
            continue

        kind = classify(workflow)
        caps = detect_workflow_caps(workflow)
        params = detect_workflow_params(workflow)
        ratios = params.get("aspect_ratios") or []
        default_ratio = params.get("default_ratio") or ""
        quality_mode = params.get("quality_mode") or "none"

        prefix = ""
        for node in workflow.values():
            if isinstance(node, dict) and "Save" in str(node.get("class_type", "")):
                value = node.get("inputs", {}).get("filename_prefix")
                prefix = "linked" if isinstance(value, list) else str(value or "")
                break
        if not prefix:
            prefix = "由工作流决定"

        if kind == "t2i":
            if not caps.get("prompt"):
                problems.append(f"{file.name}: 文生图缺少可识别的文本编码节点")
            if quality_mode == "none":
                problems.append(f"{file.name}: 无法识别分辨率注入方式")
            if set(ratios) != set(CANONICAL_RATIOS):
                problems.append(f"{file.name}: 比例不完整，实际 {ratios}")
            if default_ratio not in ratios:
                problems.append(f"{file.name}: 默认比例 {default_ratio!r} 不在支持列表")
            if not prefix:
                warnings.append(f"{file.name}: SaveImage 没有 filename_prefix")

        rows.append((kind, file.name, f"{quality_mode} / {default_ratio or '-'} / "
                                        f"{len(ratios)} ratios / prefix={prefix or '-'}"))

    for kind, name, detail in rows:
        print(f"[{kind:7}] {name}\n           {detail}")
    print()
    for msg in warnings:
        print(f"WARN  {msg}")
    for msg in problems:
        print(f"ERROR {msg}")

    t2i = sum(1 for kind, _, _ in rows if kind == "t2i")
    print(f"\n共 {len(rows)} 个工作流，其中文生图 {t2i} 个；"
          f"错误 {len(problems)}，警告 {len(warnings)}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
