#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量插入提示词 V3 — 支持【】分段、自动拆分、清洗检查、去重。

用法：
    python batch_insert_prompts.py --file prompts.txt
    python batch_insert_prompts.py --file prompts.txt --dry-run
    python batch_insert_prompts.py --file prompts.txt --strict
    # LLM智能命名：预览碎片 → 复制给AI生成标题 → 导入
    python batch_insert_prompts.py --file prompts.txt --llm-name
    python batch_insert_prompts.py --file prompts.txt --import-names llm_names.json

输入格式（以三个以上空行分隔，见 split_blocks）：
    方式1: 【人物面部】...【姿态动作】... + 元数据行
    方式2: 三段式(人+衣 / 姿态 / 场景) + 元数据行 → 自动拆分
    方式3: 纯文本 + 元数据行
    方式4: 仅提示词，无元数据 → 元数据字段自动置空

============================= 信达雅规范（必读） =============================

【核心原则】
  prompt 正文的语言质量是第一位的。杜绝机械的词汇堆砌（如"韩风冷色调
  网红美白滤镜，极致冷白皮，通体雪白"），代之以有人味、有画面感、有韵律
  的中文文学描述。

【碎片语义 —— 每类碎片只装对的内容】
  拍摄视角：镜头参数、机位、构图、焦距、画幅比例
  人物面部：脸型、五官、妆容、表情、发色、发型、肤色
  人物身材：体型、曲线、比例、身高、四肢
  人物服饰：衣服、配饰、鞋、包
  姿态动作：身体姿势、手势、站位、眼神方向、动态
  场景环境：地点、背景、道具、空间层次
  光影色调：光源方向、色温、色调、明暗、氛围光
  画风技术：画质、分辨率、摄影风格、流派、器材、胶片质感

  ❌ 禁止：【人物身材】里写年龄或网红标签
  ❌ 禁止：【画风技术】里写构图或镜头参数
  ❌ 禁止：【人物面部】里写服饰描述（如"乳沟"）
  ❌ 禁止：【拍摄视角】里写场景环境描述

【语言质量 —— 什么才叫信达雅】
  ✅ 好："她的皮肤在冷白荧光下呈现出瓷器上覆了一层薄釉般的通透感。"
  ❌ 差："韩风冷色调网红美白滤镜，极致冷白皮，通体雪白。"
  ✅ 好："她端着一碗水果，慵懒地靠在某处，姿态放松得像刚睡醒的午后。"
  ❌ 差："端着一碗水果，姿态闲适。"
  关键：每句都应有画面感，用比喻和细节让读者能"看见"这个场景。

【标点与断句】
  每条碎片的正文必须有完整的标点（句号、逗号等）。长句在自然边界处断开。
  段落间有呼吸感，不堆砌成天书。

【碎片标记的使用】
  - 碎片标题【xxx】必须与 FRAGMENT_TYPES 中定义的完全一致
  - 无内容的碎片直接移除整行，不留空标题（会导致正则吞并）
  - 碎片间用一个空行分隔，方便前端展示

【外语处理】
  所有非中文的提示词必须翻译为中文再入库。翻译要达到信达雅标准，
  不能是机器直译的僵硬感。

【入库操作规范】
  - 本脚本已内置 prompt 文本去重，同一条不会重复插入
  - 但绝不能把整个文件重新全量跑一遍来"更新"已有条目
  - 新增条目时只追加到源文件末尾，然后运行脚本
  - 如需修改已有条目，直接改源文件的对应内容，脚本入库时会自动插入
    新版本（prompt 文本不同），然后手动清理旧版本
  - ⚠️ 禁止直接用 Python 命令字符串追加内容到源文件（如
    `python -c "with open(...) as f: f.write(...)"`）
    这种方式极易导致格式错误（如缺失标点、碎片化词汇）
  - ✅ 正确做法：手动编辑源文件，或用脚本生成内容后手动复制到文件末尾

【前端与出图联动】
  - prompt 字段存带【】标题的展示格式（空行分隔碎片）
  - 前端复制按钮用 JS 去标题：text.replace(/【[^】]+】\\s*/g, '')
  - 传 ComfyUI 时 Python 去标题：re.sub(r'【[^】]+】\\s*', '', prompt)
  - 前端展示碎片标题时用 .frag-tag CSS 类高亮显示（暖橙色加粗）

============================= 以上规范于 2026-07-05 整理 =============================

============================= 标题生成规范（必读） =============================

