# -*- coding: utf-8 -*-
"""终极方案: CDP 页面执行 ipcRenderer.invoke('send-to-tab') → 前端开新 tab 填请求"""
import subprocess, sys, time, json, urllib.request, os, base64, io
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import websocket
from PIL import Image

CDP = 9333
OUT = r"D:\Administrator\桌面\AI工作区\skills&mcp制作\yakit-mcp\tmp14"
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
rpc('Runtime.enable', {})

print('[2] 等页面加载 + 进项目...')
for i in range(25):
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
    for label in ['暂 不', '暂不', '取 消', '取消']:
        r = ev(f"""(() => {{
            const all = [...document.querySelectorAll('button')];
            const t = all.find(e => e.textContent.trim() === '{label}');
            if (t) {{ t.click(); return 'ok'; }}
            return null;
        }})()""")
        if r:
            break
    time.sleep(1)

# 检查 ipcRenderer
print('[3] window.ipcRenderer:', ev('typeof (window.ipcRenderer || {}).invoke'))
print('    window.require:', ev('typeof window.require'))
# 可能的名字
ipc_names = ev("""(() => {
    return JSON.stringify(Object.keys(window).filter(k => /ipc|Invoke|invoke/i.test(k)).slice(0, 10));
})()""")
print('    ipc 相关 keys:', ipc_names)

# 尝试触发 send-to-tab（多路尝试）
PKT = "GET /get?sendtotab=1 HTTP/1.1\nHost: httpbin.org\nUser-Agent: mcp\n\n"
r = ev(f"""(async () => {{
    const params = {type: 'fuzzer', data: {isHttps: false, request: JSON.parse(document.getElementById('pkt').textContent), openFlag: true}};
    try {{
        if (window.ipcRenderer && window.ipcRenderer.invoke) {{
            await window.ipcRenderer.invoke('send-to-tab', params);
            return 'ipcRenderer.invoke OK';
        }}
        if (window.require) {{
            const ipc = window.require('electron').ipcRenderer;
            await ipc.invoke('send-to-tab', params);
            return 'require.electron OK';
        }}
        return 'no ipc channel';
    }} catch (e) {{ return 'ERR: ' + e.message; }}
}})()""")
print('[4] 触发 send-to-tab:', r)
time.sleep(4)

# 截图看是否弹出新 tab
r2 = rpc('Page.captureScreenshot', {'format': 'png'})
if 'data' in r2.get('result', {}):
    img = Image.open(io.BytesIO(base64.b64decode(r2['result']['data'])))
    path = os.path.join(OUT, 'SENDTOTAB_RESULT.png')
    img.save(path)
    print(f'[5] 截图: {path}')
ws.close()
print('=== 完成 ===')