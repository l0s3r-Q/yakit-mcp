# -*- coding: utf-8 -*-
"""高级能力测试: 批量插件/CSRF/流量导出/字典/WebShell/反连配置"""
import sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r"D:\Administrator\桌面\AI工作区\skills&mcp制作\yakit-mcp\tests")
from _common import ensure_engine
from yakit_mcp.server import (yakit_exec_batch_packet_plugin, yakit_generate_csrf_poc,
                               yakit_export_flows, yakit_payload_query, yakit_payload_save,
                               yakit_webshell_generate, yakit_reverse_configure)

ensure_engine()

pkt = "GET / HTTP/1.1\r\nHost: www.baidu.com\r\nConnection: close\r\n\r\n"

print("== 1. 批量插件扫描（2 个插件）==")
r = json.loads(yakit_exec_batch_packet_plugin("HTTP请求走私,SSRF HTTP Public", pkt, timeout=20))
print("ok:", r.get("ok"), "scripts:", r.get("scripts"))
for x in (r.get("results") or [])[:5]:
    print("  ", json.dumps(x, ensure_ascii=False)[:200])
print("reason:", str(r.get("reason", ""))[:200])

print("\n== 2. CSRF POC 生成 ==")
r = json.loads(yakit_generate_csrf_poc(pkt))
print("ok:", r.get("ok"))
print("code 前 300:", str(r.get("code", ""))[:300])
print("reason:", str(r.get("reason", ""))[:150])

print("\n== 3. 流量导出 ==")
r = json.loads(yakit_export_flows(keyword="baidu", limit=3))
print("ok:", r.get("ok"), "total:", r.get("total"))
for f in (r.get("flows") or [])[:2]:
    print("  ", f.get("url", "")[:60], f.get("status_code"), "req:", len(f.get("request", "")), "resp:", len(f.get("response", "")))

print("\n== 4. 字典保存 + 查询 ==")
r = json.loads(yakit_payload_save("mcp-test-dict", "admin\nroot\ntest", is_new=True))
print("save ok:", r.get("ok"), str(r.get("reason", ""))[:100])
r = json.loads(yakit_payload_query("mcp-test-dict"))
print("query ok:", r.get("ok"), "total:", r.get("total"), "payloads:", (r.get("payloads") or [])[:5])
print("reason:", str(r.get("reason", ""))[:150])

print("\n== 5. WebShell 生成 ==")
r = json.loads(yakit_webshell_generate("php", "cmd", confuse=False))
print("ok:", r.get("ok"))
print("script 前 200:", str(r.get("script", ""))[:200])
print("reason:", str(r.get("reason", ""))[:150])

print("\n== 6. 反连配置 ==")
r = json.loads(yakit_reverse_configure("0.0.0.0:8088"))
print("ok:", r.get("ok"), "configured:", r.get("configured"))
print("reason:", str(r.get("reason", ""))[:150])

print("\n高级能力测试完成")