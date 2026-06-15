import json, urllib.request

req = urllib.request.Request('http://127.0.0.1:8188/object_info')
resp = urllib.request.urlopen(req, timeout=5)
info = json.loads(resp.read())

# 检查需要的新节点
for name in ['SAMModelLoader', 'GroundingDinoModelLoader', 'GroundingDinoSAMSegment', 'RgthreePowerPrimitive']:
    found = name in info
    print(f'{name}: {"OK" if found else "MISSING"}')

# 搜索 SAM/GroundingDino 相关节点
for key in sorted(info.keys()):
    if 'SAM' in key.upper() or 'Grounding' in key:
        print(f'  Found: {key}')
