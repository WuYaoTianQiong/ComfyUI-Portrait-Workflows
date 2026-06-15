import urllib.request, json, time, sys

MAX_RETRY = 90  # 最多等3分钟
for i in range(MAX_RETRY):
    try:
        req = urllib.request.Request('http://127.0.0.1:8188/object_info')
        resp = urllib.request.urlopen(req, timeout=3)
        info = json.loads(resp.read())
        # 检查新节点是否已加载
        nodes_ok = all(k in info for k in [
            'SAMModelLoader (segment anything)',
            'GroundingDinoModelLoader (segment anything)',
            'GroundingDinoSAMSegment (segment anything)',
            'Power Primitive (rgthree)'
        ])
        if nodes_ok:
            print('ComfyUI 就绪，所有新节点已加载')
            sys.exit(0)
        else:
            missing = [k for k in [
                'SAMModelLoader (segment anything)',
                'GroundingDinoModelLoader (segment anything)',
                'GroundingDinoSAMSegment (segment anything)',
                'Power Primitive (rgthree)'
            ] if k not in info]
            print(f'等待节点: {missing}')
    except Exception as e:
        pass
    print('.', end='', flush=True)
    time.sleep(2)

print('\n超时，ComfyUI 未就绪')
sys.exit(1)
