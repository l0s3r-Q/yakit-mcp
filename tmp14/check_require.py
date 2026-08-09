# -*- coding: utf-8 -*-
import sys, json, urllib.request, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import websocket
CDP = 9333
try:
    with urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json', timeout=2) as req:
        pages = json.loads(req.read())
    mains = [p for p in pages if 'main/index.html' in p.get('url', '')]
    print('页面:', len(mains))
    if not mains:
        print('无主页面（可能是我起的GUI刚退）'); sys.exit(1)
    ws = websocket.create_connection(mains[0]['webSocketDebuggerUrl'], timeout=10)
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
    rpc('Runtime.enable', {})
    print('typeof require:', ev('typeof window.require'))
    print('require keys:', ev('window.require ? JSON.stringify(Object.keys(window.require).slice(0,5)) : "none"'))
    print('electron:', ev('typeof window.require === "function" ? (() => { try { return typeof window.require("electron") } catch(e) { return "ERR:" + e.message.slice(0,50) } })() : "no"'))
    ws.close()
except Exception as e:
    print('异常:', repr(e)[:100])
