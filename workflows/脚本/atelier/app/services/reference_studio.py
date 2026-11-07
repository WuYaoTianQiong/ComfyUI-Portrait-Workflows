"""参考图库合成台的配方引擎。

只负责「槽位 → 工作流」这一层的纯逻辑：角色识别、空槽裁剪、断链检查、
工作流白名单。HTTP 入参/出参与把结果拼成 editor 请求仍留在 router。
"""
from __future__ import annotations

import copy
from pathlib import Path

from app.services.workflow_catalog import list_valid_workflows
from app.services.workflow_parser import (
    find_image_input_keys,
    find_loadimage_nodes,
    image_input_key_index,
    loadimage_role,
)

#: 合成台默认工作流：2026-11-05 T0 三候选实测对比后定为 Qwen21 + VNCCS
#: （三槽齐全 + 姿势 LoRA，25 步单人链路）；空请求一律用它，不再按张数硬绑三图/四图。
#: 默认合成台工作流：四图可选发型（空第 4 槽自动裁成三图，实测 84–97s）。
DEFAULT_STUDIO_WORKFLOW = "图库专用_Qwen21+VNCCS_四图_可选发型_25步_单人.api.json"

#: 槽位描述符：顺序、中文名、来源与能力都从这里派生。
SLOT_DESCRIPTORS = (
    {
        "key": "portrait", "label": "人像", "multiple": True,
        "sources": ("library:portrait", "library:character",
                    "library:costume-anime", "upload"),
        "supports_text": True,
    },
    {
        "key": "costume", "label": "服装", "multiple": True,
        "sources": ("library:costume", "library:costume-anime", "upload"),
        "supports_text": True,
    },
    {
        "key": "pose", "label": "姿势", "multiple": True,
        "sources": ("library:pose", "upload"),
        "supports_text": True,
    },
    {
        # 第 4 槽：发型库背面图 / 上传单图。工作流槽位能力由 manifest/slots 决定。
        "key": "extra", "label": "第 4 张参考", "multiple": False,
        "sources": ("library:hair", "upload"),
        "supports_text": False,
    },
)

SLOT_ROLES = tuple(item["key"] for item in SLOT_DESCRIPTORS)
SLOT_LABELS = {item["key"]: item["label"] for item in SLOT_DESCRIPTORS}
SLOT_BY_KEY = {item["key"]: item for item in SLOT_DESCRIPTORS}

#: 参考图分支上可安全删除的节点类型：删掉它们只会移除这一路参考，
#: 不会影响主链路（KSampler / SaveImage 等不在此列，遇到即停止向下裁剪）。
REFERENCE_BRANCH_TYPES = frozenset({
    "ImageScaleToTotalPixels",
    "ImageScale",
    "ImageScaleBy",
    "ImageResize",
    "ImageResizeKJ",
    "ImageResizeKJv2",
    "VAEEncode",
    "ReferenceLatent",
})


class NotTrimmable(Exception):
    """该工作流的空槽不能安全裁剪（不是纯文本编码器输入，或删了会断主链路）。"""


class StudioWorkflowError(Exception):
    """合成台工作流不在白名单内 / 默认工作流不可用。"""


def downstream_consumers(api_workflow: dict, node_id: str) -> list[tuple[str, str]]:
    """返回引用该节点的下游 (节点 id, 输入键)。"""
    target = str(node_id)
    out: list[tuple[str, str]] = []
    for nid, node in api_workflow.items():
        if not isinstance(node, dict):
            continue
        for key, value in (node.get("inputs") or {}).items():
            if isinstance(value, (list, tuple)) and len(value) == 2 \
                    and str(value[0]) == target:
                out.append((str(nid), key))
    return out


def live_conditioning(api: dict, value, drop: set[str]) -> object:
    """把 conditioning 引用沿「被删的透传节点」向上游解析，返回第一个存活引用。

    多级链会整段被裁（人像 / 服装各一级 ReferenceLatent，正负两条），只做一层替换
    会让 KSampler.positive 指向已删节点，ComfyUI 校验直接 400（KeyError）。
    """
    seen: set[str] = set()
    current = value
    while isinstance(current, (list, tuple)) and len(current) == 2:
        source = str(current[0])
        if source not in drop:
            return list(current)
        if source in seen:
            raise NotTrimmable(source)
        seen.add(source)
        upstream = (api.get(source) or {}).get("inputs") or {}
        current = upstream.get("conditioning")
        if current is None:
            raise NotTrimmable(source)
    raise NotTrimmable(str(current))


