# -*- coding: utf-8 -*-
"""
yakit-mcp 全功能实战测试 —— 第 9 域: 编码与反连
"""
import sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))
from _common import ensure_engine, p

from yakit_mcp.server import (yakit_codec, yakit_codec_methods, yakit_auto_decode,
                               yakit_dnslog_domain, yakit_dnslog_query, yakit_reverse_server,
                               yakit_extract_url)

engine, _ = ensure_engine()
print(f"引擎: {engine.host}:{engine.port} v{engine.version()}")

print("\n########## 1. yakit_codec_methods 编码方法列表 ##########")
r = json.loads(yakit_codec_methods())
print("ok:", r.get("ok"), "total:", r.get("total"), "方法数:", len(r.get("methods") or r.get("codec_methods") or []))
ms = r.get("methods") or r.get("codec_methods") or []
print("前 10:", [m.get("codec_method") if isinstance(m, dict) else m for m in ms[:10]])

print("\n########## 2. yakit_codec SHA1 编码 ##########")
p("codec SHA1", yakit_codec("hello yakit", "SHA1"))

print("\n########## 3. yakit_codec Base64Decode ##########")
p("codec Base64Decode", yakit_codec("aGVsbG8geWFraXQ=", "Base64Decode"))

print("\n########## 4. yakit_auto_decode 自动解码 ##########")
p("auto_decode", yakit_auto_decode("aGVsbG8gd29ybGQ="))

print("\n########## 5. yakit_extract_url（baidu 包）##########")
pkt = "GET /s?wd=mcp HTTP/1.1\r\nHost: www.baidu.com\r\nConnection: close\r\n\r\n"
p("extract_url", yakit_extract_url(pkt))

print("\n########## 6. yakit_dnslog_domain 申请反连域名 ##########")
r = json.loads(yakit_dnslog_domain())
print("ok:", r.get("ok"), "domain:", r.get("domain") or r.get("root_domain") or "")
token = r.get("token") or r.get("key") or ""
print("token:", token[:40] if token else "无")

print("\n########## 7. yakit_dnslog_query 查询记录 ##########")
if token:
    p("dnslog_query", yakit_dnslog_query(token))
else:
    print("无 token 跳过（DNSLog 只查询最近记录）")
    p("dnslog_query 空token", yakit_dnslog_query(""))

print("\n########## 8. yakit_reverse_server 反连服务器信息 ##########")
p("reverse_server", yakit_reverse_server())

print("\n编码反连域测试完成")