# -*- coding: utf-8 -*-
"""优先级10 测试: quick_scan 组合 + 错误人话化"""
import sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r"D:\Administrator\桌面\AI工作区\skills&mcp制作\yakit-mcp\tests")
from _common import ensure_engine
from yakit_mcp.server import yakit_quick_scan, yakit_exec_plugin, yakit_exec_packet_plugin

ensure_engine()

print("== 1. yakit_quick_scan（baidu.com 一键扫描，等待完成）==")
r = json.loads(yakit_quick_scan("www.baidu.com", ports="80,443", wait=True, wait_timeout=120))
print("status:", r.get("status"))
print("summary:", json.dumps(r.get("summary", {}), ensure_ascii=False)[:300])
print("asset_ports:", json.dumps(r.get("asset_ports", [])[:3], ensure_ascii=False)[:300])
print("results 数:", len(r.get("results") or []))

print("\n== 2. 错误人话化（exec 不存在的插件）==")
r = json.loads(yakit_exec_plugin("不存在的插件XYZ", "{}"))
print("ok:", r.get("ok"))
print("reason_human:", r.get("reason_human", "（无 reason_human 字段）"))
print("reason:", str(r.get("reason", ""))[:150])

print("\n== 3. 错误人话化（对包执行不适配插件）==")
pkt = "GET / HTTP/1.1\r\nHost: www.baidu.com\r\nConnection: close\r\n\r\n"
r = json.loads(yakit_exec_packet_plugin("HTTP请求走私", pkt))
print("ok:", r.get("ok"), "results:", len(r.get("results") or []))

print("\n优先级10 测试完成")