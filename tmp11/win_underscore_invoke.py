# -*- coding: utf-8 -*-
"""用 window._.invoke 调引擎（免认证通道）: 查历史 + 重放"""
import subprocess, sys, time, json, urllib.request
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import websocket

CDP = 9333
# GUI 可能还在，检查
try:
    with urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json', timeout=2) as req:
        pages = json.loads(req.read())
    print('[0] GUI 还在')
except Exception:
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen([r"D:\My_apps\Yakit\Yakit.exe", f"--remote-debugging-port={CDP}", "--remote-allow-origins=*"],
                     creationflags=flags, close_fds=True)
    print('[0] GUI 启动')
    for i in range(40):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json', timeout=2) as req:
                pages = json.loads(req.read())
            if any('main/index.html' in p.get('url', '') for p in pages):
                break
        except Exception:
            pass
        time.sleep(1)

def connect():
    with urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json', timeout=3) as req:
        pages = json.loads(req.read())
    main = [p for p in pages if 'main/index.html' in p.get('url', '')][0]
    ws = websocket.create_connection(main['webSocketDebuggerUrl'], timeout=15)
    return ws, [0]

ws, msg_id = connect()
def rpc(method, params=None):
    msg_id[0] += 1
    ws.send(json.dumps({'id': msg_id[0], 'method': method, 'params': params or {}}))
    while True:
        resp = json.loads(ws.recv())
        if resp.get('id') == msg_id[0]:
            return resp

def ev(expr):
    try:
        r = rpc('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True})
        return r.get('result', {}).get('result', {}).get('value')
    except Exception:
        return None

rpc('Runtime.enable')
print('[1] 等页面...')
for i in range(20):
    v = ev('document.body ? document.body.innerText.length : -1')
    if isinstance(v, int) and v > 100:
        break
    time.sleep(2)

# 进项目（如果弹项目管理）
for i in range(15):
    texts = ev("""(() => {
        const all = [...document.querySelectorAll('*')].filter(e => e.children.length === 0);
        return JSON.stringify([...new Set(all.map(e => e.textContent.trim()).filter(t => t && t.length < 25))]);
    })()""") or "[]"
    if 'Web Fuzzer' in texts or 'History' in texts:
        break
    if '[default]' in texts:
        ev("""(() => {
            const all = [...document.querySelectorAll('div, span')];
            const t = all.find(e => e.textContent.trim() === '[default]' && e.children.length === 0);
            if (t) { t.click(); return 'ok'; }
            return 'nf';
        })()""")
        time.sleep(2)
        continue
    time.sleep(1)

# 用 window._.invoke 调引擎（查历史任务）
print('[2] window._.invoke 查历史:')
r = ev("""(async () => {
    try {
        const res = await window._.invoke('QueryHistoryHTTPFuzzerTask', {});
        return JSON.stringify(res).slice(0, 500);
    } catch (e) {
        return 'ERR: ' + e.message;
    }
})()""")
print('    ', r)

# 再试版本
r2 = ev("""(async () => {
    try {
        const res = await window._.invoke('Version', {});
        return JSON.stringify(res).slice(0, 200);
    } catch (e) {
        return 'ERR: ' + e.message;
    }
})()""")
print('[3] Version:', r2)
ws.close()
print('=== 完成 ===')