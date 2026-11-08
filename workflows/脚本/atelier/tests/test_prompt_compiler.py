"""单框提示词编译器：否定改写、负向提取与保守边界。"""

from app.services.prompt_compiler import compile_for_submission, compile_prompt


def test_compile_for_submission_matches_direct_compile():
    direct = compile_prompt("站立，避免普通站姿", "水印", negative_effective=True)
    via_entry = compile_for_submission("站立，避免普通站姿", "水印", negative_effective=True)
    assert via_entry == direct


def test_compile_for_submission_skips_rewrite_for_manual_edit():
    result = compile_for_submission(
        "不要军姿，保持原样", "水印", negative_effective=True, skip_compile=True,
    )
    assert result.positive == "不要军姿，保持原样"
    assert result.negative == "水印"
    assert result.extracted == ()


def test_plain_prompt_is_unchanged():
    result = compile_prompt("二十五岁女性，白衬衫，85mm 镜头，自然光", negative_effective=True)
    assert result.positive == "二十五岁女性，白衬衫，85mm 镜头，自然光"
    assert result.negative == ""
    assert result.notes == ()
    assert result.warnings == ()


def test_gaze_negation_becomes_positive_rewrite():
    result = compile_prompt("她不要看镜头，穿白衬衫", negative_effective=True)
    assert "不要看镜头" not in result.positive
    assert "视线自然垂落，看向画外" in result.positive
    assert "看镜头" in result.negative
    assert result.notes


def test_text_negation_uses_calligraphy_context():
    result = compile_prompt(
        "书法卷轴，不要落款、印章，只有静水流深",
        negative_effective=True,
    )
    assert "不要落款" not in result.positive
    assert "纸面干净，只保留主体文字" in result.positive
    assert "静水流深" in result.positive
    assert "落款" in result.negative and "印章" in result.negative


def test_text_negation_respects_signage_context():
    result = compile_prompt("便利店招牌，不要多余文字", negative_effective=True)
    assert "招牌文字只保留指定内容" in result.positive
    assert "文字" in result.negative


def test_multiple_text_artifacts_are_extracted_together():
    result = compile_prompt("背景干净，不要文字、水印、印章", negative_effective=True)
    for term in ("文字", "水印", "印章"):
        assert term in result.negative
    assert "不要文字" not in result.positive
    assert "画面干净" in result.positive


def test_ineffective_negative_only_rewrites_known_patterns():
    result = compile_prompt("不要看镜头，不要戴帽子", "已有负向", negative_effective=False)
    # 已知模式改成肯定描述
    assert "视线自然垂落，看向画外" in result.positive
    # 未知排除保持原样并提示，不静默删掉
    assert "不要戴帽子" in result.positive
    assert any("未识别" in item for item in result.warnings)
    # 负向不合并新词，也不假装旧负向会生效
    assert result.negative == "已有负向"
    assert "看镜头" not in result.negative
    assert any("不会提交" in item for item in result.warnings)


def test_existing_negative_is_deduped():
    result = compile_prompt("不要水印，不要模糊", "水印, 模糊", negative_effective=True)
    terms = [item.strip() for item in result.negative.split(",")]
    assert terms.count("水印") == 1
    assert terms.count("模糊") == 1


def test_fingers_and_anatomy_rewrites():
    result = compile_prompt("不要多余的手指，不要畸形", negative_effective=True)
    assert "双手结构正确，五指清晰自然" in result.positive
    assert "人体结构准确，比例自然" in result.positive
    assert "多余手指" in result.negative
    assert "畸形" in result.negative


def test_floating_clothes_anatomy_rewrite():
    """V2-C：禁止漂浮衣架式人体 → 四肢完整肯定句 + 缺手缺脚类负向。"""
    result = compile_prompt(
        "两人的手、手指、手臂、腿、脚必须完整自然出现；禁止漂浮衣架式人体。",
        negative_effective=True,
    )
    assert "禁止漂浮衣架式人体" not in result.positive
    assert "人体结构完整，四肢与手脚自然呈现" in result.positive
    for term in ("缺少手", "缺少手指", "缺少腿", "缺少脚", "漂浮衣物", "衣架",
                 "人体结构缺失", "肢体融合", "第三个人", "多余的腿", "多余的脚",
                 "多余的手", "重复人体"):
        assert term in result.negative


