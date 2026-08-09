# -*- coding: utf-8 -*-
"""
yakit-mcp 全功能实战测试 —— 第 10 域: 插件体系
"""
import sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))
from _common import ensure_engine, p

from yakit_mcp.server import (yakit_query_plugins, yakit_plugin_tags,
                               yakit_exec_plugin, yakit_exec_packet_plugin)

engine, _ = ensure_engine()
print(f"引擎: {engine.host}:{engine.port} v{engine.version()}")

print("\n########## 1. yakit_plugin_tags 插件标签 ##########")
r = json.loads(yakit_plugin_tags())
tags = r.get("tags") or []
print("ok:", r.get("ok"), "标签数:", len(tags))
print("前 10:", [t.get("value") if isinstance(t, dict) else t for t in tags[:10]])

print("\n########## 2. yakit_query_plugins 查插件（关键词 扫描）##########")
r = json.loads(yakit_query_plugins(keyword="扫描", limit=5))
print("ok:", r.get("ok"), "total:", r.get("total"))
for p_ in (r.get("plugins") or [])[:5]:
    print("  ", p_.get("id"), p_.get("name"), "|", p_.get("type"))

print("\n########## 3. yakit_exec_plugin 执行插件（信息收集类）##########")
r = json.loads(yakit_query_plugins(limit=50))
plugs = r.get("plugins") or []
target = None
for p_ in plugs:
    if p_.get("type") == "nuclei" and "指纹" in p_.get("name", ""):
        target = p_["name"]; break
if not target:
    for p_ in plugs:
        if p_.get("type") == "nuclei":
            target = p_["name"]; break
print("选插件:", target)
if target:
    er = json.loads(yakit_exec_plugin(target, json.dumps({"target": "http://www.baidu.com/"}, ensure_ascii=False)))
    print("exec ok:", er.get("ok"), "script_id:", er.get("script_id"))
    for line in (er.get("results") or [])[:8]:
        print("  >", str(line)[:160])
    print("reason:", str(er.get("reason", ""))[:250])

print("\n########## 4. yakit_exec_packet_plugin 对包执行插件 ##########")
pkt = "GET / HTTP/1.1\r\nHost: www.baidu.com\r\nConnection: close\r\n\r\n"
r = json.loads(yakit_exec_packet_plugin("HTTP请求走私", pkt))
print("ok:", r.get("ok"), "results:", len(r.get("results") or []))
for line in (r.get("results") or [])[:5]:
    print("  >", str(line)[:150])
print("reason:", str(r.get("reason", ""))[:200])

print("\n插件域测试完成")