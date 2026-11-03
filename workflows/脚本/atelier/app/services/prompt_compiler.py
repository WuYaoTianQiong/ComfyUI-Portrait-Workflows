"""单框提示词编译器：把正向里的否定子句拆成「肯定式改写 + 负向裸名词」。

扩散模型的正向条件只做加法；把「不要 X」留在正向里，既不能可靠地压制 X，
还会把 X 这个词喂进 cross-attention。这里在提交时做一次确定性编译：

- 负向通道有效（cfg>1 且负向来自文本节点）→ 抽出的词写入负向，正向改肯定描述；
- 负向通道无效（cfg=1 / ConditioningZeroOut）→ 只做肯定式改写，不假装负向生效；
- 无法识别的否定保持原样，并在 `warnings` 里明确告诉用户，不静默丢内容。

编译器只做保守的规则匹配，不调用 LLM；同一段文本重复编译应当无变化。
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CompiledPrompt:
    """一次编译的结果。

    `negative` 是「如果工作流支持负向，应该提交的内容」；当
    `negative_effective=False` 时调用方不应把它写进工作流。
    """

    positive: str
    negative: str
    notes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    extracted: tuple[str, ...] = ()
    negative_effective: bool = False

    def as_dict(self) -> dict[str, object]:
        """写进 prompt_params / API 响应的稳定形状。"""
        return {
            "positive": self.positive,
            "negative": self.negative,
            "notes": list(self.notes),
            "warnings": list(self.warnings),
            "extracted": list(self.extracted),
            "negative_effective": self.negative_effective,
        }


@dataclass(frozen=True)
class _Rule:
    pattern: re.Pattern[str]
    replacement: str
    negatives: tuple[str, ...]
    note: str


_TEXT_TERM = r"(?:多余文字|英文字|英文|文字|文本|字幕|水印|印章|落款|签名|logo|标志)"
_POSE_TERM = (
    r"(?:普通站姿|普通站拍|普通摆拍|过度摆拍|刻意摆拍|僵硬姿势|呆板姿势|"
    r"站桩|呆立|蹲姿|过于端正|刻意摆姿势|摆拍|僵硬的姿势)"
)
_TEXT_TERM_RE = re.compile(_TEXT_TERM, re.IGNORECASE)
_TEXT_NEG_RE = re.compile(
    rf"(?:不要|避免|禁止|去除|去掉|不出现|没有|无)"
    rf"(?:任何|多余|明显|一点|太多)?"
    rf"(?P<terms>{_TEXT_TERM}(?:[、,，和及与或\s]*{_TEXT_TERM})*)",
    re.IGNORECASE,
)
_LEFTOVER_NEG_RE = re.compile(
    r"(?:不要|避免|禁止|去除|去掉|不出现)[^，,。；;、\n]*"
)
# 一条否定管一串顿号项：「避免未成年外貌、学校制服感、cosplay…」
_NEG_BLOCK_RE = re.compile(r"(?P<prefix>避免|不要|禁止)(?P<body>[^，,。；;\n]+)")
_SAFETY_RE = re.compile(r"未成年|幼态|童颜|萝莉|低龄|儿童")
_LIST_STOPWORDS = {"以", "和", "或", "及", "与", "的", "并", "且", "任何"}
_LIST_SEP_RE = re.compile(r"[、和及与或]+")
_NEG_SECTION_HEADER_RE = re.compile(
    r"^\s*【(?:避免|负面|反向|negative|avoid)】\s*[:：]?\s*(.*)$",
    re.IGNORECASE,
)
_NEG_ITEM_PREFIX_RE = re.compile(
    r"^(?:不要|避免|禁止|无需|不用|不出现|任何|无|没有)\s*"
)
_CALLIGRAPHY_RE = re.compile(r"书法|卷轴|宣纸|题字|毛笔|墨迹|汉字|字形|字帖|匾额|碑帖")
_SIGN_RE = re.compile(r"招牌|店招|门头|霓虹|菜单|海报|标语|路牌|指示牌|广告牌")

# 英文否定：DB 里 13 条英文提示主要就是 no cropping / no text / no watermark / no logo。
_EN_TEXT_TERM = r"(?:text|watermark|logo|signature|seal|words?)"
_EN_TEXT_NEG_RE = re.compile(
    rf"\b(?:no|without)\s+(?P<terms>{_EN_TEXT_TERM}"
    rf"(?:\s*(?:,|or|and|/)\s*(?:no|without)?\s*{_EN_TEXT_TERM})*)\b",
    re.IGNORECASE,
)
_EN_TEXT_TERM_RE = re.compile(_EN_TEXT_TERM, re.IGNORECASE)

_RULES: tuple[_Rule, ...] = (
    _Rule(
        re.compile(
            r"(?:避免|不要|禁止)(?:未成年|幼态|童颜|低龄|儿童)"
            r"(?:外貌|面孔|感|化)?"
        ),
        "明确成年女性外貌，成熟自然的气质",
        ("未成年", "幼态", "童颜"),
        "把「避免未成年外貌」改写为成年女性描述",
    ),
    _Rule(
        re.compile(
            r"(?:不要|避免|禁止)(?:看|直视|盯着|看向|望向)(?:着)?"
            r"(?:镜头|摄像头|观众)"
        ),
        "视线自然垂落，看向画外",
        ("看镜头", "直视镜头"),
        "把「不要看镜头」改写为肯定的视线方向",
    ),
    _Rule(
        re.compile(r"不看(?:着)?(?:镜头|摄像头|观众)"),
        "视线自然垂落，看向画外",
        ("看镜头", "直视镜头"),
        "把「不看镜头」改写为肯定的视线方向",
    ),
    _Rule(
        re.compile(
            r"(?:不要|避免|禁止)(?:侧向|侧身|回头|背对镜头)"
        ),
        "正面或微侧朝向镜头",
        ("侧身", "回头", "背对镜头"),
        "把「不要侧向/回头」改写为朝向镜头",
    ),
    _Rule(
        re.compile(
            r"(?:不要|避免|禁止|别|无需|不用|无|没有)"
            r"(?:过度|过分|严重)?(?:磨皮|美颜)"
        ),
        "真实皮肤纹理与自然肤色",
        ("磨皮", "塑料皮肤"),
        "把「不要磨皮/美颜」改写为真实皮肤描述",
    ),
    _Rule(
        re.compile(r"(?:无|没有|不要|避免)(?:滤镜|美颜滤镜)"),
        "直出色彩，自然影调",
        ("滤镜", "过度美颜"),
        "把「无滤镜」改写为直出色彩",
    ),
    _Rule(
        re.compile(r"(?:无|没有|不要|避免)(?:妆感|浓妆艳抹|浓妆|厚重妆容)"),
        "素颜或淡妆，自然肤色",
        ("浓妆", "厚重妆容"),
        "把「无妆感/不要浓妆」改写为素颜或淡妆",
    ),
    _Rule(
        re.compile(r"(?:无|没有|不要|避免)(?:闪光|闪光灯|夸张光晕|光晕)"),
        "自然光线，光晕克制",
        ("闪光", "夸张光晕"),
        "把闪光/光晕否定改写为自然光线",
    ),
    _Rule(
        re.compile(r"(?:不|不要|避免|禁止)(?:暴露|走光)"),
        "着装得体，剪裁合身",
        ("过度暴露", "走光"),
        "把不暴露/走光否定改写为得体着装",
    ),
    _Rule(
        re.compile(
            r"(?:不要|避免|禁止|没有)(?:多余|多出|多|六根|七根)?(?:的)?"
            r"(?:手指|指头|多指)"
        ),
        "双手结构正确，五指清晰自然",
        ("多余手指", "畸形手"),
        "把「不要多余手指」改写为手部结构描述",
    ),
    _Rule(
        re.compile(r"(?:不要|避免|禁止)(?:茶具|壶|杯)(?:变形|结构错误)"),
        "茶具结构准确，壶嘴、把手与杯口比例正确",
        ("茶具变形",),
        "把茶具变形否定改写为结构准确",
    ),
    _Rule(
        re.compile(
            r"(?:不要|避免|禁止)(?:腿部或脸部|脸部|腿部|肢体)?变形"
        ),
        "人体与面部结构准确，比例自然",
        ("变形", "结构错误"),
        "把腿部/脸部变形否定改写为结构准确",
    ),
    _Rule(
        re.compile(r"(?:不要|避免|禁止)(?:畸形|变形|扭曲|比例失调|人体结构错误)"),
        "人体结构准确，比例自然",
        ("畸形", "变形", "扭曲"),
        "把「不要畸形/变形」改写为结构准确",
    ),
    _Rule(
        re.compile(r"(?:不要|避免|禁止)(?:过曝|过亮|死白|欠曝|过暗|死黑)"),
        "曝光均衡，高光与阴影保留细节",
        ("过曝", "欠曝", "死黑", "死白"),
        "把曝光类否定改写为曝光均衡",
    ),
    _Rule(
        re.compile(
            r"(?:不要|避免|禁止)(?:了)?(?:明显的)?"
            r"(?:影棚轮廓光|影棚光|硬阴影|生硬阴影|完美柔光箱效果|柔光箱效果)"
            r"(?:或|和)?(?:完美的)?(?:柔光箱效果)?"
        ),
        "柔和自然光，阴影过渡自然",
        ("硬阴影", "影棚光", "轮廓光"),
        "把硬阴影/影棚光否定改写为自然柔光",
    ),
    _Rule(
        re.compile(
            r"(?:不要|避免|禁止)(?:过强对比|过度橙黄偏色|过度橙黄|偏色|过饱和)"
        ),
        "曝光均衡，白平衡准确，明暗层次自然",
        ("过强对比", "偏色", "过饱和"),
        "把偏色/强对比否定改写为准确白平衡与柔和层次",
    ),
    _Rule(
        re.compile(r"(?:不要|避免|禁止)(?:模糊|低清晰度|虚焦|失焦)"),
        "画面清晰锐利，焦点准确",
        ("模糊", "失焦", "低清晰度"),
        "把模糊类否定改写为清晰锐利",
    ),
    _Rule(
        re.compile(r"(?:不要|避免|禁止)(?:噪点|噪波|颗粒感)"),
        "画面干净细腻",
        ("噪点", "噪波"),
        "把噪点类否定改写为干净细腻",
    ),
    _Rule(
        re.compile(
            r"(?:不要|避免|禁止)"
            r"(?:过度美肌(?:修饰|处理)|过度加工|AI平滑的塑料感皮肤|AI平滑的皮肤|"
            r"CGI|CG感|CG|AI感|塑料感|网红脸|陶瓷肌|假脸|过度美颜|插图风格)"
            r"(?:或|和)?(?:塑料感|CG感|CGI|插图风格|3D渲染)?"
            r"(?:的)?(?:皮肤|质感|风格|感)?",
            re.IGNORECASE,
        ),
        "真实摄影质感，皮肤有自然纹理",
        ("CGI", "塑料感", "过度磨皮", "AI感", "插图风格"),
        "把「CGI/塑料感/过度美肌」改写为真实摄影质感的皮肤",
    ),
    _Rule(
        re.compile(r"(?:不要|避免|禁止)(?:微笑|露齿笑|露齿|大笑|笑)"),
        "表情平静自然，嘴唇自然闭合",
        ("微笑", "露齿"),
        "把「不要笑」改写为平静表情",
    ),
    _Rule(
        re.compile(
            rf"(?:不要|避免|禁止|不){_POSE_TERM}"
            rf"(?:[、,，和或与\s]*{_POSE_TERM})*"
        ),
        "自然动态姿势，身体重心有变化",
        ("摆拍", "僵硬", "普通站姿"),
        "把「不要摆拍/普通站姿」改写为自然动态姿势",
    ),
    _Rule(
        re.compile(
            r"(?:不要|避免|禁止|不出现|无|没有)"
            r"(?:错字|乱码|缺笔画|重复字|错别字|文字变形|多余文字|引号|英文拼写错误)"
            r"(?:[、,，和或与\s]*(?:错字|乱码|缺笔画|重复字|错别字|文字变形|多余文字|引号|英文拼写错误))*"
        ),
        "字形准确，笔画完整",
        ("错字", "乱码", "缺笔画", "重复字", "多余文字", "引号"),
        "把错字/乱码否定改写为字形准确",
    ),
    _Rule(
        re.compile(r"(?:不要|避免|禁止)(?:杂物|路人|背景人|人群|游客)"),
        "背景干净简洁",
        ("杂物", "路人", "人群"),
        "把背景杂物类否定改写为干净背景",
    ),
    _Rule(
        re.compile(r"(?:不要|避免|禁止)(?:反光|鬼影|重影|眩光)"),
        "画面通透，光影自然",
        ("反光", "鬼影", "重影"),
        "把反光/鬼影类否定改写为通透光影",
    ),
    _Rule(
        re.compile(
            r"(?:不要|避免|禁止)(?:裁切|截断|裁脚|切脚|裁手|切手|裁头|切头)"
        ),
        "构图完整，主体与双脚完整可见",
        ("裁切", "截断", "裁脚"),
        "把裁切类否定改写为构图完整",
    ),
    _Rule(
        re.compile(r"(?:不要|避免|禁止)(?:痘痘|痘印|疤痕|瑕疵|黑眼圈|眼袋)"),
        "皮肤自然干净，眼周状态自然",
        ("痘痘", "痘印", "疤痕", "瑕疵", "黑眼圈", "眼袋"),
        "把皮肤瑕疵类否定改写为自然皮肤",
    ),
    _Rule(
        re.compile(r"(?:不要|避免|禁止)(?:油腻|油光|油亮)"),
        "皮肤清爽自然，哑光质感",
        ("油腻", "油光"),
        "把油光类否定改写为清爽哑光",
    ),
    _Rule(
        re.compile(r"(?:不要|避免|禁止)(?:僵硬|呆板|木讷)"),
        "姿态自然放松，表情生动",
        ("僵硬", "呆板"),
        "把僵硬/呆板否定改写为自然放松",
    ),
    _Rule(
        re.compile(
            r"(?:不要|避免|禁止)(?:商业泳池大片感|商业大片感|杂志大片感|广告大片感)"
        ),
        "日常随手拍，生活感与松弛感",
        ("商业大片感",),
        "把商业大片感否定改写为日常随手拍",
    ),
    _Rule(
        re.compile(r"(?:不要|避免|禁止)(?:成熟浓颜感|浓颜|成熟感)"),
        "清透淡颜，年轻自然",
        ("浓颜", "成熟感"),
        "把成熟浓颜否定改写为清透淡颜",
    ),
    _Rule(
        re.compile(r"(?:不要|避免|禁止)(?:夸张闪亮|闪亮|浮夸)"),
        "低调质感，克制的光影",
        ("夸张闪亮", "浮夸"),
        "把夸张闪亮否定改写为低调质感",
    ),
    _Rule(
        re.compile(
            r"(?:不要|避免|禁止)"
            r"(?:过度暴露|过于暴露|露骨|低俗视角|不恰当或暗示性的拍摄角度|庸俗|低俗)"
        ),
        "着装得体，视角克制，画面含蓄",
        ("过度暴露", "露骨", "低俗视角"),
        "把暴露/低俗类否定改写为得体克制的视角",
    ),
    _Rule(
        re.compile(r"(?:不要|避免|禁止)(?:镜像自拍)"),
        "自然抓拍构图",
        ("镜像自拍",),
        "把镜像自拍否定改写为自然抓拍",
    ),
    _Rule(
        re.compile(r"(?:不要|避免|禁止)(?:遮挡脸部|挡住脸)"),
        "面部完整可见，五官清晰",
        ("遮挡脸部",),
        "把遮挡脸部否定改写为面部完整",
    ),
    _Rule(
        re.compile(r"(?:不要|避免|禁止)(?:抢人物主体|喧宾夺主)"),
        "背景与道具弱化，主体突出",
        ("背景抢主体",),
        "把抢主体否定改写为主体突出",
    ),
    _Rule(
        re.compile(
            r"(?:不要|避免|禁止|不出现)(?:生成)?(?:任何)?"
            r"(?:第二人称的他人之手|拍摄者的手|他人的手)"
        ),
        "只保留人物自己的手",
        ("他人的手", "拍摄者的手"),
        "把他人之手否定改写为只保留主体自己的手",
    ),
    _Rule(
        re.compile(r"(?:不要|避免|禁止)(?:全身同色|和妆容完全同色)"),
        "服装与妆容有色彩层次",
        ("全身同色",),
        "把同色否定改写为有色彩层次",
    ),
    _Rule(
        re.compile(r"(?:不要|避免|禁止)(?:向后坐或坐到脚跟上)"),
        "自然坐姿，重心稳定",
        ("坐到脚跟上",),
        "把后坐/坐脚跟否定改写为自然坐姿",
    ),
    _Rule(
        re.compile(r"\b(?:no|without)\s+cropping\b", re.IGNORECASE),
        "full body fully in frame",
        ("cropping",),
        "把「no cropping」改写为完整入镜",
    ),
    _Rule(
        re.compile(
            r"\bavoid\s+(?:looking\s+at\s+(?:the\s+)?camera|eye\s+contact)\b",
            re.IGNORECASE,
        ),
        "gaze directed off-camera",
        ("looking at camera", "eye contact"),
        "把英文「avoid looking at camera」改写为画外视线",
    ),
    _Rule(
        re.compile(r"\b(?:no|without)\s+makeup\b", re.IGNORECASE),
        "bare natural skin",
        ("makeup",),
        "把英文「no makeup」改写为自然素颜",
    ),
    _Rule(
        re.compile(r"\b(?:no|without)\s+(?:blur|noise)\b", re.IGNORECASE),
        "sharp clean image",
        ("blur", "noise"),
        "把英文模糊/噪点否定改写为清晰干净",
    ),
)


def _clean_text(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"[ \t]*([，,。；;、])[ \t]*", r"\1", text)
    return text.strip()


def _split_terms(text: str) -> list[str]:
    return [
        part.strip().strip("。.；;，,")
        for part in re.split(r"[,，;；\n]+", text or "")
        if part.strip().strip("。.；;，,")
    ]


def _dedupe(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        key = term.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(term.strip())
    return out


def _text_replacement(positive: str) -> str:
    if _CALLIGRAPHY_RE.search(positive):
        return "纸面干净，只保留主体文字"
    if _SIGN_RE.search(positive):
        return "招牌文字只保留指定内容，画面干净"
    return "画面干净，只有主体与场景"


def _collapse_repeated_phrases(text: str) -> str:
    """「不要侧向，不要回头」会各自换出同一句；合并相邻重复短语。"""
    pattern = re.compile(
        r"(?P<phrase>[^，,。；;、\n]{6,})(?:[，,、]\s*(?P=phrase))+"
    )
    text = pattern.sub(lambda match: match.group("phrase"), text)
    # 顿号列表里的重复项：phrase 本身可能含逗号（如「自然光线，光晕克制」）。
    item_pattern = re.compile(r"(?P<item>[^、\n]{2,})(?:、(?P=item))+")
    return item_pattern.sub(lambda match: match.group("item"), text)


def _split_neg_items(text: str) -> list[str]:
    return [
        _NEG_ITEM_PREFIX_RE.sub("", item.strip()).strip().strip("。.；;，,")
        for item in re.split(r"[、,，;；。]+", text or "")
        if item.strip().strip("。.；;，,")
    ]


def _extract_negative_sections(text: str) -> tuple[str, list[str], list[str]]:
    """把【避免】/【负面】/Negative: 整段移到负向，而不是留在正向里。"""
    lines = text.splitlines()
    kept: list[str] = []
    terms: list[str] = []
    notes: list[str] = []
    removed = False
    index = 0
    while index < len(lines):
        match = _NEG_SECTION_HEADER_RE.match(lines[index])
        if not match:
            kept.append(lines[index])
            index += 1
            continue
        removed = True
        notes.append("把【避免/负面】段落从正向移到负向")
        content = match.group(1).strip()
        if content:
            terms.extend(_split_neg_items(content))
            index += 1
            continue
        index += 1
        while index < len(lines):
            line = lines[index]
            if not line.strip() or line.lstrip().startswith("【"):
                break
            terms.extend(_split_neg_items(line))
            index += 1
    return ("\n".join(kept) if removed else text), terms, notes


def _match_rule_item(item: str) -> _Rule | None:
    for candidate in (item, "不要" + item, "避免" + item):
        for rule in _RULES:
            if rule.pattern.search(candidate):
                return rule
    return None


def _rule_covers_whole(prefix: str, body: str) -> bool:
    probe = prefix + body
    for rule in _RULES:
        for match in rule.pattern.finditer(probe):
            if match.start() == 0 and match.end() == len(probe):
                return True
    return False


def _rewrite_negation_lists(
    text: str, negative_effective: bool,
) -> tuple[str, list[str], list[str], bool, list[str]]:
    """逐项处理「避免 A、B、C」：命中项改写，未命中项按能力路由。"""
    notes: list[str] = []
    extracted: list[str] = []
    warnings: list[str] = []
    changed = False

    def repl(match: re.Match[str]) -> str:
        nonlocal changed
        prefix = match.group("prefix")
        body = match.group("body")
        if not any(sep in body for sep in ("、", "和", "及", "与", "或")):
            return match.group(0)
        if _rule_covers_whole(prefix, body):
            return match.group(0)
        items = [
            item.strip() for item in _LIST_SEP_RE.split(body)
            if item.strip() and item.strip() not in _LIST_STOPWORDS
        ]
        if len(items) < 2:
            return match.group(0)

        replacements: list[str] = []
        unmatched: list[str] = []
        for item in items:
            rule = _match_rule_item(item)
            if rule is None:
                unmatched.append(item)
                continue
            if rule.replacement not in replacements:
                replacements.append(rule.replacement)
            extracted.extend(rule.negatives)

        changed = True
        notes.append(f"把列表否定逐项拆分：{'、'.join(items)}")

        residual = ""
        if negative_effective:
            for item in unmatched:
                term = _NEG_ITEM_PREFIX_RE.sub("", item).strip()
                if term:
                    extracted.append(term)
        elif unmatched:
            residual = prefix + "、".join(unmatched)
            shown = "、".join(unmatched[:4])
            suffix = " 等" if len(unmatched) > 4 else ""
            warnings.append(f"列表型否定仍有未处理项：{shown}{suffix}")

        parts = []
        if replacements:
            parts.append("；".join(replacements))
        if residual:
            parts.append(residual)
        return "；".join(parts)

    text = _NEG_BLOCK_RE.sub(repl, text)
    return text, notes, extracted, changed, warnings


def _rewrite_safety_blocks(text: str) -> tuple[str, list[str], list[str]]:
    """安全项可能藏在顿号列表里，不能只处理紧挨着否定词的那一项。"""
    notes: list[str] = []
    extracted: list[str] = []

    def repl(match: re.Match[str]) -> str:
        body = match.group("body")
        if not _SAFETY_RE.search(body):
            return match.group(0)
        items = [item.strip() for item in re.split(r"[、和及]", body) if item.strip()]
        extracted.extend(items)
        notes.append("把含未成年/幼态的排除列表改写为成年女性描述")
        return "明确成年女性外貌，真实摄影质感，成熟自然的气质"

    return _NEG_BLOCK_RE.sub(repl, text), notes, extracted


def compile_prompt(
    positive: str,
    negative: str = "",
    *,
    negative_effective: bool,
) -> CompiledPrompt:
    """把一段正向提示词编译成「肯定式正向 + 可选负向」。

    `negative_effective` 必须由工作流能力探测给出；编译器不猜工作流。
    """
    original_positive = positive or ""
    if not original_positive.strip():
        return CompiledPrompt(
            positive=original_positive,
            negative=negative,
            negative_effective=negative_effective,
        )

    text = original_positive
    notes: list[str] = []
    warnings: list[str] = []
    extracted: list[str] = []
    changed = False
    text, section_terms, section_notes = _extract_negative_sections(text)
    if section_notes:
        notes.extend(section_notes)
        extracted.extend(section_terms)
        changed = True

    text, safety_notes, safety_terms = _rewrite_safety_blocks(text)
    if safety_notes:
        notes.extend(safety_notes)
        extracted.extend(safety_terms)
        changed = True

    text_matches = list(_TEXT_NEG_RE.finditer(text))
    if text_matches:
        terms: list[str] = []
        for match in text_matches:
            terms.extend(_TEXT_TERM_RE.findall(match.group("terms")))
        replacement = _text_replacement(text)
        text = _TEXT_NEG_RE.sub(replacement, text)
        notes.append(f"把文字/水印类否定改写为「{replacement}」")
        extracted.extend(terms)
        changed = True

    en_text_matches = list(_EN_TEXT_NEG_RE.finditer(text))
    if en_text_matches:
        terms = []
        for match in en_text_matches:
            terms.extend(_EN_TEXT_TERM_RE.findall(match.group("terms")))
        text = _EN_TEXT_NEG_RE.sub("clean image with only the subject and scene", text)
        notes.append("把英文 no text/watermark/logo 改写为干净画面")
        extracted.extend(terms)
        changed = True

    text, list_notes, list_terms, list_changed, list_warnings = _rewrite_negation_lists(
        text, negative_effective,
    )
    if list_changed:
        notes.extend(list_notes)
        extracted.extend(list_terms)
        warnings.extend(list_warnings)
        changed = True

    for rule in _RULES:
        if not rule.pattern.search(text):
            continue
        text = rule.pattern.sub(rule.replacement, text)
        notes.append(rule.note)
        extracted.extend(rule.negatives)
        changed = True

    collapsed = _collapse_repeated_phrases(text)
    if collapsed != text:
        text = collapsed
        changed = True
        notes.append("合并重复的改写短语")

    leftovers = _dedupe([
        match.group(0).strip() for match in _LEFTOVER_NEG_RE.finditer(text)
    ])
    if leftovers:
        shown = "、".join(f"「{item}」" for item in leftovers[:3])
        suffix = f" 等 {len(leftovers)} 处" if len(leftovers) > 3 else ""
        warnings.append(
            f"仍有未识别的否定 {shown}{suffix}，已保留原样；"
            "建议改成肯定描述，或确认工作流支持负向后手动填入负向"
        )

    # 没有任何规则命中时逐字保留原文：不为了清理空白而改动英文/无否定提示。
    positive_out = _clean_text(text) if changed else original_positive
    existing = _split_terms(negative)
    extracted_clean = _dedupe([term for term in extracted if term])

    if negative_effective and extracted_clean:
        negative_out = ", ".join(_dedupe(existing + extracted_clean))
    else:
        # 不合并时保持用户负向原文，避免无意义的逗号/空白归一化。
        negative_out = negative
        if not negative_effective and extracted_clean:
            notes.append("当前工作流负向不生效：只应用肯定式改写，未把排除词写入负向")
        if not negative_effective and existing:
            warnings.append("当前工作流负向不生效，已有负向内容不会提交")

    return CompiledPrompt(
        positive=positive_out,
        negative=negative_out,
        notes=tuple(notes),
        warnings=tuple(warnings),
        extracted=tuple(extracted_clean),
        negative_effective=negative_effective,
    )
