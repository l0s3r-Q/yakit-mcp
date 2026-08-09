# -*- coding: utf-8 -*-
"""
yakit-mcp 全功能实战测试 —— 第 1 域: 核心重放
目标: www.baidu.com
"""
import sys, json, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))
from _common import ensure_engine, p

from yakit_mcp.server import (yakit_status, yakit_parse_packet, yakit_replay,
                               yakit_replay_batch, yakit_query_flows, yakit_extract_url)

engine, gui_alive = ensure_engine()
print(f"引擎就绪: {engine.host}:{engine.port} v{engine.version()} GUI={gui_alive}")

print("\n########## 1. yakit_status ##########")
p("yakit_status", yakit_status())

print("\n########## 2. yakit_parse_packet（baidu.com 包）##########")
pkt = "GET / HTTP/1.1\r\nHost: www.baidu.com\r\nUser-Agent: Mozilla/5.0\r\nAccept: */*\r\nConnection: close\r\n\r\n"
p("parse_packet", yakit_parse_packet(pkt))

print("\n########## 3. yakit_extract_url ##########")
p("extract_url", yakit_extract_url(pkt))

print("\n########## 4. yakit_replay（try_both 对 baidu.com）##########")
r = json.loads(yakit_replay(pkt, auto_protocol=True, try_both=True, save_to_gui=True))
print("protocol_detected:", r.get("protocol_detected"))
print("selected_protocol:", r.get("selected_protocol"))
print("status_code:", r.get("status_code"), "duration_ms:", r.get("duration_ms"))
print("gui_visible:", r.get("gui_visible"))
for a in (r.get("attempts") or []):
    print(f"  [{a.get('protocol')}] ok={a.get('ok')} status={a.get('status_code')} url={str(a.get('url'))[:60]}")
if r.get("response_raw"):
    print("响应头:", (r.get("response_raw") or "")[:200].replace("\n", " | "))

print("\n########## 5. yakit_query_flows（查 baidu 流量）##########")
p("query_flows", yakit_query_flows(keyword="baidu", limit=5))

print("\n########## 6. yakit_replay_batch（批量 2 包）##########")
pkts = json.dumps([
    "GET / HTTP/1.1\r\nHost: www.baidu.com\r\nConnection: close\r\n\r\n",
    "GET /s?wd=test HTTP/1.1\r\nHost: www.baidu.com\r\nConnection: close\r\n\r\n",
])
p("replay_batch", yakit_replay_batch(pkts, concurrency=2))

print("\n核心重放域 ✅ 完成")