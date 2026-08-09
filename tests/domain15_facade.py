# -*- coding: utf-8 -*-
"""Facades 监听测试"""
import sys, json, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r"D:\Administrator\桌面\AI工作区\skills&mcp制作\yakit-mcp\tests")
from _common import ensure_engine
from yakit_mcp.server import (yakit_facade_start, yakit_facade_stop,
                               yakit_task_status, yakit_facade_yso)

ensure_engine()

print("== 1. yakit_facade_start（本地 8088 监听）==")
r = json.loads(yakit_facade_start(local_port=8088, enable_dnslog=True, dnslog_port=8089))
print(json.dumps(r, ensure_ascii=False)[:300])
tid = r.get("task_id")
time.sleep(3)

print("\n== 2. 端口监听确认 ==")
import socket
for port in (8088, 8089):
    s = socket.socket(); s.settimeout(1)
    print(f"  端口 {port}:", "LISTENING" if s.connect_ex(('127.0.0.1', port)) == 0 else "未监听")
    s.close()

print("\n== 3. 任务状态 ==")
print(json.dumps(json.loads(yakit_task_status(tid)), ensure_ascii=False)[:300])

print("\n== 4. 停止 ==")
print(json.dumps(json.loads(yakit_facade_stop(tid)), ensure_ascii=False)[:200])
time.sleep(1)
s = socket.socket(); s.settimeout(1)
print("  停止后 8088:", "仍监听" if s.connect_ex(('127.0.0.1', 8088)) == 0 else "已释放")
s.close()

print("\n== 5. yakit_facade_yso（YSO 监听）==")
r = json.loads(yakit_facade_yso(reverse_port=8090, gadget="CommonsCollections1", class_name="dnslog"))
print(json.dumps(r, ensure_ascii=False)[:300])
tid2 = r.get("task_id")
if tid2:
    time.sleep(2)
    s = socket.socket(); s.settimeout(1)
    print("  8090:", "LISTENING" if s.connect_ex(('127.0.0.1', 8090)) == 0 else "未监听")
    s.close()
    print("  停止:", json.dumps(json.loads(yakit_facade_stop(tid2)), ensure_ascii=False)[:150])

print("\nFacades 测试完成")