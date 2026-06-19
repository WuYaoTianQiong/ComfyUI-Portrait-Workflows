#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量将 Stable Diffusion / ComfyUI 提示词文本解析并插入到 SQLite 数据库。

使用方式：
    python batch_insert_prompts.py --file prompts.txt
    python batch_insert_prompts.py --file prompts.txt --dry-run  # 仅预览，不写入

输入文本格式说明：
1. 多条提示词之间用空行（一个或多个换行）分隔。
2. 每条提示词包含：
   - 正文（可多行）
   - 可选 Negative prompt: ... 行
   - 必需的元数据行：Steps: ..., CFG scale: ..., Sampler: ..., Seed: ..., Model: ..., width: ..., height: ...
3. 英文风格说明（如 "Keep the presentation..." / "Use ... lens"）会被自动翻译为中文。
4. 程序会自动生成 name 和 tags；如不满意可在插入后通过前端页面修改。

输出：
    插入成功后会打印每条记录的 id、name、model、seed。
"""

import argparse
import re
import sqlite3
from datetime import datetime
DB_PATH = r'd:\Entertainment\ComfyUI-aki-v2\ComfyUI-aki-v3\workflows\文档\提示词收藏.db'

# 英文风格说明翻译规则：按顺序替换
STYLE_REPLACEMENTS = [
    (r'Keep the presentation in a romantic intimate adult direction\.', '保持浪漫亲密的成人风格。'),
    (r'Keep the presentation in a suggestive adult direction\.', '保持暗示性成人风格。'),
    (r'Apply a visual treatment with natural visual continuity, controlled natural lighting, clean readable light, balanced color, clean readable composition, and subtle natural texture\.', '应用具有自然视觉连续性、可控自然光、干净可读的光线、均衡色彩、干净可读的构图和微妙自然纹理的视觉处理。'),
    (r'Use (\d+mm) lens and (.*?) for visual framing\.', r'使用\1镜头和\2进行构图。'),
    (r'Use (\d+mm) lens and (.*?) for visual framing', r'使用\1镜头和\2进行构图'),
]

# 用于生成 tags 的中文关键词表，按常见主题分类；匹配不到时会再辅以英文术语和模型名
TAG_KEYWORDS = {
    '少女', '女孩', '女生', '女子', '女性', '大学生', '网红', '汉服', '古装',
    '衬衫', 'T恤', '针织衫', '毛衣', '外套', '大衣', '裙子', '短裙', '百褶裙', '连衣裙',
    '牛仔裤', '短裤', '热裤', '打底裤', '袜子', '中筒袜', '长袜', '丝袜', '运动鞋', '高跟鞋',
    '乐福鞋', '玛丽珍鞋', '雪地靴', '轮滑鞋', '靴子', '短靴',
    '校园', '教学楼', '图书馆', '教室', '餐厅', '吧台', '咖啡厅', '便利店', '车站',
    '候车厅', '水族馆', '洗车房', '卧室', '床', '沙发', '书房', '办公室', '街头',
    '夜景', '雨天', '冬日', '夏日', '森林', '丛林', '海边', '河边', '花火大会',
    '油纸伞', '灯笼', '行李箱', '书本', '笔记本', '咖啡', '水杯', '包', '眼镜', '围巾',
    '水手服', '西装', '制服', '比基尼', '泳装', '吊带', '抹胸', '露脐', '蕾丝',
    '自拍亭', '拍照亭', '吊床', '水母缸', '灯笼', '烟花', '瀑布', '樱花',
}

# 英文风格/技术术语，直接作为标签保留
ENGLISH_TAG_PATTERNS = re.compile(
    r'\b(\d+mm|f/\d+(?:\.\d+)?|1/\d+s(?:hutter)?|Moody Photography|ultra realistic|high detail|cinematic lighting|portrait photography|vertical composition)\b',
    re.IGNORECASE
)


def translate_style_english(text):
    """将提示词末尾的英文风格说明翻译为中文。"""
    for pattern, repl in STYLE_REPLACEMENTS:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    return text


def split_blocks(text):
    """
    按提示词块分割输入文本。
    块之间由至少两个换行分隔。
    """
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    blocks = re.split(r'\n\s*\n\s*\n+', text.strip())
    return [b.strip() for b in blocks if b.strip()]


def parse_metadata(block):
    """从块文本中提取元数据，返回字典和去除元数据后的正文。"""
    pattern = (
        r'Steps:\s*(\d+),\s*'
        r'CFG scale:\s*([\d.]+),\s*'
        r'Sampler:\s*([^,]+?),\s*'
        r'Seed:\s*(\d+),\s*'
        r'Model:\s*([^,]+?),\s*'
        r'width:\s*(\d+),\s*'
        r'height:\s*(\d+)'
    )
    m = re.search(pattern, block, re.IGNORECASE)
    if not m:
        return None, block

    meta = {
        'steps': int(m.group(1)),
        'cfg_scale': float(m.group(2)),
        'sampler': m.group(3).strip(),
        'seed': int(m.group(4)),
        'model': m.group(5).strip(),
        'width': int(m.group(6)),
        'height': int(m.group(7)),
    }
    body = block[:m.start()].strip()
    return meta, body


def parse_negative_prompt(body):
    """提取 Negative prompt，返回 (正文, negative_prompt)。"""
    pattern = r'Negative prompt:\s*(.*?)(?:\n\s*\n|\n(?=Steps:)|$)'
    m = re.search(pattern, body, re.IGNORECASE | re.DOTALL)
    if m:
        negative = m.group(1).strip()
        body_clean = body[:m.start()].strip()
        return body_clean, negative
    return body, ''


def generate_name(prompt_text, index):
    """生成简短标题：取第一行并清理。"""
    first_line = prompt_text.split('\n')[0].strip()
    first_line = re.sub(r'^(一位|一名|一个|现实感|超写实|电影感|日式|韩风|Moody Photography,)', '', first_line, flags=re.IGNORECASE).strip()
    name = first_line[:20].strip('，。、； ')
    if not name:
        name = f'未命名提示词-{index + 1}'
    return name


def generate_tags(prompt_text, model, width, height):
    """基于内置关键词表和英文术语生成 tags。"""
    tags = []

    # 匹配中文关键词
    for kw in TAG_KEYWORDS:
        if kw in prompt_text:
            tags.append(kw)

    # 匹配英文技术/风格术语
    english_terms = ENGLISH_TAG_PATTERNS.findall(prompt_text)
    tags.extend(english_terms)

    # 加入模型短名
    if model:
        m_short = model.split('\\')[-1].split('/')[-1]
        if m_short:
            tags.append(m_short)

    # 加入分辨率
    tags.append(f'{width}x{height}')

    # 去重并保持顺序
    seen = set()
    unique_tags = []
    for t in tags:
        tl = t.lower()
        if tl not in seen:
            seen.add(tl)
            unique_tags.append(t)

    return ','.join(unique_tags[:10])


def insert_records(records, dry_run=False):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if dry_run:
        print('=== 预览模式，未写入数据库 ===')
        for i, r in enumerate(records, 1):
            print(f'\n--- 第 {i} 条 ---')
            print(f'name: {r["name"]}')
            print(f'prompt: {r["prompt"][:80]}...')
            print(f'tags: {r["tags"]}')
            print(f'meta: steps={r["steps"]}, cfg={r["cfg_scale"]}, sampler={r["sampler"]}, seed={r["seed"]}, model={r["model"]}, {r["width"]}x{r["height"]}')
        return

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        for r in records:
            cur.execute(
                '''
                INSERT INTO prompts
                (name, prompt, negative_prompt, steps, cfg_scale, sampler, seed, model, width, height, tags, note, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    r['name'], r['prompt'], r['negative_prompt'], r['steps'], r['cfg_scale'],
                    r['sampler'], r['seed'], r['model'], r['width'], r['height'],
                    r['tags'], r.get('note', '手动收藏'), now,
                ),
            )
        conn.commit()
        print(f'已插入 {len(records)} 条记录')

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute('SELECT id, name, model, seed, created_at FROM prompts ORDER BY id DESC LIMIT ?', (len(records),))
        for row in cur.fetchall():
            print(row)


def main():
    parser = argparse.ArgumentParser(description='批量解析提示词并插入数据库')
    parser.add_argument('--file', required=True, help='包含提示词的文本文件路径')
    parser.add_argument('--dry-run', action='store_true', help='仅预览，不写入数据库')
    args = parser.parse_args()

    with open(args.file, 'r', encoding='utf-8') as f:
        text = f.read()

    blocks = split_blocks(text)
    records = []
    for idx, block in enumerate(blocks):
        meta, body = parse_metadata(block)
        if not meta:
            print(f'警告：第 {idx + 1} 块未找到完整元数据，已跳过')
            continue

        body, negative = parse_negative_prompt(body)

        name = generate_name(body, idx)
        # tags 在翻译风格说明前生成，避免"干净可读"等通用词占据标签
        tags = generate_tags(body, meta['model'], meta['width'], meta['height'])
        body = translate_style_english(body)

        records.append({
            'name': name,
            'prompt': body,
            'negative_prompt': negative,
            'steps': meta['steps'],
            'cfg_scale': meta['cfg_scale'],
            'sampler': meta['sampler'],
            'seed': meta['seed'],
            'model': meta['model'],
            'width': meta['width'],
            'height': meta['height'],
            'tags': tags,
            'note': '手动收藏',
        })

    if not records:
        print('未解析到任何有效提示词，请检查文件格式。')
        return

    insert_records(records, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
