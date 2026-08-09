# -*- coding: utf-8 -*-
"""
yakit-mcp 全功能实战测试 —— 第 8 域: 资产查询
先对 8.8.8.8 做端口扫描入库，再查 ports/hosts/domains/risks
"""
import sys, json, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))
from _common import ensure_engine, p

from yakit_mcp.server import (yakit_query_ports, yakit_query_hosts, yakit_query_domains,
                               yakit_query_risks, yakit_port_scan)

engine, _ = ensure_engine()
print(f"引擎: {engine.host}:{engine.port} v{engine.version()}")

print("\n########## 0. 先扫描 8.8.8.8 入库（53,443）##########")
r = json.loads(yakit_port_scan("8.8.8.8", "53,443,80", concurrent=20))
print("扫描 ok:", r.get("ok"), "events:", r.get("total_events"))

print("\n########## 1. yakit_query_ports（查 8.8.8.8 端口）##########")
p("query_ports", yakit_query_ports(keyword="8.8.8.8", limit=10))

print("\n########## 2. yakit_query_hosts（主机资产）##########")
p("query_hosts", yakit_query_hosts(keyword="8.8.8.8", limit=5))

print("\n########## 3. yakit_query_domains（域名资产，查 baidu）##########")
p("query_domains", yakit_query_domains(keyword="baidu", limit=5))

print("\n########## 4. yakit_query_risks（漏洞/风险查询）##########")
p("query_risks", yakit_query_risks(limit=5))

print("\n资产查询域测试完成")