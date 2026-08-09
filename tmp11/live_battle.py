# -*- coding: utf-8 -*-
"""实战全真演练: 启动Yakit → 复用引擎 → 打开WebFuzzer → 清旧填新 → 发送 → 响应截图"""
import subprocess, sys, time, json, urllib.request, os, base64, io
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import websocket
from PIL import Image

OUT = r"D:\Administrator\桌面\AI工作区\skills&mcp制作\yakit-mcp\tmp11"
os.makedirs(OUT, exist_ok=True)
CDP = 9333

# 0. 先启动 GUI(CDP模式) —— 用户要求直接实战，我直接启动
flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
subprocess.Popen([r"D:\My_apps\Yakit\Yakit.exe", f"--remote-debugging-port={CDP}", "--remote-allow-origins=*"],
                 creationflags=flags, close_fds=True)
print('[0] Yakit GUI 已启动 (CDP 9333)')

# 1. 等 GUI CDP + 引擎
sys.path.insert(0, r"C:\Users\36078\skills\mcp\yakit-mcp")
from yakit_mcp.engine import YakEngine, clear_fuzzer_history
from yakit_mcp import grpc_pb2 as ypb

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

# 引擎: 等 GUI 引擎起来（10053 或探测）
eng = YakEngine(auto_start=True)
for i in range(30):
    found = eng._probe_engine_port()
    if found:
        eng.port = found
        print(f'[2] 引擎就绪 [{i+1}s] port={found} 版本={eng.version()}')
        break
    time.sleep(1)
else:
    print('[2] 未探测到引擎，独立启动...')
    eng.auto_start = True
    eng.start()
    print(f'    独立引擎 port={eng.port} 版本={eng.version()}')

# 2. 清空历史（旧内容残留）
stub = eng.connect()
print('[3] 清空历史:')
try:
    cl = clear_fuzzer_history(eng)
    print('    ', json.dumps(cl, ensure_ascii=False))
except Exception as e:
    print('    清空失败:', repr(e))

# 3. CDP 连接操作 GUI：进项目 → 打开WebFuzzer
ws, msg_id = None, [0]
def connect():
    global ws, msg_id
    with urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json', timeout=3) as req:
        pages = json.loads(req.read())
    main = [p for p in pages if 'main/index.html' in p.get('url', '')][0]
    ws = websocket.create_connection(main['webSocketDebuggerUrl'], timeout=15)
    msg_id = [0]
    rpc('Runtime.enable', {})
    rpc('Page.enable', {})

def rpc(method, params=None):
    msg_id[0] += 1
    ws.send(json.dumps({'id': msg_id[0], 'method': method, 'params': params or {}}))
    while True:
        resp = json.loads(ws.recv())
        if resp.get('id') == msg_id[0]:
            return resp

def ev(expr):
    global ws, msg_id
    for _ in range(3):
        try:
            r = rpc('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True})
            return r.get('result', {}).get('result', {}).get('value')
        except Exception:
            try:
                connect()
            except Exception:
                return None
    return None

connect()
print('[4] 进项目 + 打开 Web Fuzzer...')
for i in range(30):
    texts = ev("""(() => {
        const all = [...document.querySelectorAll('*')].filter(e => e.children.length === 0);
        return JSON.stringify([...new Set(all.map(e => e.textContent.trim()).filter(t => t && t.length < 25))]);
    })()""") or "[]"
    if 'Web Fuzzer' in texts:
        print(f'    主界面 [{i}]')
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

ev("""(() => {
    const all = [...document.querySelectorAll('*')].filter(e => e.children.length === 0);
    const t = all.find(e => (e.textContent.trim()).toLowerCase() === 'web fuzzer');
    if (t) { t.click(); return 'ok'; }
    return 'nf';
})()""")
time.sleep(6)
for label in ['稍后再说', '拒 绝', '忽 略']:
    ev(f"""(() => {{
        const all = [...document.querySelectorAll('button')];
        const t = all.find(e => e.textContent.trim() === '{label}');
        if (t) {{ t.click(); return 'ok'; }}
        return null;
    }})()""")
time.sleep(1)

# 4. 旧内容处理：Ctrl+A 删除（新 tab 用不了就尽力清）
print('[5] 清空编辑器旧内容（Ctrl+A → Del）...')
ev("""(() => {
    const ed = document.querySelector('.monaco-editor');
    if (ed) {
        const r = ed.getBoundingClientRect();
        const opts = {bubbles: true, cancelable: true, clientX: r.left + 80, clientY: r.top + 40};
        ed.dispatchEvent(new MouseEvent('mousedown', opts));
        ed.dispatchEvent(new MouseEvent('mouseup', opts));
    }
})()""")
time.sleep(0.5)
# 全选删除（多次尝试）
for _ in range(3):
    rpc('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'a', 'code': 'KeyA', 'modifiers': 2})
    time.sleep(0.3)
    rpc('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': 'a', 'code': 'KeyA', 'modifiers': 2})
    time.sleep(0.3)
    rpc('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'Backspace', 'code': 'Backspace'})
    time.sleep(0.3)
    rpc('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': 'Backspace', 'code': 'Backspace'})
    time.sleep(0.5)

# 5. 填入新请求
print('[6] 填入新请求包...')
PKT = """GET /get?zhandou=1&flag=success HTTP/1.1
Host: httpbin.org
User-Agent: yakit-mcp-live-test

"""
rpc('Input.insertText', {'text': PKT})
time.sleep(1.5)
lines = ev("""(() => {
    const ls = [...document.querySelectorAll('.view-line')];
    return ls.length ? JSON.stringify(ls.slice(0, 4).map(l => l.textContent)) : 'no-editor';
})()""")
print('    编辑器:', lines)

# 6. 点发送
print('[7] 点发送...')
ev("""(() => {
    const all = [...document.querySelectorAll('button')];
    const t = all.find(e => {
        const t = e.textContent.trim();
        return t.startsWith('发送请求') && !t.startsWith('暂停');
    });
    if (t) { t.click(); return 'clicked'; }
    return 'nf';
})()""")

# 7. 等响应
for i in range(10):
    time.sleep(1)
    v = ev("""(() => {
        const t = document.body.innerText;
        if (t.includes('f0b')) return '有响应!';
        return '暂无';
    })()""")
    if v == '有响应!':
        print(f'    [{i+1}s] 响应出现')
        break

# 8. 截图
print('[8] 截图...')
r2 = rpc('Page.captureScreenshot', {'format': 'png'})
if 'data' in r2.get('result', {}):
    img = Image.open(io.BytesIO(base64.b64decode(r2['result']['data'])))
    path = os.path.join(OUT, 'LIVE_FULL_CHAIN.png')
    img.save(path)
    print(f'    {path} ({img.size})')

# 9. 验证引擎侧历史
try:
    hist = stub.QueryHistoryHTTPFuzzerTask(ypb.Empty())
    tasks = list(hist.Tasks if hist.Tasks else [])
    print(f'[9] 引擎历史任务: {len(tasks)}')
    for t in tasks[:3]:
        print(f'    id={t.Id} host={t.Host} success={t.HTTPFlowSuccessCount}')
except Exception as e:
    print('[9] 查历史失败:', repr(e))

ws.close()
print('=== 实战完成 ===')