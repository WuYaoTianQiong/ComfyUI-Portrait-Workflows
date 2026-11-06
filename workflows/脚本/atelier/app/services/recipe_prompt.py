"""参考库出图 · 中文结构化提示词。

逐段移植上游 `ai-pose-gallery-zh/src/services/aiGenerator.ts:155 buildRecipePrompt`：
- 用自然语言给每张参考图编号（图1 人物 / 图2 服装 / 图3 姿势 / 图4 附加），
  实测比堆砌要点更能让多图编辑模型还原服装、避免照搬人体模型线条；
- 本仓库只保留「无预设 / 写实人像写真」两种画风，其余画风按需再加；
- 上游的 `upload` / `character_sheet` 分支在这里不会出现（参考库条目全部来自本地库），
  因此只保留库条目分支，但保留 `faceless`（无脸展示）判定以便日后兼容。
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.pose_phrases import expand_pose_name

#: 与上游同名画风键保持一一对应，前端下拉直接用这两个 key。
STYLE_PRESETS: dict[str, dict[str, str]] = {
    "none": {
        "label": "无预设（跟随参考图）",
        "prompt": "",
    },
    "realistic": {
        "label": "写实人像写真",
        "prompt": "写实商业摄影级质感，85mm 人像镜头，自然柔和光影，真实肌肤纹理与织物细节，8k 高清画质。",
    },
}

#: 支持在提示词里声明「真人」的画风（上游 PHOTO_STYLES 的可裁剪子集）。
PHOTO_STYLES = frozenset({"realistic"})

#: 上游用这个发型名称表示「没有特殊发型」，此时回退到发长描述。
BASE_HAIR_NAME = "标准基础款"

#: 素体模式（C-REF-BODY-MODE@1）：
#: - `costume`：常规出图，服装槽有参考图就写服装段（默认，兼容旧调用）；
#: - `bare`：中性素体展示，禁止选服装，只写中性、非性化的素体条款。
BODY_MODES: tuple[str, str] = ("costume", "bare")

#: 素体展示条款：不写身体部位清单、不写「裸露/性感」等词，只声明中性人体展示。
BARE_DISPLAY_CLAUSE = (
    "• 素体展示：画面为成年女性的素体人体展示，不穿任何服装与配饰；"
    "保持中性、非性化的站姿或姿势构图，不添加任何性暗示元素。"
)


@dataclass(frozen=True)
class RecipeEntry:
    """一张参考图在提示词里需要的最小字段（来自参考库 DTO）。"""

    id: str
    name: str = ""
    subtitle: str = ""
    facet: str = ""
    angle: str = ""


def _hair_description(portrait: RecipeEntry) -> str:
    """上游：发型名称不是「标准基础款」时用标题，否则用发长。

    DTO 映射：`name` = 标题、`subtitle` = 发型名称、`facet` = 发长。
    """
    hair_name = (portrait.subtitle or "").strip()
    if hair_name and hair_name != BASE_HAIR_NAME:
        return portrait.name
    return portrait.facet


def _figure_no(index_map: dict[str, int] | None, role: str, default: int) -> int:
    """角色在提示词里的图号：调用方给了真实图位就按图位，否则用默认递增号。"""
    if index_map:
        value = index_map.get(role)
        if isinstance(value, int) and value > 0:
            return value
    return default


def build_recipe_prompt(
    portrait: RecipeEntry | None,
    costume: RecipeEntry | None,
    pose: RecipeEntry | None,
    extra: RecipeEntry | None = None,
    style: str = "realistic",
    prompt_suffix: str = "",
    index_map: dict[str, int] | None = None,
    body_mode: str = "costume",
) -> str:
    """按上游顺序拼出完整提示词；未知画风/素体模式抛 ValueError（由路由转成 400）。

    `index_map` 是角色 → 工作流真实图号（"portrait"/"costume"/"pose"/"extra"）。
    合成台空槽裁剪后图位不会压缩重排（例如 Qwen21 缺人像时服装仍是图3、姿势仍是图1），
    这里必须按真实图号写提示词；不传时退回按出现顺序递增的旧行为。

    `body_mode`（C-REF-BODY-MODE@1）默认 `"costume"` 保持旧调用方行为不变：
    - 未选服装时**不再**写「保留图1人物原有可见服装」，避免模型补全/捏造衣服；
    - `"bare"` 额外追加中性素体条款，双人姿势改为中性、非性化姿态描述。
    """
    if style not in STYLE_PRESETS:
        raise ValueError(f"不支持的画风：{style}")
    if body_mode not in BODY_MODES:
        raise ValueError(f"不支持的素体模式：{body_mode}")

    style_info = STYLE_PRESETS[style]
    is_photo = style in PHOTO_STYLES
    faceless = not portrait and bool(costume and pose)

    clauses: list[str] = []
    idx = 1
    costume_idx = 0

    if portrait:
        num = _figure_no(index_map, "portrait", idx)
        # bare 模式下没有服装，"服装镂空处露出的皮肤"无从谈起；同时避免出现
        # 「裸露」等词，统一改成中性的「全身皮肤」表述。
        skin = (
            "人物的肤色必须与图一人物一致，全身皮肤必须与脸部肤色统一，"
            "统一后的肤色与质感按风格要求呈现。"
            if body_mode == "bare"
            else (
                "人物的肤色必须与图一人物一致，所有裸露皮肤（包括服装镂空处露出的皮肤）"
                "必须与脸部肤色统一，统一后的肤色与质感按风格要求呈现。"
            )
        )
        # 未选服装时**不写任何服装指令**：任何"保留原有服装"的措辞都会让模型
        # 补全/捏造衣服（实测缺陷），服装要留白就彻底留白。
        clauses.append(
            f"• 人物：图{num}中的人物，保持其脸型、五官、发型（{_hair_description(portrait)}）"
            f"和发色一致。{skin}"
        )
        idx += 1

    if costume:
        costume_idx = _figure_no(index_map, "costume", idx)
        clauses.append(
            f"• 服装：让人物穿上图{costume_idx}中展示的整套服装和配饰"
            f"（参考名称：{costume.name}），每件单品的颜色、款式、面料与配饰都以图{costume_idx}为准，"
            f"名称仅作辅助说明。"
        )
        idx += 1

    pose_idx = 0
    if pose:
        pose_idx = _figure_no(index_map, "pose", idx)
        wear = f"，穿着图{costume_idx}的服装" if costume_idx else ""
        body = (
            f"最终画面中的人物是真人，皮肤真实自然{wear}"
            if is_photo
            else f"人物的肤色与质感按风格要求呈现{wear}"
        )
        pose_desc = expand_pose_name(pose.name) or pose.name
        if pose.angle:
            pose_desc = f"{pose_desc}；镜头角度：{pose.angle}"
        clauses.append(
            f"• 姿势：严格复现图{pose_idx}中人体模型的身体姿态与镜头角度。"
            f"身体姿态要点：{pose_desc}。"
            "必须逐项落实这些身体部位的状态：重心落在哪条腿、胯部朝哪边顶、"
            "肩线与躯干的前后倾斜、手臂的位置（扶腰/搭肩/下垂）、膝盖的朝向与弯曲程度。"
            "不要画成双脚并拢、身体笔直、手臂自然下垂的站立姿势，不要军姿，不要 T-pose。"
            f"图{pose_idx}只是动作示意，{body}。"
        )
        idx += 1

    # 双人姿势（库内 id 统一为 `pair*`）：必须显式声明人数与两人的服装归属。
    # 实测（2026-11-04）：只写「按图3摆姿势」时，无论 Edit 还是 VNCCS 都只出一个；
    # 且第二人容易没衣服。这里把人数、两人的衣装、禁止合并都写死。
    # 未选服装时不再写「两人各自都有完整服装」：那是凭空捏造衣装。
    is_pair = bool(pose and pose.id.startswith("pair"))
    if is_pair:
        if body_mode == "bare":
            clauses.append(
                "• 双人要求：画面中为两位成年女性的素体展示，两人都完整入镜，保持中性、非性化姿态。"
                f"两人的相对位置、朝向、远近与肢体关系严格按图{pose_idx}中的两个人形，"
                "禁止合并成一个人、禁止裁掉其中一人、禁止只画一个人。"
            )
        else:
            pair_costume = (
                f"其中一位穿图{costume_idx}的整套服装和配饰，另一位穿同色系素色简化款；"
                if costume_idx
                else ""
            )
            clauses.append(
                "• 双人要求：画面中必须同时出现两位成年女性，两人都要完整入镜；"
                f"{pair_costume}任何一位都不允许裸露或半裸。"
                f"两人的相对位置、朝向、远近与肢体关系严格按图{pose_idx}中的两个人形，"
                "禁止合并成一个人、禁止裁掉其中一人、禁止只画一个人。"
            )

    # 素体模式（C-REF-BODY-MODE@1）：只追加中性人体展示条款。
    # bare 下不可能选服装，所以上面不会出现任何服装段落；faceless 也天然不触发
    # （`not portrait and bool(costume and pose)` 需要 costume 存在）。
    if body_mode == "bare":
        clauses.append(BARE_DISPLAY_CLAUSE)

    if faceless:
        clauses.append(
            "• 无脸展示：生成一位穿着参考服装的成年展示人物，脸部保持无五官的自然肤色表面，"
            "不添加眼睛、鼻子、嘴巴或具体人物身份；全身裸露皮肤的颜色统一，"
            "不照搬服装图或姿势图的灰白人台材质。"
        )

    if extra:
        extra_num = _figure_no(index_map, "extra", idx)
        clauses.append(
            f"• 附加参考：融合图{extra_num}（{extra.name or '补充元素'}）中的元素、配饰、背景或光影细节。"
        )
        idx += 1

    if not clauses:
        return "请先选择人像/服装/姿势或上传附加参考图。"

    suffix = (prompt_suffix or "").strip()
    if suffix:
        clauses.append(f"• 补充要求：{suffix}")

    subject = "人物穿搭展示图" if faceless else ("真实人物照片" if is_photo else "人物图像")
    lines = [f"请根据提供的 {idx - 1} 张参考图，生成一张完整的{subject}：", *clauses]
    if style_info["prompt"]:
        tail = "人物比例协调，手部自然，脸部无五官，光影统一。" if faceless else "人物比例协调，手部与五官自然，光影统一。"
        lines.append(f"• 风格：{style_info['prompt']} {tail}")
    lines.append("画面中没有任何文字、标志或水印。")
    return "\n".join(lines)