def test_extracted_negation_does_not_leave_double_punctuation():
    """否定整段被抽走后不能残留「。。」「。，」，否则正向提示词会带坏标点。"""
    result = compile_prompt(
        "两人的相对位置严格按图中的两个人形。禁止合并成一个人、禁止裁掉其中一人、"
        "禁止只画一个人。\n"
        "膝盖的朝向与弯曲程度。不要画成双脚并拢、身体笔直、手臂自然下垂的站立姿势，"
        "不要军姿。",
        negative_effective=True,
    )
    assert "。。" not in result.positive
    assert "。，" not in result.positive


def test_compiler_is_idempotent():
    first = compile_prompt("不要看镜头，穿白衬衫", negative_effective=True)
    second = compile_prompt(first.positive, first.negative, negative_effective=True)
    assert second.positive == first.positive
    assert second.negative == first.negative
    assert second.notes == ()


def test_positive_phrases_with_wu_are_not_misread():
    text = "无瑕肌肤，85mm 镜头，白色衬衫"
    result = compile_prompt(text, negative_effective=True)
    assert result.positive == text
    assert result.warnings == ()


def test_oil_and_skin_rewrites():
    result = compile_prompt("不要油光，不要痘痘", negative_effective=True)
    assert "皮肤清爽自然，哑光质感" in result.positive
    assert "皮肤自然干净，眼周状态自然" in result.positive
    assert "油光" in result.negative
    assert "痘痘" in result.negative


def test_longest_match_does_not_leave_residue():
    """「没有浓妆艳抹」不能只吃掉「浓妆」，留下「艳抹」。"""
    result = compile_prompt("一张清纯面孔，没有浓妆艳抹，只有明媚", negative_effective=True)
    assert "艳抹" not in result.positive
    assert "素颜或淡妆" in result.positive


def test_english_prompt_without_negation_is_byte_identical():
    text = "full body shot, person vertically centered in frame, 85mm lens"
    result = compile_prompt(text, negative_effective=True)
    assert result.positive == text
    assert result.notes == ()


def test_english_no_cropping_is_rewritten():
    result = compile_prompt(
        "full body shot, feet visible, no cropping", negative_effective=True,
    )
    assert "no cropping" not in result.positive
    assert "full body fully in frame" in result.positive
    assert "cropping" in result.negative


def test_english_no_text_watermark_logo_are_extracted_together():
    result = compile_prompt(
        "cinematic portrait, no text, no watermark, no logo", negative_effective=True,
    )
    assert "no text" not in result.positive
    for term in ("text", "watermark", "logo"):
        assert term in result.negative
    assert result.positive.count("clean image with only the subject and scene") == 1


def test_adult_safety_negation_is_rewritten():
    result = compile_prompt("书店过道，避免未成年外貌，大学生气质", negative_effective=True)
    assert "未成年" not in result.positive
    assert "明确成年女性外貌" in result.positive
    assert "未成年" in result.negative


def test_hard_light_and_studio_light_are_rewritten():
    a = compile_prompt("窗边人像，避免硬阴影", negative_effective=True)
    assert "硬阴影" not in a.positive
    assert "柔和自然光" in a.positive

    b = compile_prompt("卧室，避免了明显的影棚轮廓光或完美的柔光箱效果", negative_effective=True)
    assert "影棚轮廓光" not in b.positive
    assert "柔光箱" not in b.positive
    assert "柔和自然光" in b.positive


def test_crop_and_pose_leftovers_are_rewritten():
    a = compile_prompt("全身照，避免裁脚", negative_effective=True)
    assert "裁脚" not in a.positive
    assert "构图完整" in a.positive

    b = compile_prompt("站在门口，避免普通站姿", negative_effective=True)
    assert "普通站姿" not in b.positive
    assert "自然动态姿势" in b.positive


def test_leg_face_deformation_and_tea_set_are_rewritten():
    a = compile_prompt("坐姿，避免腿部或脸部变形", negative_effective=True)
    assert "变形" not in a.positive
    assert "人体与面部结构准确" in a.positive

    b = compile_prompt("奉茶，不要茶具变形", negative_effective=True)
    assert "茶具变形" not in b.positive
    assert "茶具结构准确" in b.positive


def test_style_leftovers_are_rewritten():
    result = compile_prompt(
        "日常街拍，避免过度美肌修饰或塑料感，不要商业泳池大片感，"
        "不要成熟浓颜感，不要夸张闪亮，避免过度暴露",
        negative_effective=True,
    )
    for leftover in ("过度美肌", "商业泳池大片感", "成熟浓颜感", "夸张闪亮", "过度暴露"):
        assert leftover not in result.positive
    assert "真实摄影质感" in result.positive
    assert "日常随手拍" in result.positive
    assert "清透淡颜" in result.positive
    assert "低调质感" in result.positive
    assert "着装得体" in result.positive


