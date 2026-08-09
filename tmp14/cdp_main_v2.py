# -*- coding: utf-8 -*-
import sys, json, urllib.request, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import websocket
CDP = 9333
try:
    with urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json/version', timeout=2) as req:
        ver = json.loads(req.read())
    print('version:', json.dumps(ver, ensure_ascii=False)[:300])
except Exception as e:
    print('version 不可用:', repr(e)[:80]); sys.exit(1)

ws_url = ver.get('webSocketDebuggerUrl')
print('\nbrowser ws:', ws_url)
if not ws_url:
    print('无 browser ws'); sys.exit(1)
ws = websocket.create_connection(ws_url, timeout=10)
mid = [0]
def rpc(method, params=None):
    mid[0] += 1
    ws.send(json.dumps({'id': mid[0], 'method': method, 'params': params or {}}))
    while True:
        resp = json.loads(ws.recv())
        if resp.get('id') == mid[0]:
            return resp

# Target.getTargets 看是否有 node/main target
r = rpc('Target.getTargets')
if 'result' in r:
    for t in r['result'].get('targetInfos', [])[:10]:
        print(f'  {t.get("type")} | {t.get("title","")[:30]} | {t.get("url","")[:50]}')
        if t.get('type') in ('node', 'other') or 'main' in str(t.get('url','')).lower():
            print('    ws:', t.get('webSocketDebuggerUrl'))
ws.close()