def dangling_refs(api: dict, dropped: set[str]) -> list[tuple[str, str, str]]:
    """裁剪后仍指向「本次删掉的节点」的输入；ComfyUI 会以校验 400 拒绝。

    只查本次删掉的节点：工作流文件本身若已有悬空引用（例如最小 mock 里的 clip），
    那不是裁剪的责任，交给 ComfyUI 自己的校验去报。
    """
    missing: list[tuple[str, str, str]] = []
    for node_id, node in api.items():
        if not isinstance(node, dict):
            continue
        for key, value in (node.get("inputs") or {}).items():
            if isinstance(value, (list, tuple)) and len(value) == 2 \
                    and str(value[0]) in dropped:
                missing.append((str(node_id), str(key), str(value[0])))
    return missing


def role_nodes(api_workflow: dict) -> dict[str, str]:
    """按标题把 LoadImage 映射到业务角色；同一角色重复时只认第一个。"""
    out: dict[str, str] = {}
    for node_id, title in find_loadimage_nodes(api_workflow):
        role = loadimage_role(title)
        if role and role not in out:
            out[role] = node_id
    return out


def build_index_map(
    api_workflow: dict, filled: dict[str, bool], nodes: dict[str, str],
) -> dict[str, int]:
    """角色 → 工作流真实图号（images.image_N / imageN 里的 N）。

    裁剪后图位不压缩重排，所以提示词必须按真实图号书写（Qwen21 缺人像时
    服装仍是图3、姿势仍是图1）。没有图片键的工作流（Flux 系）返回空映射，
    提示词退回按出现顺序编号，与实际图位一致。
    """
    index_map: dict[str, int] = {}
    for role in SLOT_ROLES:
        node_id = nodes.get(role)
        if not node_id or not filled.get(role):
            continue
        numbers = [
            image_input_key_index(key)
            for _enc_id, key in find_image_input_keys(api_workflow, node_id)
        ]
        numbers = [number for number in numbers if number]
        if numbers:
            index_map[role] = min(numbers)
    return index_map


def trim_unfilled_slots(
    api_workflow: dict, filled: dict[str, bool],
) -> tuple[dict, dict[str, int]]:
    """在副本上裁掉空槽的参考图分支，返回 (裁剪后工作流, 角色→图号映射)。

    只对“图片通过文本编码器参考图键进入”的 Qwen 系工作流生效：
    · 先删文本编码器里的 images.image_N / imageN 键；
    · 再沿参考图分支删除 ImageScale / VAEEncode / ReferenceLatent；
    · 若被删节点是 conditioning 透传节点，把下游引用改接其上游 conditioning；
    · 其它下游输入（如 KSampler.latent_image）无法直通 → `NotTrimmable`。

    Flux 系把参考图接到 ReferenceLatent.latent 而文本编码器没有图片键，
    直接删节点会在 VAEEncode 上留下悬空输入，因此判定为不可裁剪。
    """
    api = copy.deepcopy(api_workflow)
    nodes = role_nodes(api)
    index_map = build_index_map(api, filled, nodes)

    drop: set[str] = set()
    drop_keys: list[tuple[str, str]] = []

    for role in SLOT_ROLES:
        node_id = nodes.get(role)
        if not node_id or filled.get(role):
            continue
        keys = find_image_input_keys(api, node_id)
        if not keys:
            raise NotTrimmable(role)
        drop_keys.extend(keys)
        drop.add(node_id)

        # 只沿参考图预处理分支向下走；遇到 KSampler / SaveImage 等主链路节点就停。
        stack = [node_id]
        while stack:
            current = stack.pop()
            for consumer_id, key in downstream_consumers(api, current):
                # conditioning / positive / negative 是透传语义：沿它扩散会误删
                # 另一条参考分支（例如服装的 ReferenceLatent），改由直通检查处理
                if key == "conditioning" or key.startswith("conditioning_") \
                        or key in ("positive", "negative"):
                    continue
                consumer = api.get(consumer_id)
                if not isinstance(consumer, dict):
                    continue
                if consumer.get("class_type") not in REFERENCE_BRANCH_TYPES:
                    continue
                if consumer_id in drop:
                    continue
                drop.add(consumer_id)
                stack.append(consumer_id)

    # 被删节点若仍被保留节点引用：只有 conditioning 语义能直通上游
    drop_key_set = set(drop_keys)
    replacements: list[tuple[str, str, object]] = []
    for dropped in drop:
        node = api.get(dropped) or {}
        cond_src = (node.get("inputs") or {}).get("conditioning")
        for consumer_id, key in downstream_consumers(api, dropped):
            if consumer_id in drop or (consumer_id, key) in drop_key_set:
                continue
            transparent = key == "conditioning" or key.startswith("conditioning_") \
                or key in ("positive", "negative")
            if transparent and cond_src is not None:
                replacements.append(
                    (consumer_id, key, live_conditioning(api, cond_src, drop))
                )
                continue
            raise NotTrimmable(dropped)

    for consumer_id, key, value in replacements:
        api[consumer_id].setdefault("inputs", {})[key] = value
    for enc_id, key in drop_keys:
        inputs = api.get(enc_id, {}).get("inputs")
        if isinstance(inputs, dict):
            inputs.pop(key, None)
    for node_id in drop:
        api.pop(node_id, None)
    return api, index_map


