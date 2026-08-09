# -*- coding: utf-8 -*-
"""全链路终极验证: 新建项目 → 清空历史 → 打开WebFuzzer → 填包发送 → 截图"""
import subprocess, sys, time, json, urllib.request, os, base64, io
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import websocket
from PIL import Image

OUT = r"D:\Administrator\桌面\AI工作区\skills&mcp制作\yakit-mcp\tmp10"
os.makedirs(OUT, exist_ok=True)
CDP = 9333

sys.path.insert(0, r"C:\Users\36078\skills\mcp\yakit-mcp")
from yakit_mcp.engine import YakEngine, clear_fuzzer_history
from yakit_mcp import grpc_pb2 as ypb

eng = YakEngine(auto_start=True)
eng.start()
stub = eng.connect()
print('[0] 引擎:', eng.version())

# 1. 新建项目（非 default）
print('\n[1] 新建项目测试...')
try:
    # 尝试 NewProject
    proj = stub.NewProject(ypb.NewProjectRequest(ProjectName='mcp-test-project'))
    print('    NewProject:', proj)
except Exception as e:
    print('    NewProject 失败:', repr(e))

# 列出所有项目
try:
    projs = stub.GetProjects(ypb.GetProjectsRequest())
    print('    项目列表:')
    for p in projs.Projects:
        print(f'      id={p.Id} name={p.ProjectName} type={p.Type}')
except Exception as e:
    print('    GetProjects 失败:', repr(e))

# 2. 切换项目（试试非 default）
try:
    r = stub.SetCurrentProject(ypb.SetCurrentProjectRequest(ProjectName='mcp-test-project', Type='project'))
    cur = stub.GetCurrentProjectEx(ypb.GetCurrentProjectExRequest(Type='project'))
    print('    切换到:', cur.ProjectName)
except Exception as e:
    print('    SetCurrentProject 失败:', repr(e))

# 3. 清空历史（旧内容）
print('\n[2] 清空历史(旧内容残留解决):')
cl = clear_fuzzer_history(eng)
print('    ', json.dumps(cl, ensure_ascii=False))

# 4. 启动 GUI (CDP)
flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
subprocess.Popen([r"D:\My_apps\Yakit\Yakit.exe", f"--remote-debugging-port={CDP}", "--remote-allow-origins=*"],
                 creationflags=flags, close_fds=True)
print('\n[3] GUI 启动...')
for i in range(40):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json', timeout=2) as req:
            pages = json.loads(req.read())
        if any('main/index.html' in p.get('url', '') for p in pages):
            print(f'    CDP 就绪 [{i+1}s]')
            break
    except Exception:
        pass
    time.sleep(1)

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
print('[4] 进项目...')
for i in range(30):
    texts = ev("""(() => {
        const all = [...document.querySelectorAll('*')].filter(e => e.children.length === 0);
        return JSON.stringify([...new Set(all.map(e => e.textContent.trim()).filter(t => t && t.length < 25))]);
    })()""") or "[]"
    if 'Web Fuzzer' in texts:
        print(f'    主界面 [{i}]')
        break
    # 点项目名（可能是 mcp-test-project 或 default）
    for proj_name in ['mcp-test-project', '[default]', 'default']:
        if proj_name in texts:
            ev(f"""(() => {{
                const all = [...document.querySelectorAll('div, span')];
                const t = all.find(e => e.textContent.trim() === '{proj_name}' && e.children.length === 0);
                if (t) {{ t.click(); return 'ok'; }}
                return 'nf';
            }})()""")
            time.sleep(2)
            break
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

# 5. 打开 Web Fuzzer
print('[5] 打开 Web Fuzzer...')
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

# 6. 填新包（Monaco: 聚焦后 Ctrl+A 清空再插入）
print('[6] 填请求包...')
PKT = """GET /get?full=chain&ok=1 HTTP/1.1
Host: httpbin.org
User-Agent: yakit-mcp-full-chain

"""
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
# Ctrl+A 全选删除
rpc('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'a', 'code': 'KeyA', 'modifiers': 2})
time.sleep(0.2)
rpc('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': 'a', 'code': 'KeyA', 'modifiers': 2})
time.sleep(0.2)
rpc('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'Backspace', 'code': 'Backspace'})
rpc('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': 'Backspace', 'code': 'Backspace'})
time.sleep(0.5)
rpc('Input.insertText', {'text': PKT})
time.sleep(1.5)
# 验证编辑器内容
lines = ev("""(() => {
    const ls = [...document.querySelectorAll('.view-line')];
    return ls.length ? JSON.stringify(ls.slice(0, 4).map(l => l.textContent)) : 'no-editor';
})()""")
print('    编辑器内容:', lines)

# 7. 点发送
print('[7] 发送...')
ev("""(() => {
    const all = [...document.querySelectorAll('button')];
    const t = all.find(e => {
        const t = e.textContent.trim();
        return t.startsWith('发送请求') && !t.startsWith('暂停');
    });
    if (t) { t.click(); return 'clicked'; }
    return 'nf';
})()""")
time.sleep(6)

# 8. 截图
print('[8] 截图...')
r2 = rpc('Page.captureScreenshot', {'format': 'png'})
if 'data' in r2.get('result', {}):
    img = Image.open(io.BytesIO(base64.b64decode(r2['result']['data'])))
    path = os.path.join(OUT, 'FULL_CHAIN.png')
    img.save(path)
    print(f'    {path} ({img.size})')

# 9. 查历史（确认新任务）
print('[9] 历史任务:')
hist = stub.QueryHistoryHTTPFuzzerTask(ypb.Empty())
tasks = list(hist.Tasks if hist.Tasks else [])
print(f'    任务数: {len(tasks)}')
for t in tasks[:5]:
    print(f'      id={t.Id} host={t.Host} success={t.HTTPFlowSuccessCount}')
ws.close()
print('\n=== 完成 ===')