【信达雅要求】
  标题（name）不应机械截取【姿态动作】第一句话。必须使用场景+服饰+风格的三段
  组合格式，如"热带海边·麻花辫与微风"、"古风庭院·薄纱长裙·韩系冷调"。
  每次新入库后，建议用 --llm-name 模式让LLM分析碎片生成标题。

【截断防护】
  标题总长度不得超过 30 字，每段长度应控制在 8 字以内，防止 extract_kw 切断
  中文词造成"渐变的交"、"电影级质"这类看不懂的乱码尾巴。
  建议：场景段 ≤6 字，服饰段 ≤8 字，画风段 ≤4 字。

【LLM 智能命名流程】
  1. python batch_insert_prompts.py --file prompts.txt --llm-name
     → 输出每条新提示词的碎片信息（场景、服饰、画风等）
  2. 将输出复制给任意LLM（Claude/ChatGPT/通义千问），附上提示：
     "为每条提示词生成一个信达雅的中文标题，15字以内，有画面感"
  3. LLM 返回 JSON 格式：{"0":"标题1","1":"标题2",...}
  4. python batch_insert_prompts.py --file prompts.txt --import-names llm_names.json
     导入LLM生成的标题并执行入库

【⚠️ 已知坑】
  - 规则生成（extract_kw）会把长句截断，生成"渐变的交"、"电影级质"等乱码尾缀
  - 必须用 LLM 精修或手动审核所有新标题，确保无截断
  - 早期版本（2026-07-05之前）入库的提示词没有插入 template_fragments 表，
    需要手动补全碎片记录才能使用 LLM 命名功能