def role_support_error(
    nodes: dict[str, str], filled: dict[str, bool], workflow_name: str,
) -> str:
    """已填槽位的角色能否被工作流识别；返回错误文案（空串=通过）。

    整条工作流一个角色都认不出，与「缺某一个槽」是两回事，文案必须分开，
    否则用户只会看到「该工作流没有人像输入」，完全猜不到根因（多为 UI 格式 .json）。
    """
    if not nodes:
        return (
            f"该工作流的参考图节点无法识别角色（可能是 UI 格式工作流），"
            f"请换用 .api.json 工作流：{workflow_name}"
        )
    for role in SLOT_ROLES:
        if filled[role] and role not in nodes:
            return f"该工作流没有{SLOT_LABELS[role]}输入：{workflow_name}"
    return ""


def resolve_trim_plan(
    api_workflow: dict, filled: dict[str, bool],
) -> tuple[dict, dict[str, int], str]:
    """空槽裁剪方案：返回 `(提交用工作流, 角色→图号映射, 错误文案)`；空文案=可提交。

    `/reference/recipes` 与 `/reference/trim-check` 必须共用本函数：
    「探测说能提交」与「提交不 400」是同一个判定，否则前端会弹了框却根本不需要弹。
    """
    input_count = len(find_loadimage_nodes(api_workflow))
    total = sum(filled.values())
    nodes = role_nodes(api_workflow)

    if total >= input_count:
        return api_workflow, build_index_map(api_workflow, filled, nodes), ""

    try:
        trimmed_api, index_map = trim_unfilled_slots(api_workflow, filled)
    except NotTrimmable:
        trimmed_api = api_workflow
        index_map = build_index_map(api_workflow, filled, nodes)
    if len(find_loadimage_nodes(trimmed_api)) != total:
        # 工作流还有本次用不到、又无法安全删除的输入：明确告诉用户需要几张
        return api_workflow, index_map, (
            f"该工作流有 {input_count} 个输入且无法裁剪到 {total} 个；"
            f"请至少提供 {input_count} 张参考图"
        )
    # 图位数够了但内部引用断了（裁剪漏改链）→ 推给 ComfyUI 会 400，这里提前拦住
    dangling = dangling_refs(trimmed_api, set(api_workflow) - set(trimmed_api))
    if dangling:
        broken = "、".join(f"节点{node}.{key}" for node, key, _ in dangling[:3])
        return api_workflow, index_map, (
            f"该工作流裁剪空槽后会断链（{broken} 仍引用已删除的节点），无法安全裁剪；"
            f"请至少提供 {input_count} 张参考图"
        )
    return trimmed_api, index_map, ""


def resolve_studio_workflow(requested: str) -> Path:
    """解析合成台工作流；显式指定不在 studio 范围内时报错，绝不静默回落。"""
    items = list_valid_workflows(scope="studio")
    if not items:
        raise StudioWorkflowError("合成台暂无可用工作流")

    explicit = (requested or "").strip()
    raw = explicit or DEFAULT_STUDIO_WORKFLOW
    for item in items:
        name = item["name"]
        # 兼容前端只传简称：xxx.api.json 的 Path.stem 仍是 xxx.api，这里再去一层
        candidates = {name, Path(name).stem, Path(Path(name).stem).stem}
        if raw in candidates or item["path"] == raw:
            return Path(item["path"])

    try:
        resolved = Path(raw).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        resolved = None
    if resolved is not None:
        for item in items:
            if Path(item["path"]).resolve(strict=False) == resolved:
                return Path(item["path"])

    if explicit:
        raise StudioWorkflowError("该工作流不属于合成台可用范围")
    raise StudioWorkflowError(f"默认工作流不可用：{DEFAULT_STUDIO_WORKFLOW}")
