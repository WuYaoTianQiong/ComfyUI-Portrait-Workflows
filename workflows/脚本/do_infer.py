import sys, json, urllib.request, urllib.error
sys.stdout.reconfigure(encoding='utf-8')

with open(r'd:\Entertainment\ComfyUI-aki-v2\workflows\MoodyZIT_V7_Inpaint_图生图_自动遮罩.json', 'r', encoding='utf-8') as f:
    workflow = json.load(f)

# 从 PowerPrimitive 读值，直接写入目标节点（API 模式下 PowerPrimitive 引用不生效）
target = workflow.get('37', {}).get('inputs', {}).get('value', 'hair')
positive = workflow.get('10', {}).get('inputs', {}).get('text', 'white short hair')

workflow['36']['inputs']['prompt'] = target   # GroundingDinoSAMSegment
workflow['12']['inputs']['text'] = target     # CLIPTextEncode(negative)

print(f'遮罩目标: {target}')
print(f'正向提示: {positive}')

data = json.dumps({'prompt': workflow, 'client_id': 'inference-run'}).encode('utf-8')
req = urllib.request.Request('http://127.0.0.1:8188/prompt', data=data, headers={'Content-Type': 'application/json'})
try:
    resp = urllib.request.urlopen(req, timeout=60)
    result = json.loads(resp.read())
    pid = result.get('prompt_id', '')
    print(f'OK prompt_id={pid}')
    if result.get('node_errors'):
        print(f'ERRORS={json.dumps(result["node_errors"])}')
except urllib.error.HTTPError as e:
    body = e.read().decode('utf-8')
    print(f'HTTP_{e.code}: {body}')
except Exception as e:
    print(f'FAIL: {e}')

