# -*- coding: utf-8 -*-
"""
yakit-mcp 实战测试 —— 第 5 域补充: simple_detect + basic_crawler（正确签名）
"""
import sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))
from _common import ensure_engine, p

from yakit_mcp.server import yakit_simple_detect, yakit_basic_crawler

engine, _ = ensure_engine()
print(f"引擎: {engine.host}:{engine.port} v{engine.version()}")

print("\n########## 1. yakit_simple_detect（baidu.com:80，60s 超时）##########")
try:
    r = json.loads(yakit_simple_detect("www.baidu.com", ports="80", concurrent=10, total_timeout=60))
    print("ok:", r.get("ok"))
    evs = r.get("events") or r.get("parsed") or []
    for e in evs[:10]:
        print("  ", str(e)[:200])
    print("reason:", str(r.get("reason", ""))[:300])
except Exception as e:
    print("simple_detect 异常:", repr(e)[:300])

print("\n########## 2. yakit_basic_crawler（baidu.com 深度1）##########")
try:
    r = json.loads(yakit_basic_crawler("http://www.baidu.com/", max_depth=1, max_urls=15, concurrent=5))
    print("ok:", r.get("ok"))
    urls = r.get("urls") or r.get("results") or []
    print("URL 数:", len(urls))
    for u in urls[:10]:
        print("  ", str(u)[:130])
    print("reason:", str(r.get("reason", ""))[:300])
except Exception as e:
    print("crawler 异常:", repr(e)[:200])

print("\n补充域测试完成")