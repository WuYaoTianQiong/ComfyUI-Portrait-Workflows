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

#: 双人姿势的人体完整性条款（V2-C，2026-11-08）：
#: 参考图多为大头照 / ghost mannequin / 线稿，模型缺少肢体视觉证据，
#: 容易只画衣服不画手脚。这里显式要求四肢完整，并把否定交给编译器抽成负向。
PAIR_ANATOMY_CLAUSE = (
    "两人的手、手指、手臂、腿、脚必须完整自然出现；服装未覆盖的部位必须是自然皮肤；"
    "禁止漂浮衣架式人体。"
)

#: 双人姿势的着装边界：正常可见的手臂 / 小腿 / 手脚不算裸露，
#: 避免模型把「不许裸露」理解成用衣服遮住或省略四肢。
PAIR_MODESTY_CLAUSE = (
    "不得出现性器官、胸部、臀部裸露；"
    "服装之外正常可见的手臂、小腿、手、脚属于正常皮肤，不视为裸露。"
)

#: 成人向（18+ 解锁）的素体条款：只声明不穿服装，不再附加「中性 / 非性化 /
#: 不添加性暗示元素」。默认路径仍用 `BARE_DISPLAY_CLAUSE`，该常量只在
#: `adult_mode=True` 时生效（2026-11-08）。
BARE_DISPLAY_CLAUSE_ADULT = (
    "• 素体展示：画面为成年女性的素体人体展示，不穿任何服装与配饰。"
)

