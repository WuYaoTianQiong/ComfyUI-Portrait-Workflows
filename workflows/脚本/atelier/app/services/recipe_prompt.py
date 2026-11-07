"""参考库出图 · 中文结构化提示词。

逐段移植上游 `ai-pose-gallery-zh/src/services/aiGenerator.ts:155 buildRecipePrompt`：
- 用自然语言给每张参考图编号（图1 人物 / 图2 服装 / 图3 姿势 / 图4 附加），
  实测比堆砌要点更能让多图编辑模型还原服装、避免照搬人体模型线条；
- 本仓库只保留「无预设 / 写实人像写真」两种画风，其余画风按需再加；
- 上游的 `upload` / `character_sheet` 分支在这里不会出现（参考库条目全部来自本地库），
  因此只保留库条目分支，但保留 `faceless`（无脸展示）判定以便日后兼容。
"""
from __future__ import annotations

import re
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
    #: 仅姿势：`pair` 表示双人构图；上游 pair* 与 pose-studio-lite 都靠它判双人。
    composition: str = ""


#: 补充态（P1）固定句式：图片主句保留，文本只作额外特征追加。
#: 补充分句刻意不写「图N」——图号只对已填图片槽生效（方案 §5.2）。
SUPPLEMENT_JOINER = "；此外需体现："

#: 替代态（P2）固定句式（方案 §5.1）：槽无图、但该槽有文本时，用文本句替换图片主句。
#: 三句同样不写「图N」——文本槽不占图号，图号只对已填图片槽生效。
PORTRAIT_REPLACEMENT_PREFIX = "• 人物：一位"
#: 人像替代句的肤色收尾；bare 模式额外声明中性素体展示（不写任何性化措辞）。
PORTRAIT_REPLACEMENT_SKIN = "肤色与质感按风格要求呈现。"
PORTRAIT_REPLACEMENT_SKIN_BARE = "中性素体展示，肤色与质感按风格要求呈现。"
COSTUME_REPLACEMENT_TAIL = "，颜色、款式、面料与配饰以文字描述为准。"
POSE_REPLACEMENT_TAIL = (
    "。保持重心、胯部朝向、肩线、手臂位置与膝盖弯曲的自然关系；"
    "不要军姿，不要 T-pose，不要双脚并拢。"
)

#: 修饰层行首：`• 类型：内容`（与前端渲染结果、composer 的碎片格式一致）。
_MODIFIER_HEAD_RE = re.compile(r"^\s*•\s*([^：:]+?)\s*[：:]")

#: 有该修饰碎片时，姿势段不再写库条目里的 `镜头角度：{pose.angle}`（方案 §5.3）。
_MODIFIER_VIEW_ANGLE = "拍摄视角"
#: 有该修饰碎片时，不追加固定 `• 风格：` 段（方案 §5.4）。
_MODIFIER_ART_STYLE = "画风技术"


def _supplement_clause(clause: str, text: str) -> str:
    """在图片主句后追加「此外需体现」分句；空文本原样返回。

    主句以句号结尾，这里先去掉句号再接分号，避免出现「。；」。
    """
    text = (text or "").strip()
    if not text:
        return clause
    return f"{clause.rstrip('。')}{SUPPLEMENT_JOINER}{text}。"


def _replacement_text(text: str) -> str:
    """槽位文本 → 替代句里的短语：去空白并去掉尾部句号，模板统一补一个「。」。

    用户碎片常常自带句号；不去尾句号会拼出「…柔和。。」，模型侧虽无影响，
    但 dry-run 预览可读性差，且与「。；」同类问题同源。
    """
    return (text or "").strip().rstrip("。")


def _slot_texts(portrait_text: str, costume_text: str, pose_text: str) -> tuple[str, str, str]:
    """三槽文本一次性归一化，避免每个分支各写一遍 strip / 重复标点。"""
    return tuple(
        _replacement_text(text).replace("。；", "；").replace("；。", "；")
        for text in (portrait_text, costume_text, pose_text)
    )


