# -*- coding: utf-8 -*-
"""测试 MCP 工具层（直接调用工具函数）"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from yakit_mcp.server import yakit_status, yakit_parse_packet, yakit_replay, yakit_query_flows

print("=== yakit_status ===")
print(yakit_status()[:300])

print("\n=== yakit_parse_packet ===")
print(yakit_parse_packet("""GET /ping HTTP/1.1
Host: httpbin.org
User-Agent: test

""")[:400])

print("\n=== yakit_replay (httpbin GET) ===")
r = json.loads(yakit_replay("""GET /get HTTP/1.1
Host: httpbin.org
User-Agent: Mozilla/5.0

""", is_https=False, save_to_gui=True))
print("ok:", r.get("ok"), "status:", r.get("status_code"), "dur:", r.get("duration_ms"), "ms")
print("gui_visible:", r.get("gui_visible"), "flow:", r.get("flow", {}).get("id"))
print("url:", r.get("url"))

print("\n=== yakit_query_flows ===")
q = json.loads(yakit_query_flows(keyword="httpbin", limit=3))
print("total:", q.get("total"), "flows:", len(q.get("flows", [])))