#: bare 模式下的双人四肢条款：没有服装，删掉「服装未覆盖的部位」措辞，
#: 避免提示词里出现与素体自相矛盾的服装描述。
PAIR_ANATOMY_CLAUSE_BARE = (
    "两人的手、手指、手臂、腿、脚必须完整自然出现；全身皮肤自然；"
    "禁止漂浮衣架式人体。"
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


def _modifier_body(lines: list[str]) -> str:
    """修饰层行 → 可嵌入条款的单句正文：去掉行首 `• `，用「；」连接。

    人物 B 的修饰层要包在一条 `• 人物B（附加修饰）：…` 里，若保留每行行首的
    `• ` 会拼出双项目符号；这里只去符号，不改正文内容与顺序。
    """
    return "；".join(re.sub(r"^\s*•\s*", "", line) for line in lines)


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
    #: P1（2026-11-08）：人物B 姿态动作文字；P1 没有 B 独立姿势图位，只走文字。
    person_b_pose_text: str = "",
    #: P1（2026-11-08）：人物B 专属修饰层（视角/场景/光影/画风），格式同 A 的修饰层。
    person_b_modifier_fragments: str = "",
    #: V2-C 第 5 槽：人物B服装图像参考（只在双人姿势下写 B 条款）
    extra_costume: RecipeEntry | None = None,
    #: 成人向（2026-11-08）：仅当 18+ 解锁后由路由层置 True。
    #: 作用范围仅限「去掉素体/双人条款里的非性化、禁裸露抑制句」，
    #: 人数、四肢、构图约束与非成人模式完全一致；默认 False 保证旧行为逐字不变。
    adult_mode: bool = False,
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
    - `extra_costume`（V2-C，2026-11-08）：第 5 槽是人物 B 的服装图像参考。
      B 的服装/配饰/鞋以该图为准，`person_b_costume_text` 不参与；B 的脸/发型仍由
      第 4 槽身份图控制。单人姿势下不写任何 B 条款。
    - `person_b_pose_text` / `person_b_modifier_fragments`（P1，2026-11-08）：
      B 的姿态与修饰层独立成条款，仅双人姿势下生效；B 含「画风技术」时同样抑制整图
      固定风格段（画风是整图属性），其余 B 修饰不回流人物 A。
    - `adult_mode`（2026-11-08）：18+ 解锁后由路由层置 True。只去掉素体/双人条款里的
      「中性、非性化」「不添加任何性暗示元素」「不得出现性器官…裸露」抑制句，
      人数锚点与四肢完整性约束逐字保留；不新增任何露骨描写，实际效果仍由用户提示词驱动。
      默认 False 时所有安全文案与旧调用逐字一致。

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
    # P1：人物 B 独立修饰层；只在双人姿势下渲染，类型判定与 A 分开。
    b_pose_text = _replacement_text(person_b_pose_text)
    b_modifier_lines = _modifier_lines(person_b_modifier_fragments)
    b_modifier_types = _modifier_types(b_modifier_lines)
    # 双人姿势：上游 `pair*` 与 pose-studio-lite 的 `composition=pair` 都必须识别。
    # 姿势段与双人条款共用这一判定：双人时姿势段不能再用单人口径。
    is_pair = bool(
        pose and (pose.composition == "pair" or pose.id.startswith("pair"))
    )

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
        # 2026-11-08：原来写「肤色必须与图一人物一致」——「图一」是上游单图时代的
        # 硬编码图号，现在图1 是姿势白模/深度图，等于让模型对齐白模肤色。改为
        # 不带图号的表述：人像本身就是脸部真源（本节主句已写明「图N中的人物」）。
        skin = (
            "人物的全身皮肤必须与脸部肤色统一，"
            "统一后的肤色与质感按风格要求呈现。"
            if body_mode == "bare"
            else (
                "人物的所有裸露皮肤（包括服装镂空处露出的皮肤）"
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
        # 成人向：素体替代句里的「中性」同样属于抑制措辞，改用普通肤色句。
        skin = (
            PORTRAIT_REPLACEMENT_SKIN_BARE
            if body_mode == "bare" and not adult_mode
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
        if is_pair:
            # 双人时不能再写「画面中的人物是真人…穿着图N的服装」：单人口径会和
            # 后面的「恰好两位」冲突，模型会把两人都往人物A的服装上套。
            body = (
                "画面中只保留两位真人，皮肤真实自然"
                if is_photo
                else "画面中只保留两位真人，肤色与质感按风格要求呈现"
            )
        else:
            body = (
                f"最终画面中的人物是真人，皮肤真实自然{wear}"
                if is_photo
                else f"人物的肤色与质感按风格要求呈现{wear}"
            )
        pose_desc = expand_pose_name(pose.name) or pose.name
        # 拍摄视角碎片优先于库条目角度：有碎片时不再写 pose.angle，其余姿势文案保留。
        if pose.angle and _MODIFIER_VIEW_ANGLE not in modifier_types:
            pose_desc = f"{pose_desc}；镜头角度：{pose.angle}"
        pose_target = f"图{pose_idx}中两个人形" if is_pair else f"图{pose_idx}中人体模型"
        limb_lead = (
            "两人各自必须逐项落实这些身体部位的状态："
            if is_pair
            else "必须逐项落实这些身体部位的状态："
        )
        pair_hint = (
            f"图{pose_idx}中的重叠交叉轮廓是前后遮挡关系，不属于多余肢体；"
            if is_pair
            else ""
        )
        clause = (
            f"• 姿势：严格复现{pose_target}的身体姿态与镜头角度。"
            f"身体姿态要点：{pose_desc}。"
            f"{limb_lead}重心落在哪条腿、胯部朝哪边顶、"
            "肩线与躯干的前后倾斜、手臂的位置（扶腰/搭肩/下垂）、膝盖的朝向与弯曲程度。"
            "不要画成双脚并拢、身体笔直、手臂自然下垂的站立姿势，不要军姿，不要 T-pose。"
            f"{pair_hint}图{pose_idx}只是动作示意，{body}。"
        )
        clause = _supplement_clause(clause, pose_text)
        clauses.append(clause)
        idx += 1
    elif pose_text:
        # 替代态（§5.1）：没有骨架图可复现，只保留「自然重心/关节关系 + 三个否定」；
        # 「严格复现图N」与「图N只是动作示意」两句必须整体消失，否则模型会去找不存在的图。
        clauses.append(f"• 姿势：{pose_text}{POSE_REPLACEMENT_TAIL}")

    # v2-A：第 4 槽语义 = person_b 时，图N 是人物B的脸/发型真源。
    # 先算图号（index_map 优先；没有时按前面已填的图片槽递增），供双人条款引用。
    b_image_idx = 0
    if extra and extra_kind == "person_b":
        if index_map and isinstance(index_map.get("extra"), int) and index_map["extra"] > 0:
            b_image_idx = index_map["extra"]
        else:
            b_image_idx = 1 + int(bool(portrait)) + int(bool(costume)) + int(bool(pose))

    # V2-C：第 5 槽 = 人物B服装图像；与 B 身份图一样按真实图号书写。
    b_costume_idx = 0
    if extra_costume:
        if (
            index_map
            and isinstance(index_map.get("extra_costume"), int)
            and index_map["extra_costume"] > 0
        ):
            b_costume_idx = index_map["extra_costume"]
        else:
            b_costume_idx = (
                1
                + int(bool(portrait))
                + int(bool(costume))
                + int(bool(pose))
                + int(bool(extra))
            )

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
        # 双人条款的三个分支共用同一套人数/四肢/构图约束，只有「抑制句」按模式条件拼接：
        # - bare：用没有服装措辞的四肢条款；
        # - 成人向：去掉禁裸露/非性化抑制句（人数与结构约束不动）。
        anatomy = (
            PAIR_ANATOMY_CLAUSE_BARE if body_mode == "bare" else PAIR_ANATOMY_CLAUSE
        )
        # bare 的抑制由素体条款承担，这里不再叠「不得出现…裸露」，
        # 否则与「不穿任何服装与配饰」自相矛盾（旧 bare 分支同样没有这句）。
        modesty = (
            ""
            if adult_mode or body_mode == "bare"
            else PAIR_MODESTY_CLAUSE
        )
        # B 有任一内容（身份图/服装图/文字/姿态/修饰）就走详细分支。
        # 2026-11-08：bare 不再整体丢弃 B 条款，素体展示同样要能画出人物B。
        b_has_content = bool(
            b_image_idx or b_costume_idx or b_parts or b_pose_text or b_modifier_lines
        )
        if b_has_content:
            a_parts: list[str] = []
            if portrait_idx:
                a_parts.append(f"脸型、五官、发型严格沿用图{portrait_idx}中的人物")
            if costume_idx:
                a_parts.append(f"穿图{costume_idx}中展示的整套服装与配饰")
            a_desc = "，".join(a_parts) or "沿用前面的人物描述"
            if b_image_idx and b_costume_idx:
                b_source = f"按图{b_image_idx}的脸型、发型与图{b_costume_idx}的服装"
            elif b_image_idx:
                b_source = f"按图{b_image_idx}的脸型、发型与下方文字设定"
            elif b_costume_idx:
                b_source = f"按图{b_costume_idx}的服装与下方文字设定"
            else:
                b_source = "按下方文字设定"
            # 拆条（2026-11-08）：人数/结构/构图留在「双人要求」，
            # A 与 B 各自的描述独立成条，前端按「人物A / 人物B / 共用约束」分组渲染。
            clauses.append(
                "• 双人要求：画面中必须同时出现恰好两位成年女性，两人都完整入镜；"
                "人物A只出现一次，人物B只出现一次，每人只有两条腿、两只脚、两只手；"
                f"{modesty}{anatomy}"
                f"两人的相对位置、朝向、远近与肢体关系严格按图{pose_idx}中的两个人形；"
                f"图{pose_idx}中的重叠交叉轮廓是前后遮挡关系，不属于多余肢体，"
                "画面中始终只有人物A与人物B两个人。"
                "禁止合并成一个人、禁止裁掉其中一人、禁止只画一个人。"
            )
            clauses.append(f"• 人物A：{a_desc}。")
            clauses.append(
                f"• 人物B：{b_source}。"
                "人物B的脸型、五官必须与人物A明显不同，不要复用人物A的脸。"
            )
            # 图像优先：B 身份图管脸/发型；B 服装图管服装/配饰/鞋。
            # 被图像接管的文字部分不再重复下发，只保留年龄/自由文字等图像无法表达的内容。
            b_portrait_part = _replacement_text(person_b_portrait_text)
            b_free_part = _replacement_text(person_b_text)
            if b_costume_idx and b_image_idx:
                b_text_parts = [part for part in (b_free_part,) if part]
                label = "年龄/自由文字设定"
            elif b_costume_idx:
                b_text_parts = [part for part in (b_portrait_part, b_free_part) if part]
                label = "面部/年龄文字设定"
            elif b_image_idx:
                b_text_parts = b_image_text_parts
                label = "服装/年龄文字设定"
            else:
                b_text_parts = b_parts
                label = "文字设定"
            if b_text_parts:
                clauses.append(
                    f"• 人物B（{label}）：{_ensure_period('；'.join(b_text_parts))}"
                    "人物B的脸型、五官必须与人物A明显不同，不要复用人物A的脸。"
                )
            # P1：B 的姿势/修饰独立成条款，避免与 A 的槽位文本、全局修饰层混用。
            if b_pose_text:
                clauses.append(
                    f"• 人物B（姿态文字）：{_ensure_period(b_pose_text)}"
                    "人物B的姿态以这段文字为准；两人的相对位置、朝向、远近仍需"
                    f"严格按图{pose_idx}中的两个人形。"
                )
            if b_modifier_lines:
                clauses.append(
                    f"• 人物B（附加修饰）：{_modifier_body(b_modifier_lines)}。"
                )
        elif body_mode == "bare":
            neutral = "" if adult_mode else "保持中性、非性化姿态。"
            clauses.append(
                "• 双人要求：画面中为恰好两位成年女性的素体展示，两人都完整入镜，"
                "每人只有两条腿、两只脚、两只手；"
                f"{neutral}{anatomy}"
                f"图{pose_idx}中的重叠交叉轮廓是前后遮挡关系，不属于多余肢体。"
                f"两人的相对位置、朝向、远近与肢体关系严格按图{pose_idx}中的两个人形。"
                "禁止合并成一个人、禁止裁掉其中一人、禁止只画一个人。"
            )
        else:
            pair_costume = (
                f"其中一位穿图{costume_idx}的整套服装和配饰，另一位穿同色系素色简化款；"
                if costume_idx
                else ""
            )
            clauses.append(
                "• 双人要求：画面中必须同时出现恰好两位成年女性，两人都要完整入镜；"
                "画面中始终只有两位人物，每人只有两条腿、两只脚、两只手；"
                f"{pair_costume}{modesty}{anatomy}"
                f"两人的相对位置、朝向、远近与肢体关系严格按图{pose_idx}中的两个人形；"
                f"图{pose_idx}中的重叠交叉轮廓是前后遮挡关系，不属于多余肢体。"
                "禁止合并成一个人、禁止裁掉其中一人、禁止只画一个人。"
            )

    # 素体模式（C-REF-BODY-MODE@1）：只追加素体展示条款。
    # bare 下不可能同时选服装（图或文本），所以上面不会出现服装段落；
    # faceless 也天然不触发（`bool(costume and pose)` 需要服装图存在）。
    # 成人向（2026-11-08）：换成不含「中性/非性化/性暗示」的素体条款。
    if body_mode == "bare":
        clauses.append(
            BARE_DISPLAY_CLAUSE_ADULT if adult_mode else BARE_DISPLAY_CLAUSE
        )

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

    # V2-C：第 5 槽是人物B服装；只给 B 提供服装/配饰/鞋，绝不回流到 A。
    # 单人姿势下不写任何 B 条款（与第 4 槽 person_b 同一隔离口径）。
    if extra_costume:
        if is_pair:
            name_hint = (
                f"（参考：{extra_costume.name}）"
                if extra_costume.name and "上传" not in extra_costume.name
                else ""
            )
            clauses.append(
                f"• 人物B（服装图像参考）：图{b_costume_idx}是人物B的整套服装、配饰与鞋参考{name_hint}；"
                f"人物B的服装、配饰、鞋必须与图{b_costume_idx}一致；"
                f"图{b_costume_idx}的服装绝对不要用于人物A。"
            )
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
    if (
        style_info["prompt"]
        and _MODIFIER_ART_STYLE not in modifier_types
        # P1：B 的画风碎片同样是整图属性，双人姿势下与固定风格段互斥；
        # 单人姿势不渲染 B 条款，也不能被 B 的画风碎片影响。
        and not (is_pair and _MODIFIER_ART_STYLE in b_modifier_types)
    ):
        tail = "人物比例协调，手部自然，脸部无五官，光影统一。" if faceless else "人物比例协调，手部与五官自然，光影统一。"
        lines.append(f"• 风格：{style_info['prompt']} {tail}")
    lines.append("没有任何文字、标志或水印。")
    return "\n".join(lines)