import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import json, urllib.request, urllib.error, uuid

API_URL = 'http://127.0.0.1:8188'
WORKFLOW_PATH = r'd:\Entertainment\ComfyUI-aki-v2\workflows\MoodyZIT_V7_Inpaint_图生图_自动遮罩.json'

# 1. 获取 Power Primitive 节点的定义
req = urllib.request.Request(f'{API_URL}/object_info')
info = json.loads(urllib.request.urlopen(req, timeout=5).read())

pp = info.get('Power Primitive (rgthree)')
if pp:
    print('=== Power Primitive (rgthree) ===')
    print(f'INPUT_TYPES: {json.dumps(pp.get("input", {}), ensure_ascii=False, indent=2)}')
    print(f'Required: {json.dumps(pp.get("input", {}).get("required", {}), ensure_ascii=False, indent=2)}')
    print(f'Optional: {json.dumps(pp.get("input", {}).get("optional", {}), ensure_ascii=False, indent=2)}')
else:
    print('Power Primitive (rgthree) not found')

# 2. 验证工作流格式是否正确
with open(WORKFLOW_PATH, 'r', encoding='utf-8') as f:
    workflow = json.load(f)

# 打印 PowerPrimitive 节点
pp_node = workflow.get('37', {})
print(f'\n=== 节点 37 (Power Primitive) ===')
print(json.dumps(pp_node, ensure_ascii=False, indent=2))

# 检查 GroundingDinoSAMSegment 的 input spec
gd = info.get('GroundingDinoSAMSegment (segment anything)')
if gd:
    print(f'\n=== GroundingDinoSAMSegment ===')
    print(f'Required: {json.dumps(gd.get("input", {}).get("required", {}), ensure_ascii=False, indent=2)}')
else:
    print('\nGroundingDinoSAMSegment not found')
