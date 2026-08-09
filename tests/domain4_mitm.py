# -*- coding: utf-8 -*-
"""
yakit-mcp 全功能实战测试 —— 第 4 域: MITM 抓包
目标: 启动 MITM → 代理访问 baidu.com → 查流量 → 停止
"""
import sys, json, time, urllib.request, socket
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))
from _common import ensure_engine, p

from yakit_mcp.server import (yakit_mitm_start, yakit_mitm_status, yakit_mitm_stop,
                               yakit_mitm_flows, yakit_replay)

engine, gui_alive = ensure_engine()
print(f"引擎: {engine.host}:{engine.port} v{engine.version()} GUI={gui_alive}")

print("\n########## 1. yakit_mitm_start 启动 MITM（端口 8083）##########")
p("mitm_start", yakit_mitm_start(port=8083))

print("\n########## 2. yakit_mitm_status ##########")
p("mitm_status", yakit_mitm_status())

print("\n########## 3. 通过 MITM 代理访问 baidu.com ##########")
import urllib.request as ur
try:
    proxy = ur.ProxyHandler({'http': 'http://127.0.0.1:8083', 'https': 'http://127.0.0.1:8083'})
    opener = ur.build_opener(proxy)
    resp = opener.open('http://www.baidu.com/', timeout=15)
    print("代理访问状态:", resp.status)
    body = resp.read(200)
    print("响应前 120 字:", body.decode('utf-8', errors='replace')[:120].replace("\n", " "))
except Exception as e:
    print("代理访问异常（预期：MITM 拦截 HTTP 可能需要处理）:", str(e)[:200])

print("\n########## 4. yakit_mitm_flows 查抓到的流量 ##########")
time.sleep(2)
p("mitm_flows", yakit_mitm_flows(limit=10))

print("\n########## 5. yakit_mitm_stop 停止 MITM ##########")
p("mitm_stop", yakit_mitm_stop(port=8083))

print("\n########## 6. 停止后 status 验证 ##########")
time.sleep(1)
p("mitm_status_after", yakit_mitm_status())

print("\nMITM 抓包域测试完成")