============================= 标题规范于 2026-07-05 整理 =============================
"""

import argparse, re, sqlite3, sys, json
from datetime import datetime
sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = r'd:\Entertainment\ComfyUI-aki-v2\ComfyUI-aki-v3\workflows\文档\提示词收藏.db'
STYLE_PREFIXES = ["Moody Photography", "Moody Distillation photography style",
                  "Moody Distillation", "Huihui(辉辉)", "Dori"]
FRAGMENT_TYPES = ["姿态动作", "拍摄视角", "人物面部", "人物身材", "人物服饰", "场景环境", "光影色调", "画风技术"]
STYLE_REPLACEMENTS = [
    (r'Keep the presentation in a romantic intimate adult direction\.', '保持浪漫亲密的成人风格。'),
    (r'Keep the presentation in a suggestive adult direction\.', '保持暗示性成人风格。'),
    (r'Apply a visual treatment with natural visual continuity, controlled natural lighting, clean readable light, balanced color, clean readable composition, and subtle natural texture\.', '应用自然视觉连续性、可控自然光、干净可读光线、均衡色彩、干净构图和微妙自然纹理。'),
    (r'Use (\d+mm) lens and (.*?) for visual framing\.?', r'使用\1镜头和\2进行构图。'),
]

TAG_KEYWORDS = {
    '少女', '女孩', '女生', '女子', '女性', '大学生', '网红', '汉服', '古装', '古风',
    '衬衫', 'T恤', '针织衫', '毛衣', '外套', '大衣', '裙子', '短裙', '百褶裙', '连衣裙',
    '牛仔裤', '短裤', '热裤', '打底裤', '袜子', '中筒袜', '运动鞋', '高跟鞋',
    '乐福鞋', '玛丽珍鞋', '雪地靴', '轮滑鞋', '靴子', '小白鞋', '帆布鞋',
    '校园', '教学楼', '图书馆', '教室', '餐厅', '吧台', '咖啡厅', '便利店', '车站',
    '候车厅', '水族馆', '洗车房', '卧室', '床', '沙发', '书房', '办公室', '街头',
    '夜景', '雨天', '冬日', '夏日', '森林', '丛林', '海边', '河边', '花火大会',
    '油纸伞', '灯笼', '行李箱', '书本', '笔记本', '咖啡', '水杯', '包', '眼镜', '围巾',
    '水手服', '西装', '制服', '比基尼', '泳装', '吊带', '抹胸', '露脐', '蕾丝',
    '竹林', '武侠', '弟子服', '门派', '剑', '扇子', '运动',
}
ENGLISH_TAG_PATTERNS = re.compile(
    r'\b(\d+mm|f/\d+(?:\.\d+)?|Moody Photography|ultra realistic|high detail|cinematic lighting)\b', re.IGNORECASE)


# ========== 碎片解析 ==========

def parse_fragments(text):
    result = {}
    for m in re.finditer(r'【([^】]+)】\s*(.*?)(?=\n【|$)', text, re.DOTALL):
        result[m.group(1).strip()] = m.group(2).strip()
    if not result:
        result = auto_split_fragments(text)
    return result


def auto_split_fragments(text):
    paras = [p.strip() for p in re.split(r'\n\s*\n+', text) if p.strip()]
    if len(paras) < 2:
        return {}

    def guess_type(para):
        app_kw = ["肤色", "脸型", "皮肤", "眼睛", "鼻子", "嘴唇", "发型", "妆容", "身材"]
        cloth_kw = ["穿", "着", "戴", "披", "背", "围"]
        pose_kw = ["站在", "坐在", "躺在", "蹲在", "构图", "镜头", "视角", "拍摄", "看向"]
        scene_kw = ["场景", "背景", "前景", "光线", "色调", "灯光", "曝光", "白平衡"]
        score = {"appearance": 0, "pose": 0, "scene": 0}
        for kw in app_kw + cloth_kw:
            if kw in para: score["appearance"] += 1
        for kw in pose_kw:
            if kw in para: score["pose"] += 1
        for kw in scene_kw:
            if kw in para: score["scene"] += 1
        return max(score, key=score.get) if any(score.values()) else "unknown"

    types = [guess_type(p) for p in paras]
    frags, app_parts, cloth_parts = {}, [], []

    for para, ptype in zip(paras, types):
        if ptype == "appearance":
            cm = re.search(r"[。，;；](穿|披|背|围|戴).*", para)
            if cm:
                app_parts.append(para[:cm.start()].strip())
                cloth_parts.append(para[cm.start():].strip("。，；;"))
            else:
                app_parts.append(para)
        elif ptype == "pose":
            frags["姿态动作"] = para
        elif ptype == "scene":
            frags["场景背景"] = para
        else:
            app_parts.append(para)

    if app_parts:
        frags["人物外貌"] = "\n".join(app_parts).strip()
    if cloth_parts:
        frags["服装配饰"] = "\n".join(cloth_parts).strip()
    return frags if sum(1 for t in FRAGMENT_TYPES if frags.get(t)) >= 2 else {}


def reassemble(frags):
    return "\n".join(f'【{k}】{frags[k]}' for k in FRAGMENT_TYPES if frags.get(k))


def clean_fragments(frags):
    modified = False
    app, tech, pose = frags.get("人物外貌", ""), frags.get("风格技术", ""), frags.get("姿态动作", "")
    stripped, extracted = app, []
    for prefix in STYLE_PREFIXES:
        if stripped.startswith(prefix):
            m = re.match(r'^' + re.escape(prefix) + r'[，,]\s*', stripped)
            if m:
                extracted.append(m.group(0).strip().rstrip("，,"))
                stripped = stripped[m.end():]
    if extracted:
        add = "，".join(extracted)
        tech = (tech.rstrip("。，") + "，" + add) if tech else add
        frags["人物外貌"], frags["风格技术"] = stripped, tech
        modified = True

    for ft in FRAGMENT_TYPES:
        val = frags.get(ft, "")
        m = re.match(r'^([A-Za-z0-9_ ,()\-\.&/\']+?)\s*[，,]\s*(.*)', val)
        if m and m.group(1).strip() and any('\u4e00' <= c <= '\u9fff' for c in m.group(2)):
            # ⚠️ 【拍摄视角】中的英文构图指令必须留在最前面（权重最高），
            #    移到末尾会导致构图失控（如全身上下不对称、脚被裁剪）
            if ft == "拍摄视角":
                continue
            frags[ft] = m.group(2).strip() + "，" + m.group(1).strip()
            modified = True

    if pose:
        m = re.match(r'^(\([^)]+\))\s*[，,]\s*(.*)', pose)
        if m:
            frags["姿态动作"] = m.group(2).strip() + "，" + m.group(1).strip()
            modified = True
    return modified


def split_blocks(text):
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    return [b.strip() for b in re.split(r'\n\s*\n\s*\n+', text.strip()) if b.strip()]


def parse_metadata(block):
    p = (r'Steps:\s*(\d+),\s*CFG scale:\s*([\d.]+),\s*Sampler:\s*([^,]+?),\s*'
         r'Seed:\s*(\d+),\s*Model:\s*([^,]+?),\s*width:\s*(\d+),\s*height:\s*(\d+)')
    m = re.search(p, block, re.IGNORECASE)
    if not m:
        return (None, block)
    meta = {
        'steps': int(m.group(1)), 'cfg_scale': float(m.group(2)), 'sampler': m.group(3).strip(),
        'seed': int(m.group(4)), 'model': m.group(5).strip(), 'width': int(m.group(6)), 'height': int(m.group(7)),
        # 双程采样 + LoRA 可选字段
        'scheduler': None, 'steps_2': None, 'cfg_scale_2': None,
        'sampler_2': None, 'scheduler_2': None, 'lora_name': None, 'lora_weight': None,
    }
    rest = block[m.end():]
    # 解析可选字段
    opt = {
        'Scheduler': 'scheduler', 'Steps 2': 'steps_2', 'CFG scale 2': 'cfg_scale_2',
        'Sampler 2': 'sampler_2', 'Scheduler 2': 'scheduler_2',
    }
    for key, field in opt.items():
        em = re.search(key + r':\s*([^,\n]+)', rest)
        if em:
            val = em.group(1).strip()
            if field in ('steps_2',):
                meta[field] = int(val)
            elif field in ('cfg_scale_2',):
                meta[field] = float(val)
            else:
                meta[field] = val
    # LoRA: LoRA: filename@weight
    lm = re.search(r'LoRA:\s*([^@\n]+?)(?:@([\d.]+))?', rest)
    if lm:
        meta['lora_name'] = lm.group(1).strip()
        meta['lora_weight'] = float(lm.group(2)) if lm.group(2) else None
    return (meta, block[:m.start()].strip())


def parse_negative_prompt(body):
    m = re.search(r'Negative prompt:\s*(.*?)(?:\n\s*\n|\n(?=Steps:)|$)', body, re.IGNORECASE | re.DOTALL)
    return (body[:m.start()].strip(), m.group(1).strip()) if m else (body, '')


def _resolve_name(name_result, idx, llm_name_map, args):
    """处理名称：LLM 模式输出碎片信息，导入模式读取映射，否则返回规则名称"""
    if isinstance(name_result, dict) and '_llm_input' in name_result:
        # LLM 模式：记录碎片信息供后续生成
        llm_name_map.setdefault(idx, name_result['_llm_input'])
        return f'__LLM_NEED_NAME_{idx}'

    if idx in llm_name_map and not isinstance(llm_name_map[idx], dict):
        return llm_name_map[idx][:30]

    return name_result


def generate_name(frags, body, idx, args=None):
    """生成信达雅标题

    默认使用规则提取（场景·服饰·画风三段式）。
    传入 --llm-name 时，输出碎片信息供外部 LLM 智能生成标题。
    """

    # ===== LLM 模式：输出碎片信息，由 AI 生成标题 =====
    if args and getattr(args, 'llm_name', False):
        scene = frags.get("场景环境", "")
        cloth = frags.get("人物服饰", "")
        tech = frags.get("画风技术", "")
        face = frags.get("人物面部", "")
        pose = frags.get("姿态动作", "")
        light = frags.get("光影色调", "")
        return {
            '_llm_input': {
                '场景环境': scene and scene[:60],
                '人物服饰': cloth and cloth[:60],
                '画风技术': tech and tech[:60],
                '人物面部': face and face[:40],
                '姿态动作': pose and pose[:40],
                '光影色调': light and light[:40],
            }
        }

    # ===== 规则模式：场景·服饰·画风三段组合 =====
    scene = frags.get("场景环境", "")
    cloth = frags.get("人物服饰", "")
    tech = frags.get("画风技术", "")
    pose = frags.get("姿态动作", "")
    face = frags.get("人物面部", "")

    def get_first_kw(text, max_len=12):
        if not text: return ''
        text = re.sub(r'^[，,。、；\s]+', '', text)
        first = text.split("，")[0].split(",")[0].strip()
        generic = {"一位", "一名", "一个", "亚洲"}
        for g in generic:
            if first.startswith(g):
                rest = first[len(g):]
                first = rest[:1] + rest[1:] if rest else ''
        return first[:max_len].strip("。，、； ")

    scene_kw = get_first_kw(scene, 10)
    cloth_kw = get_first_kw(cloth, 12)
    tech_kw = get_first_kw(tech, 6)

    candidates = [s for s in [scene_kw, cloth_kw, tech_kw] if s]

    if len(candidates) >= 2:
        name = "·".join(candidates)
    elif candidates:
        name = candidates[0]
    else:
        first = re.sub(
            r'^(一位|一名|一个|现实感|超写实|电影感|日式|韩风|Moody Photography,)',
            '', body.split('\n')[0], re.IGNORECASE
        ).strip()
        name = first[:24].strip("。，、； ") or f'未命名-{idx+1}'
    return name[:30].strip("。，、； ")


def generate_tags(frags, prompt_text, model, width, height):
    tags, full = [], reassemble(frags) or prompt_text
    for kw in TAG_KEYWORDS:
        if kw in full: tags.append(kw)
    tags.extend(ENGLISH_TAG_PATTERNS.findall(full))
    if model: tags.append(model.split('\\')[-1].split('/')[-1])
    if width and height:
        tags.append(f'{width}x{height}')
    seen = set()
    return ','.join(t for t in tags if not (t.lower() in seen or seen.add(t.lower())))[:100]


def validate_purity(frags):
    warns = []
    for ft in FRAGMENT_TYPES:
        val = frags.get(ft, "")
        if not val: continue
        if ft == "人物外貌":
            for p in STYLE_PREFIXES:
                if p in val: warns.append(f'【{ft}】包含风格名「{p}」')
        if ft == "姿态动作":
            for kw in ["穿着", "上衣", "裤子", "裙子"]:
                if kw in val: warns.append(f'【{ft}】可能混入服装描述（含「{kw}」）')
    return warns


def insert_records(records, dry_run=False):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if dry_run:
        print('=== 预览模式 ===')
        for i, r in enumerate(records, 1):
            print(f'\n--- 第 {i} 条 ---\nname: {r["name"]}\n碎片:')
            for ft, content in r.get('fragments', {}).items():
                print(f'  【{ft}】{content[:60]}...')
            print(f'model: {r["model"]} lora: {r.get("lora_name","")} cfg: {r["cfg_scale"]} w: {r["width"]} h: {r["height"]}')
            print(f'tags: {r["tags"]}')
        return
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        inserted, skipped = 0, 0
        for r in records:
            # 去重：以 prompt 文本为唯一标识
            cur.execute('SELECT id FROM prompts WHERE prompt = ?', (r['prompt'],))
            if cur.fetchone():
                skipped += 1
                continue
            # 1. 插入 prompts
            cur.execute(
                'INSERT INTO prompts (name, prompt, negative_prompt, steps, cfg_scale, sampler, seed, model, width, height, tags, note, updated_at, scheduler, steps_2, cfg_scale_2, sampler_2, scheduler_2, lora_name, lora_weight) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (r['name'], r['prompt'], r['negative_prompt'], r['steps'], r['cfg_scale'],
                 r['sampler'], r['seed'], r['model'], r['width'], r['height'],
                 r['tags'], '手动收藏', now,
                 r.get('scheduler'), r.get('steps_2'), r.get('cfg_scale_2'),
                 r.get('sampler_2'), r.get('scheduler_2'), r.get('lora_name'), r.get('lora_weight')))
            prompt_id = cur.lastrowid
            inserted += 1

            # 2. 插入 templates
            cur.execute(
                'INSERT INTO templates (name, category_id, created_at, updated_at) VALUES (?,?,?,?)',
                (r['name'], None, now, now))
            template_id = cur.lastrowid

            # 3. 插入 template_fragments
            frags = r.get('fragments', {})
            for sort_order, ft in enumerate(FRAGMENT_TYPES):
                content = frags.get(ft, '')
                if not content:
                    continue
                cur.execute(
                    'INSERT INTO template_fragments (template_id, prompt_id, fragment_type, cached_content, sort_order) VALUES (?,?,?,?,?)',
                    (template_id, prompt_id, ft, content, sort_order))

        conn.commit()
        print(f'已插入 {inserted} 组碎片，跳过 {skipped} 条重复')
        for r in records:
            print(f'  {r["name"]} ({len([v for v in r.get("fragments",{}).values() if v])}个碎片)')
        for r in records:
            print(f'  {r["name"]} ({len([v for v in r.get("fragments",{}).values() if v])}个碎片)')


def main():
    p = argparse.ArgumentParser(description='批量插入提示词 V2')
    p.add_argument('--file', required=True)
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--strict', action='store_true', help='严格：碎片不纯净则跳过')
    p.add_argument('--llm-name', action='store_true',
                   help='LLM模式：输出每个提示词的碎片信息，复制给AI生成标题后再用 --import-names 导入')
    p.add_argument('--import-names', type=str, metavar='JSONFILE',
                   help='导入LLM生成的信达雅标题（JSON文件，格式: {"序号": "标题名"}）')
    args = p.parse_args()

    with open(args.file, 'r', encoding='utf-8') as f:
        text = f.read()

    # ---- 导入LLM生成的标题 ----
    llm_name_map = {}
    if args.import_names:
        with open(args.import_names, 'r', encoding='utf-8') as f:
            llm_name_map = json.load(f)
        print(f'已加载 {len(llm_name_map)} 条 LLM 标题')

    records = []
    for idx, block in enumerate(split_blocks(text)):
        meta, body = parse_metadata(block)
        body = block if meta is None else body  # 无元数据时整块当作 body

        # 无元数据时使用空值，不跳过
        if meta is None:
            meta = {
                'steps': None, 'cfg_scale': None, 'sampler': None,
                'seed': None, 'model': None, 'width': None, 'height': None,
                'scheduler': None, 'steps_2': None, 'cfg_scale_2': None,
                'sampler_2': None, 'scheduler_2': None, 'lora_name': None, 'lora_weight': None,
            }

        body, neg = parse_negative_prompt(body)
        for pat, repl in STYLE_REPLACEMENTS:
            body = re.sub(pat, repl, body, flags=re.IGNORECASE)
        frags = parse_fragments(body)
        has_frags = any(frags.get(t) for t in FRAGMENT_TYPES)

        if has_frags:
            if clean_fragments(frags):
                print(f'  [CLEAN] 第 {idx+1} 块')
            for w in validate_purity(frags):
                print(f'  [WARN] {w}')
            if validate_purity(frags) and args.strict:
                print(f'  [SKIP] 跳过')
                continue
            # prompt存带标题的展示格式，前端复制用 JS 去标记：copyText.replace(/【[^】]+】\s*/g, '')
            display_lines = [f'【{k}】{frags[k]}' for k in FRAGMENT_TYPES if frags.get(k)]
            prompt_text = '\n\n'.join(display_lines)
        else:
            prompt_text = body

        records.append({
            'name': _resolve_name(generate_name(frags if has_frags else {}, body, idx, args),
                                  idx, llm_name_map, args),
            'prompt': prompt_text, 'negative_prompt': neg,
            'steps': meta['steps'], 'cfg_scale': meta['cfg_scale'],
            'sampler': meta['sampler'], 'seed': meta['seed'],
            'model': meta['model'], 'width': meta['width'], 'height': meta['height'],
            'tags': generate_tags(frags if has_frags else {}, prompt_text, meta['model'], meta['width'], meta['height']),
            'scheduler': meta.get('scheduler'), 'steps_2': meta.get('steps_2'),
            'cfg_scale_2': meta.get('cfg_scale_2'), 'sampler_2': meta.get('sampler_2'),
            'scheduler_2': meta.get('scheduler_2'), 'lora_name': meta.get('lora_name'),
            'lora_weight': meta.get('lora_weight'),
            'fragments': frags if has_frags else {},
        })

    if not records:
        print('无有效数据')
        return

    # ---- LLM 模式：输出碎片信息供 AI 生成标题 ----
    if args.llm_name:
        llm_inputs = {r['name']: r['fragments'] for r in records
                      if r['name'].startswith('__LLM_NEED_NAME_')}
        if llm_inputs:
            print(f'\n{"="*60}')
            print('  LLM 命名模式 — 请将以下信息复制给 AI 生成标题')
            print(f'{"="*60}')
            print('''
请为以下每条提示词生成一个信达雅的中文标题（15字以内，有画面感，像写真集命名）：

格式要求：
- 用场景+风格+人物的精华组合
- 不要机械截取关键词，要用自然中文
- 示例： "热带海边·麻花辫与微风"、"纯白极简·轻熟侧影"
''')
            for name_key, frags in llm_inputs.items():
                idx = name_key.replace('__LLM_NEED_NAME_', '')
                print(f'--- 第{idx}条 ---')
                for ft in FRAGMENT_TYPES:
                    val = frags.get(ft, '')
                    if val:
                        print(f'  {ft}: {val[:80]}')
                print()
            print('完成后返回 JSON 格式：{"0":"标题1","1":"标题2",...}')
            print('保存为文件后用 --import-names 导入\n')
        return

    insert_records(records, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
