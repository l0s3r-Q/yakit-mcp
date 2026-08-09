# -*- coding: utf-8 -*-
"""CDP 页面内调用引擎（免认证）: 查历史任务验证通道"""
import subprocess, sys, time, json, urllib.request
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import websocket

CDP = 9333
flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
subprocess.Popen([r"D:\My_apps\Yakit\Yakit.exe", f"--remote-debugging-port={CDP}", "--remote-allow-origins=*"],
                 creationflags=flags, close_fds=True)
print('[0] GUI 启动')
for i in range(40):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json', timeout=2) as req:
            pages = json.loads(req.read())
        if any('main/index.html' in p.get('url', '') for p in pages):
            print(f'[1] CDP 就绪 [{i+1}s]')
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

# 等加载
for i in range(20):
    v = ev('document.body ? document.body.innerText.length : -1')
    if isinstance(v, int) and v > 100:
        print(f'[2] 页面加载 [{i}]')
        break
    time.sleep(2)

# 进项目
for i in range(20):
    texts = ev("""(() => {
        const all = [...document.querySelectorAll('*')].filter(e => e.children.length === 0);
        return JSON.stringify([...new Set(all.map(e => e.textContent.trim()).filter(t => t && t.length < 25))]);
    })()""") or "[]"
    if 'Web Fuzzer' in texts:
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

# 关键: 找页面里的引擎调用通道（window 上的 invoke 或 grpc client）
print('[3] 探测页面内引擎通道:')
r = ev("""(() => {
    const keys = Object.keys(window).filter(k => /invoke|grpc|engine|ipc|bridge/i.test(k));
    return JSON.stringify(keys.slice(0, 20));
})()""")
print('    window keys:', r)

# 试 invoke 通道（Yakit 前端用 window.ipcRenderer 或类似）
r2 = ev("""(() => {
    // Yakit 前端: window.xxx.invoke("QueryHistoryHTTPFuzzerTask") 或类似
    const candidates = [];
    for (const k of Object.keys(window)) {
        const v = window[k];
        if (v && typeof v.invoke === 'function') candidates.push(k);
        if (v && v.api && typeof v.api.invoke === 'function') candidates.push(k + '.api');
    }
    return JSON.stringify(candidates);
})()""")
print('    invoke 通道:', r2)
ws.close()
print('=== 完成 ===')