#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量插入提示词 V2 — 支持【】分段、自动拆分、清洗检查。

用法：
    python batch_insert_prompts.py --file prompts.txt
    python batch_insert_prompts.py --file prompts.txt --dry-run
    python batch_insert_prompts.py --file prompts.txt --strict

输入格式（以空行分隔）：
    方式1: 【人物外貌】...【姿态动作】... + 元数据行
    方式2: 三段式(人+衣 / 姿态 / 场景) + 元数据行 → 自动拆分
    方式3: 纯文本 + 元数据行
"""

import argparse, re, sqlite3, sys
from datetime import datetime
sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = r'd:\Entertainment\ComfyUI-aki-v2\ComfyUI-aki-v3\workflows\文档\提示词收藏.db'
STYLE_PREFIXES = ["Moody Photography", "Moody Distillation photography style",
                  "Moody Distillation", "Huihui(辉辉)", "Dori"]
FRAGMENT_TYPES = ["人物面部", "人物身材", "人物服饰", "姿态动作", "拍摄视角", "场景环境", "光影色调", "画风技术"]
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
    return ({
        'steps': int(m.group(1)), 'cfg_scale': float(m.group(2)), 'sampler': m.group(3).strip(),
        'seed': int(m.group(4)), 'model': m.group(5).strip(), 'width': int(m.group(6)), 'height': int(m.group(7)),
    }, block[:m.start()].strip()) if m else (None, block)


def parse_negative_prompt(body):
    m = re.search(r'Negative prompt:\s*(.*?)(?:\n\s*\n|\n(?=Steps:)|$)', body, re.IGNORECASE | re.DOTALL)
    return (body[:m.start()].strip(), m.group(1).strip()) if m else (body, '')


def generate_name(frags, body, idx):
    for ft in ["姿态动作", "人物外貌"]:
        val = frags.get(ft, "")
        first = val.split("，")[0].split(",")[0].strip() if val else ""
        if len(first) >= 4:
            return first[:24].strip("。，、； ")
    first = re.sub(r'^(一位|一名|一个|现实感|超写实|电影感|日式|韩风|Moody Photography,)', '', body.split('\n')[0], re.IGNORECASE).strip()
    return first[:20].strip("。，、； ") or f'未命名-{idx+1}'


def generate_tags(frags, prompt_text, model, width, height):
    tags, full = [], reassemble(frags) or prompt_text
    for kw in TAG_KEYWORDS:
        if kw in full: tags.append(kw)
    tags.extend(ENGLISH_TAG_PATTERNS.findall(full))
    if model: tags.append(model.split('\\')[-1].split('/')[-1])
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
            print(f'\n--- 第 {i} 条 ---\nname: {r["name"]}\nprompt: {r["prompt"][:120]}...\ntags: {r["tags"]}')
        return
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        for r in records:
            cur.execute(
                'INSERT INTO prompts (name, prompt, negative_prompt, steps, cfg_scale, sampler, seed, model, width, height, tags, note, updated_at) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (r['name'], r['prompt'], r['negative_prompt'], r['steps'], r['cfg_scale'],
                 r['sampler'], r['seed'], r['model'], r['width'], r['height'],
                 r['tags'], '手动收藏', now))
        conn.commit()
        print(f'已插入 {len(records)} 条记录')
        cur.execute('SELECT id, name FROM prompts ORDER BY id DESC LIMIT ?', (len(records),))
        for row in cur.fetchall():
            print(f'  #{row[0]} {row[1]}')


def main():
    p = argparse.ArgumentParser(description='批量插入提示词 V2')
    p.add_argument('--file', required=True)
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--strict', action='store_true', help='严格：碎片不纯净则跳过')
    args = p.parse_args()

    with open(args.file, 'r', encoding='utf-8') as f:
        text = f.read()

    records = []
    for idx, block in enumerate(split_blocks(text)):
        meta, body = parse_metadata(block)
        if not meta:
            print(f'[SKIP] 第 {idx+1} 块：无元数据')
            continue
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
            prompt_text = reassemble(frags)
        else:
            prompt_text = body

        records.append({
            'name': generate_name(frags if has_frags else {}, body, idx),
            'prompt': prompt_text, 'negative_prompt': neg,
            'steps': meta['steps'], 'cfg_scale': meta['cfg_scale'],
            'sampler': meta['sampler'], 'seed': meta['seed'],
            'model': meta['model'], 'width': meta['width'], 'height': meta['height'],
            'tags': generate_tags(frags if has_frags else {}, prompt_text, meta['model'], meta['width'], meta['height']),
        })

    if not records:
        print('无有效数据')
        return
    insert_records(records, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