def _modifier_lines(text: str) -> list[str]:
    """修饰层原始行：去掉空行与逐行重复，保留 `• 类型：内容` 的书写顺序。

    类型去重按整行精确匹配（type||content），与 composer 的去重口径一致；
    正文跨行时不能按「类型」重建，否则会把碎片正文重新排版。
    """
    lines: list[str] = []
    seen: set[str] = set()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return lines


def _modifier_types(lines: list[str]) -> set[str]:
    """修饰层里出现过的类型名（`• 拍摄视角：…` → `拍摄视角`）。"""
    types: set[str] = set()
    for line in lines:
        matched = _MODIFIER_HEAD_RE.match(line)
        if matched:
            types.add(matched.group(1).strip())
    return types


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


def _ensure_period(text: str) -> str:
    """给人物 B 的自由文字补齐句末标点；已有标点不重复追加。"""
    text = text.strip()
    if not text:
        return ""
    return text if text[-1] in "。！？!?；;" else f"{text}。"


def build_recipe_prompt(
    portrait: RecipeEntry | None,
    costume: RecipeEntry | None,
    pose: RecipeEntry | None,
    extra: RecipeEntry | None = None,
    extra_kind: str = "",
    style: str = "realistic",
    prompt_suffix: str = "",
    index_map: dict[str, int] | None = None,
    body_mode: str = "costume",
    portrait_text: str = "",
    costume_text: str = "",
    pose_text: str = "",
    modifier_fragments: str = "",
    negative_prompt: str = "",
    person_b_text: str = "",
    extra_text: str = "",
    person_b_portrait_text: str = "",
    person_b_costume_text: str = "",
) -> str:
    """按上游顺序拼出完整提示词；未知画风/素体模式抛 ValueError（由路由转成 400）。

    `index_map` 是角色 → 工作流真实图号（"portrait"/"costume"/"pose"/"extra"）。
    合成台空槽裁剪后图位不会压缩重排（例如 Qwen21 缺人像时服装仍是图3、姿势仍是图1），
    这里必须按真实图号写提示词；不传时退回按出现顺序递增的旧行为。

    `body_mode`（C-REF-BODY-MODE@1）默认 `"costume"` 保持旧调用方行为不变：
    - 未选服装时**不再**写「保留图1人物原有可见服装」，避免模型补全/捏造衣服；
    - `"bare"` 额外追加中性素体条款，双人姿势改为中性、非性化姿态描述。

    P1 补充态（方案 §5.2 / §5.3 / §5.4）：
    - `portrait_text` / `costume_text` / `pose_text`：对应槽**有图**时，在图片主句后
      追加「此外需体现」分句（槽内有图 + 文本 = 补充态）。P4 起是否允许这条路径
      由路由层按 `*_supplement` 开关校验；本函数只负责渲染，不做开关判断。
    - `modifier_fragments`：`• 类型：内容` 多行原文，插在「补充要求」之前；
      含「拍摄视角」时不写库条目角度，含「画风技术」时不追加固定风格段。
    - `negative_prompt`：本函数不渲染负向；签名与 `RecipeRequest` 对齐，负向统一由
      提交层 `compile_prompt` / `inject_prompt` 处理。
    - `extra_text`（第 4 槽文字补充，2026-11-07）：仅在 `extra` 图片存在时生效，
      在发型 / 附加参考主句后追加「此外需体现」分句；无图时不渲染（路由层已 400）。
    - `person_b_portrait_text` / `person_b_costume_text`（v1.5，2026-11-07）：
      人物 B 的面部/身材与服饰文本碎片，只在双人姿势下并入「人物B（文字设定）」条款；
      单人或无 B 内容时完全忽略，A 的条款（图N人物 + 槽位文本）逐字不变。
    - `extra_kind="person_b"`（v2-A，2026-11-07）：第 4 槽是人物 B 的脸/发型身份参考。
      B 的面容/发型以图N为准，`person_b_portrait_text` 不参与；B 的服装/年龄仍走文字。
      图N 的脸/发型明确禁止用于人物 A；A 的三槽条款保持逐字不变。

    P2 替代态（方案 §5.1 / §4.4）：对应槽**无图**且文本非空时，用文本句替换图片主句
    （`portrait is None` 等），三槽要么图片句、要么文本句，二选一。
    - 文本槽不占图号：`idx` 只在有图时递增，提示词仍按 `index_map` 写真实 `image_N`；
    - 顺序固定 人像 → 服装 → 姿势；
    - `faceless` 只在「人像既无图也无文本」时成立（C3-2），否则会抹掉文本描述的脸。
    """
    if style not in STYLE_PRESETS:
        raise ValueError(f"不支持的画风：{style}")
    if body_mode not in BODY_MODES:
        raise ValueError(f"不支持的素体模式：{body_mode}")

    style_info = STYLE_PRESETS[style]
    is_photo = style in PHOTO_STYLES
    portrait_text, costume_text, pose_text = _slot_texts(
        portrait_text, costume_text, pose_text,
    )
    # C3-2：人像槽用文本替代时，文本就是「脸」的描述，不能再判无脸展示。
    faceless = not (portrait or portrait_text) and bool(costume and pose)
    modifier_lines = _modifier_lines(modifier_fragments)
    modifier_types = _modifier_types(modifier_lines)

    clauses: list[str] = []
    #: 图号计数只在有图时递增（文本槽不占图号）；`index_map` 存在时以真实图位为准。
    idx = 1
    portrait_idx = 0
    costume_idx = 0

    if portrait:
        num = _figure_no(index_map, "portrait", idx)
        portrait_idx = num
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
        clause = (
            f"• 人物：图{num}中的人物，保持其脸型、五官、发型（{_hair_description(portrait)}）"
            f"和发色一致。{skin}"
        )
        # 补充态：槽有图时文本只是额外特征，不覆盖「保持图N一致」的主句。
        clause = _supplement_clause(clause, portrait_text)
        clauses.append(clause)
        idx += 1
    elif portrait_text:
        # 替代态（§5.1）：槽无图但有文本 → 文本句替换图片主句，不写「图N」。
        # bare 下没有服装可参照，只声明中性素体展示；非 bare 保留肤色/质感约定。
        skin = (
            PORTRAIT_REPLACEMENT_SKIN_BARE
            if body_mode == "bare"
            else PORTRAIT_REPLACEMENT_SKIN
        )
        clauses.append(
            f"{PORTRAIT_REPLACEMENT_PREFIX} {portrait_text}。{skin}"
        )

    if costume:
        costume_idx = _figure_no(index_map, "costume", idx)
        clause = (
            f"• 服装：让人物穿上图{costume_idx}中展示的整套服装和配饰"
            f"（参考名称：{costume.name}），每件单品的颜色、款式、面料与配饰都以图{costume_idx}为准，"
            f"名称仅作辅助说明。"
        )
        clause = _supplement_clause(clause, costume_text)
        clauses.append(clause)
        idx += 1
    elif costume_text:
        # 替代态（§5.1）：文字即服装真源，刻意不写「以图N为准」。
        clauses.append(
            f"• 服装：人物穿着 {costume_text}{COSTUME_REPLACEMENT_TAIL}"
        )

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
        # 拍摄视角碎片优先于库条目角度：有碎片时不再写 pose.angle，其余姿势文案保留。
        if pose.angle and _MODIFIER_VIEW_ANGLE not in modifier_types:
            pose_desc = f"{pose_desc}；镜头角度：{pose.angle}"
        clause = (
            f"• 姿势：严格复现图{pose_idx}中人体模型的身体姿态与镜头角度。"
            f"身体姿态要点：{pose_desc}。"
            "必须逐项落实这些身体部位的状态：重心落在哪条腿、胯部朝哪边顶、"
            "肩线与躯干的前后倾斜、手臂的位置（扶腰/搭肩/下垂）、膝盖的朝向与弯曲程度。"
            "不要画成双脚并拢、身体笔直、手臂自然下垂的站立姿势，不要军姿，不要 T-pose。"
            f"图{pose_idx}只是动作示意，{body}。"
        )
        clause = _supplement_clause(clause, pose_text)
        clauses.append(clause)
        idx += 1
    elif pose_text:
        # 替代态（§5.1）：没有骨架图可复现，只保留「自然重心/关节关系 + 三个否定」；
        # 「严格复现图N」与「图N只是动作示意」两句必须整体消失，否则模型会去找不存在的图。
        clauses.append(f"• 姿势：{pose_text}{POSE_REPLACEMENT_TAIL}")

    # 双人姿势：上游 `pair*` 与 pose-studio-lite 的 `composition=pair` 都必须识别。
    # 2026-11-07 实测：自动模式只有一张人像时模型会克隆 A；B 的文字设定必须显式写出，
    # 且要声明 B 的脸与 A 不同，否则两人会变成同一张脸。
    # 未选服装时不再写「两人各自都有完整服装」：那是凭空捏造衣装。
    is_pair = bool(
        pose and (pose.composition == "pair" or pose.id.startswith("pair"))
    )
    # v2-A：第 4 槽语义 = person_b 时，图N 是人物B的脸/发型真源。
    # 先算图号（index_map 优先；没有时按前面已填的图片槽递增），供双人条款引用。
    b_image_idx = 0
    if extra and extra_kind == "person_b":
        if index_map and isinstance(index_map.get("extra"), int) and index_map["extra"] > 0:
            b_image_idx = index_map["extra"]
        else:
            b_image_idx = 1 + int(bool(portrait)) + int(bool(costume)) + int(bool(pose))

    # B 的三部分文本（面部/身材、服饰、自由补充）各自独立；只在双人姿势下并入 B 条款。
    # 有 B 身份图时，面容/发型以图为准，`person_b_portrait_text` 不参与（UI 会禁用对应入口）。
    b_parts = [
        part
        for part in (
            _replacement_text(person_b_portrait_text),
            _replacement_text(person_b_costume_text),
            _replacement_text(person_b_text),
        )
        if part
    ]
    b_image_text_parts = [
        part
        for part in (
            _replacement_text(person_b_costume_text),
            _replacement_text(person_b_text),
        )
        if part
    ]
    if is_pair:
        if body_mode == "bare":
            clauses.append(
                "• 双人要求：画面中为恰好两位成年女性的素体展示，两人都完整入镜，保持中性、非性化姿态。"
                f"两人的相对位置、朝向、远近与肢体关系严格按图{pose_idx}中的两个人形。"
                "禁止合并成一个人、禁止裁掉其中一人、禁止只画一个人。"
            )
        elif b_image_idx or b_parts:
            a_parts: list[str] = []
            if portrait_idx:
                a_parts.append(f"脸型、五官、发型严格沿用图{portrait_idx}中的人物")
            if costume_idx:
                a_parts.append(f"穿图{costume_idx}中展示的整套服装与配饰")
            a_desc = "，".join(a_parts) or "沿用前面的人物描述"
            b_source = (
                f"按图{b_image_idx}的脸型、发型与下方文字设定"
                if b_image_idx
                else "按下方文字设定"
            )
            clauses.append(
                "• 双人要求：画面中必须同时出现恰好两位成年女性，两人都完整入镜；"
                f"人物A：{a_desc}；人物B{b_source}；任何一位都不允许裸露或半裸。"
                f"两人的相对位置、朝向、远近与肢体关系严格按图{pose_idx}中的两个人形。"
                "禁止合并成一个人、禁止裁掉其中一人、禁止只画一个人。"
            )
            # 有 B 身份图：面容/发型以图为准，文字只保留服装/年龄，避免与图像冲突。
            # 无 B 身份图：仍是 v1.5 的三部分固定顺序拼接；A 的条款完全不动。
            b_text_parts = b_image_text_parts if b_image_idx else b_parts
            if b_text_parts:
                label = "服装/年龄文字设定" if b_image_idx else "文字设定"
                clauses.append(
                    f"• 人物B（{label}）：{_ensure_period('；'.join(b_text_parts))}"
                    "人物B的脸型、五官必须与人物A明显不同，不要复用人物A的脸。"
                )
        else:
            pair_costume = (
                f"其中一位穿图{costume_idx}的整套服装和配饰，另一位穿同色系素色简化款；"
                if costume_idx
                else ""
            )
            clauses.append(
                "• 双人要求：画面中必须同时出现恰好两位成年女性，两人都要完整入镜；"
                f"{pair_costume}任何一位都不允许裸露或半裸。"
                f"两人的相对位置、朝向、远近与肢体关系严格按图{pose_idx}中的两个人形。"
                "禁止合并成一个人、禁止裁掉其中一人、禁止只画一个人。"
            )

    # 素体模式（C-REF-BODY-MODE@1）：只追加中性人体展示条款。
    # bare 下不可能同时选服装（图或文本），所以上面不会出现服装段落；
    # faceless 也天然不触发（`bool(costume and pose)` 需要服装图存在）。
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
        if extra_kind == "person_b":
            # v2-A：第 4 槽是人物B身份图；只给 B 提供脸/发型，绝不回流到 A。
            # 单人姿势下没有人物B可归属：整条 B 条款（含文字补充）都不写，
            # 否则模型可能把图N的脸直接用到人物A。
            if not is_pair:
                clause = ""
            else:
                name_hint = (
                    f"（参考：{extra.name}）"
                    if extra.name and "上传" not in extra.name
                    else ""
                )
                clause = (
                    f"• 人物B（图像参考）：图{extra_num}是人物B的脸型与发型参考{name_hint}；"
                    f"人物B的脸型、五官、发型必须与图{extra_num}一致，"
                    f"但不得使用图{extra_num}中人物的服装；"
                    f"图{extra_num}的脸与发型绝对不要用于人物A。"
                )
        elif extra_kind == "hair":
            portrait_num = _figure_no(index_map, "portrait", 0)
            face_hint = (
                f"，结合图{portrait_num}人物的发际线自然衔接" if portrait_num else ""
            )
            name_hint = (
                f"（参考：{extra.name}）"
                if extra.name and "上传" not in extra.name
                else ""
            )
            clause = (
                f"• 发型：严格复现图{extra_num}中的发型{name_hint}"
                "（长度、轮廓、分缝、发色、盘发/编发结构）"
                f"{face_hint}。图{extra_num}只提供发型背面/无脸参考，"
                f"不要使用图{extra_num}中人物的脸、服装或背景。"
            )
        else:
            clause = (
                f"• 附加参考：融合图{extra_num}（{extra.name or '补充元素'}）中的元素、配饰、背景或光影细节。"
            )
        if clause:
            clauses.append(clause)
        # 图为主 + 文本补充：单独成句，避免编译器抽走「不要使用图N…」后
        # 留下「，；此外需体现」的拼接标点；文字不覆盖图片主句。
        # 无主句（单人姿势下的 B 身份图）时不渲染补充文字。
        extra_note = _replacement_text(extra_text) if clause else ""
        if extra_note:
            clauses.append(f"• 此外需体现：{extra_note}。")
        idx += 1

    if not clauses:
        return "请先选择人像/服装/姿势或上传附加参考图。"

    # 修饰层（§5.3）：始终追加，位于「补充要求」之前；无 prompt_suffix 时
    # 因此自然落在固定「风格」段之前。原文按行插入，不做解析重建。
    if modifier_lines:
        clauses.extend(modifier_lines)

    suffix = (prompt_suffix or "").strip()
    if suffix:
        clauses.append(f"• 补充要求：{suffix}")

    subject = "人物穿搭展示图" if faceless else ("真实人物照片" if is_photo else "人物图像")
    lines = [f"请根据提供的 {idx - 1} 张参考图，生成一张完整的{subject}：", *clauses]
    # 画风技术碎片与画风预设互斥（§5.4）：选了碎片就不再追加固定风格描述段；
    # 真人/非真人主体判定仍只看 style，不受碎片影响。
    if style_info["prompt"] and _MODIFIER_ART_STYLE not in modifier_types:
        tail = "人物比例协调，手部自然，脸部无五官，光影统一。" if faceless else "人物比例协调，手部与五官自然，光影统一。"
        lines.append(f"• 风格：{style_info['prompt']} {tail}")
    lines.append("画面中没有任何文字、标志或水印。")
    return "\n".join(lines)