def test_repeated_replacements_are_collapsed():
    result = compile_prompt("柔光，无闪光、无夸张光晕", negative_effective=True)
    assert result.positive.count("自然光线，光晕克制") == 1


def test_direction_and_cgi_leftovers_are_rewritten():
    result = compile_prompt("镜头前，不要侧向，不要回头，避免CGI", negative_effective=True)
    for leftover in ("不要侧向", "不要回头", "避免CGI"):
        assert leftover not in result.positive
    assert result.positive.count("正面或微侧朝向镜头") == 1
    assert "真实摄影质感" in result.positive


def test_safety_term_inside_a_list_removes_the_whole_negative_list():
    result = compile_prompt(
        "书店过道，避免未成年外貌、学校制服感、cosplay、塑料AI脸，大学生气质",
        negative_effective=True,
    )
    assert "未成年" not in result.positive
    assert "学校制服感" not in result.positive
    assert "cosplay" not in result.positive
    assert "明确成年女性外貌" in result.positive
    for term in ("未成年", "学校制服感", "cosplay", "塑料AI脸"):
        assert term in result.negative


def test_negative_section_is_removed_and_extracted():
    text = "【主题】人像\n【避免】错字、乱码、印章、水印\n【光线】柔光"
    result = compile_prompt(text, negative_effective=True)
    assert "【避免】" not in result.positive
    for term in ("错字", "乱码", "印章", "水印"):
        assert term not in result.positive
        assert term in result.negative
    assert "【主题】" in result.positive
    assert "【光线】" in result.positive


def test_negative_section_is_removed_even_when_negative_is_ineffective():
    text = "【主题】人像\n【避免】印章、水印"
    result = compile_prompt(text, negative_effective=False)
    assert "印章" not in result.positive
    assert result.negative == ""
    assert any("负向不生效" in item for item in result.notes)


def test_calligraphy_prompt_has_no_negative_section_left():
    text = (
        "【场景】背景挂一幅竖幅宣纸书法，竖排四个汉字「静」「水」「流」「深」；"
        "只写这四个字，不要落款、印章、英文或多余文字。\n"
        "【避免】错字、乱码、缺笔画、文字变形、多余文字、落款、印章、"
        "AI网红脸、过度磨皮、塑料皮肤、直视镜头、畸形手指、水印、Logo。"
    )
    result = compile_prompt(text, negative_effective=True)
    assert "【避免】" not in result.positive
    assert "静" in result.positive and "深" in result.positive
    assert "落款" not in result.positive
    assert "印章" not in result.positive
    for term in ("落款", "印章", "水印", "Logo"):
        assert term in result.negative


def test_text_error_list_is_consumed():
    result = compile_prompt(
        "招牌，不出现错字、乱码、缺笔画、重复字", negative_effective=True,
    )
    for term in ("错字", "乱码", "缺笔画", "重复字"):
        assert term not in result.positive
        assert term in result.negative
    assert "字形准确，笔画完整" in result.positive
    assert not any("列表型否定" in item for item in result.warnings)


def test_overposed_and_stiff_posture_list_is_consumed():
    result = compile_prompt("人像，避免过度摆拍、僵硬姿势", negative_effective=True)
    for term in ("过度摆拍", "僵硬姿势"):
        assert term not in result.positive
    assert "自然动态姿势" in result.positive


def test_list_items_are_moved_to_negative_when_effective():
    result = compile_prompt(
        "站立，避免普通站姿、无互动、平铺表情", negative_effective=True,
    )
    for item in ("普通站姿", "无互动", "平铺表情"):
        assert item not in result.positive
    assert "自然动态姿势" in result.positive
    assert "互动" in result.negative
    assert "平铺表情" in result.negative
    assert not any("列表型否定" in item for item in result.warnings)


def test_unmatched_list_items_survive_with_warning_when_ineffective():
    result = compile_prompt(
        "站立，避免普通站姿、无互动、平铺表情", negative_effective=False,
    )
    assert "普通站姿" not in result.positive
    assert "无互动" in result.positive
    assert "平铺表情" in result.positive
    assert any("列表型否定仍有未处理项" in item for item in result.warnings)


def test_compound_phrase_is_not_split_into_bad_negative_terms():
    result = compile_prompt("坐姿，避免腿部或脸部变形", negative_effective=True)
    assert "人体与面部结构准确" in result.positive
    assert "腿部" not in result.negative
    assert "脸部" not in result.negative
