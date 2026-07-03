# -*- coding: utf-8 -*-
"""全面分析 111 条提示词"""
import sys, sqlite3, re
sys.stdout.reconfigure(encoding='utf-8')

path = r'd:\Entertainment\ComfyUI-aki-v2\ComfyUI-aki-v3\workflows\文档\提示词收藏.db'
conn = sqlite3.connect(path)
cur = conn.cursor()

rows = list(cur.execute('SELECT id, name, prompt, tags, note FROM prompts ORDER BY id'))

# ================================================================
# 1. 碎片格式分析
# ================================================================
print('=' * 70)
print('1. 碎片格式分析')
print('=' * 70)

all_fragment_types = set()
format_groups = {}  # (碎片数, 碎片类型集合) → [ids]

for r in rows:
    pid, name, prompt = r[0], r[1], r[2] or ''
    frags = re.findall(r'【([^】]+)】', prompt)
    frag_types = set(frags)
    all_fragment_types.update(frag_types)
    
    key = (len(frags), tuple(sorted(frag_types)))
    if key not in format_groups:
        format_groups[key] = []
    format_groups[key].append(pid)

print(f'共发现 {len(all_fragment_types)} 种不同的碎片类型:')
for ft in sorted(all_fragment_types):
    print(f'  【{ft}】')

print(f'\n格式分组 ({len(format_groups)} 种):')
for (count, types), ids in sorted(format_groups.items(), key=lambda x: -x[0][0]):
    sample = cur.execute('SELECT name FROM prompts WHERE id=?', (ids[0],)).fetchone()[0]
    print(f'  [{count}碎片] {len(ids)}条 → 类型: {", ".join(sorted(types))}')
    print(f'    示例: ID={ids[0]} {sample}')
    print(f'    IDs: {ids}')

# ================================================================
# 2. 命名规范分析
# ================================================================
print('\n' + '=' * 70)
print('2. 命名规范分析')
print('=' * 70)

# 命名风格归类
name_styles = {}  # pattern → [ids]
for r in rows:
    pid, name = r[0], r[1] or ''
    if re.match(r'^\d{2}_', name):
        style = '编号前缀 (01_xxx)'
    elif re.match(r'^姿势\d+[:：]', name) or re.match(r'^姿势\d+ ', name):
        style = '姿势编号'
    elif '·' in name:
        style = '地点·风格 (xxx·xxx)'
    elif re.match(r'^[A-Z]', name):
        style = '英文开头'
    else:
        style = '纯中文描述'
    
    if style not in name_styles:
        name_styles[style] = []
    name_styles[style].append(pid)

print('命名风格分布:')
for style, ids in sorted(name_styles.items(), key=lambda x: -len(x[1])):
    print(f'  [{style}] {len(ids)}条: {ids[:5]}{"..." if len(ids)>5 else ""}')

# 重复/相似命名检查
print('\n相似命名（可能重复）:')
name_map = {}
for r in rows:
    pid, name = r[0], (r[1] or '').strip()
    name_map.setdefault(name, []).append(pid)
for name, ids in sorted(name_map.items(), key=lambda x: -len(x[1])):
    if len(ids) > 1:
        print(f'  ✗ 完全相同: {ids} → "{name}"')

# ================================================================
# 3. 内容分析
# ================================================================
print('\n' + '=' * 70)
print('3. 内容分析')
print('=' * 70)

# 提示词长度分布
lengths = [len(r[2] or '') for r in rows]
print(f'提示词长度: 最短={min(lengths)}  最长={max(lengths)}  平均={sum(lengths)//len(lengths)}')
short = [(r[0], r[1], len(r[2] or '')) for r in rows if len(r[2] or '') < 50]
if short:
    print(f'  过短提示词(<50字) {len(short)}条:')
    for pid, name, l in short:
        print(f'    ID={pid} "{name}" ({l}字)')

long_texts = [(r[0], r[1], len(r[2] or '')) for r in rows if len(r[2] or '') > 500]
if long_texts:
    print(f'  超长提示词(>500字) {len(long_texts)}条:')
    for pid, name, l in long_texts:
        print(f'    ID={pid} "{name}" ({l}字)')

# 内容重复检查（相似度）
print('\n内容相似度检查（前20字相同视为疑似重复）:')
from collections import defaultdict
content_prefix = defaultdict(list)
for r in rows:
    p = r[2] or ''
    prefix = p[:20].strip()
    content_prefix[prefix].append((r[0], r[1], p[:60]))
for prefix, items in sorted(content_prefix.items(), key=lambda x: -len(x[1])):
    if len(items) > 1:
        print(f'  前缀 "{prefix}..." 出现 {len(items)} 次:')
        for pid, name, preview in items:
            print(f'    ID={pid} "{name}" → {preview!r}')
        print()

# ================================================================
# 4. 缺少负向提示词
# ================================================================
print('=' * 70)
print('4. 负向提示词分析')
print('=' * 70)

no_neg = [(r[0], r[1]) for r in rows if not (r[3] or '')]  # r[3]=tags, wait need to check position
no_neg = []
for r in rows:
    pid, name = r[0], r[1]
    # r[3] is tags, r[4] is note, need negative_prompt
    np = cur.execute('SELECT negative_prompt FROM prompts WHERE id=?', (pid,)).fetchone()[0] or ''
    if not np:
        no_neg.append((pid, name))

print(f'缺少负向提示词: {len(no_neg)}/{len(rows)} 条')
if len(no_neg) < 20:
    for pid, name in no_neg:
        print(f'  ID={pid} "{name}"')

# ================================================================
# 5. 标签缺失
# ================================================================
print('\n' + '=' * 70)
print('5. 标签分析')
print('=' * 70)

no_tags = [(r[0], r[1]) for r in rows if not (r[3] or '')]
print(f'缺少标签: {len(no_tags)}/{len(rows)} 条')
if no_tags:
    print(f'  前10条: {no_tags[:10]}')

conn.close()
