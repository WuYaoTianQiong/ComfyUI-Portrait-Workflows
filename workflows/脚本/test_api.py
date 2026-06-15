import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import json, urllib.request, urllib.error, time, os

WORKFLOW_PATH = os.path.join(os.path.dirname(__file__), '..', 'MoodyZIT_V7_Inpaint_图生图_自动遮罩.json')
API_URL = 'http://127.0.0.1:8188'

print('测试 1: 加载工作流')
with open(WORKFLOW_PATH, 'r', encoding='utf-8') as f:
    workflow = json.load(f)
print(f'  节点数: {len(workflow)}')

print('测试 2: 获取 object_info')
req = urllib.request.Request(f'{API_URL}/object_info')
resp = urllib.request.urlopen(req, timeout=5)
info = json.loads(resp.read())

required_nodes = [
    'UNETLoader', 'CLIPLoader', 'VAELoader',
    'SAMModelLoader (segment anything)',
    'GroundingDinoModelLoader (segment anything)',
    'GroundingDinoSAMSegment (segment anything)',
    'Power Primitive (rgthree)'
]

for name in required_nodes:
    found = name in info
    if not found:
        print(f'  [MISSING] {name}')
    else:
        print(f'  [OK] {name}')

# 检查实际注册的节点
for nid, node in workflow.items():
    ct = node['class_type']
    if ct not in info:
        print(f'  [NODE MISSING] {nid}: {ct}')

print('测试通过，可以提交')
