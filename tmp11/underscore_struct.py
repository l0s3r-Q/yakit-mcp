# -*- coding: utf-8 -*-
"""看 window._ 结构（invoke 的调用方式）"""
import subprocess, sys, time, json, urllib.request
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import websocket

CDP = 9333
try:
    with urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json', timeout=2) as req:
        pages = json.loads(req.read())
except Exception:
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen([r"D:\My_apps\Yakit\Yakit.exe", f"--remote-debugging-port={CDP}", "--remote-allow-origins=*"],
                     creationflags=flags, close_fds=True)
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
    except Exception as e:
        return 'ERR'

rpc('Runtime.enable')
print('_ typeof:', ev('typeof window._'))
print('_ keys:', ev('window._ ? Object.keys(window._).slice(0,20) : "none"'))
print('_ proto:', ev('window._ ? Object.getOwnPropertyNames(Object.getPrototypeOf(window._)).slice(0,20) : "none"'))
print('_ invoke typeof:', ev('typeof (window._ || {}).invoke'))
ws.close()