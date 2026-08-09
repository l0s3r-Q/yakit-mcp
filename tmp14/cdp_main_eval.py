# -*- coding: utf-8 -*-
"""验证方案2: CDP 连 Electron 主进程(browser target) → 执行 JS 发 fetch-send-to-tab"""
import subprocess, sys, time, json, urllib.request
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import websocket

CDP = 9333
flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
subprocess.Popen([r"D:\My_apps\Yakit\Yakit.exe", f"--remote-debugging-port={CDP}", "--remote-allow-origins=*"],
                 creationflags=flags, close_fds=True)
print('[0] GUI 启动 (CDP)')
for i in range(40):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json', timeout=2) as req:
            pages = json.loads(req.read())
        if pages:
            print(f'[1] CDP 就绪 [{i+1}s], {len(pages)} targets')
            break
    except Exception:
        pass
    time.sleep(1)

# 列出所有 target（找 browser/主进程）
for p in pages:
    print(f'  type={p.get("type")} title={str(p.get("title"))[:30]} url={str(p.get("url"))[:50]}')

# 连主进程 target（type=node 或 browser）
main_t = [p for p in pages if p.get('type') in ('node', 'browser')]
page_t = [p for p in pages if p.get('type') == 'page' and 'main/index.html' in p.get('url', '')]

print('\n主进程 target:', [p.get('type') for p in main_t])
print('页面 target:', len(page_t))

if main_t:
    ws = websocket.create_connection(main_t[0]['webSocketDebuggerUrl'], timeout=15)
    mid = [0]
    def rpc(method, params=None):
        mid[0] += 1
        ws.send(json.dumps({'id': mid[0], 'method': method, 'params': params or {}}))
        while True:
            resp = json.loads(ws.recv())
            if resp.get('id') == mid[0]:
                return resp
    def ev(expr):
        r = rpc('Runtime.evaluate', {'expression': expr, 'returnByValue': True})
        return r.get('result', {}).get('result', {}).get('value')
    print('\n[2] 主进程 eval:')
    print('  typeof require:', ev('typeof require'))
    print('  electron:', ev('typeof require === "function" ? Object.keys(require("electron")).slice(0,10) : "no require"'))
else:
    print('无主进程 target')
ws.close() if 'ws' in dir() else None
print('=== 完成 ===')