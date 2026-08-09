# -*- coding: utf-8 -*-
"""
yakit-mcp 全功能实战测试 —— 第 5 域: 主动扫描
目标: 端口扫描 8.8.8.8（常见端口） + 弱口令爆破类型 + 基础爬虫 baidu.com
"""
import sys, json, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))
from _common import ensure_engine, p

from yakit_mcp.server import (yakit_port_scan, yakit_brute_types, yakit_basic_crawler,
                               yakit_simple_detect, yakit_start_brute)

engine, gui_alive = ensure_engine()
print(f"引擎: {engine.host}:{engine.port} v{engine.version()} GUI={gui_alive}")

print("\n########## 1. yakit_brute_types 爆破类型 ##########")
p("brute_types", yakit_brute_types())

print("\n########## 2. yakit_port_scan 端口扫描 8.8.8.8（53,443）##########")
r = json.loads(yakit_port_scan("8.8.8.8", "53,443,80", concurrent=20))
print("ok:", r.get("ok"))
print("total_events:", r.get("total_events"))
evs = r.get("events") or r.get("parsed") or []
for e in evs[:10]:
    print("  ", str(e)[:150])
print("用时/状态:", json.dumps({k: v for k, v in r.items() if k not in ("events", "parsed", "results")}, ensure_ascii=False)[:300])

print("\n########## 3. yakit_basic_crawler 爬虫 baidu.com（深度1，防过深）##########")
try:
    r = json.loads(yakit_basic_crawler("http://www.baidu.com/", max_depth=1, max_urls=20, concurrent=5, timeout=80))
    print("ok:", r.get("ok"))
    print("urls 数:", len(r.get("urls") or r.get("results") or []))
    for u in (r.get("urls") or r.get("results") or [])[:5]:
        print("  ", str(u)[:120])
    print("reason:", str(r.get("reason", ""))[:200])
except Exception as e:
    print("crawler 异常:", repr(e)[:200])

print("\n########## 4. yakit_simple_detect 漏洞检测 baidu.com ##########")
try:
    r = json.loads(yakit_simple_detect("http://www.baidu.com/", ["80"], timeout=90))
    print("ok:", r.get("ok"))
    evs = r.get("events") or r.get("parsed") or []
    for e in evs[:8]:
        print("  ", str(e)[:180])
    print("reason:", str(r.get("reason", ""))[:200])
except Exception as e:
    print("simple_detect 异常:", repr(e)[:200])

print("\n########## 5. yakit_start_brute（只列类型不实际爆破，避免触发风险）##########")
try:
    r = json.loads(yakit_brute_types())
    print("爆破类型数:", r.get("total") or len(r.get("types") or []))
except Exception as e:
    print("brute_types 异常:", repr(e)[:200])

print("\n主动扫描域测试完成")