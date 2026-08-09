# -*- coding: utf-8 -*-
"""异步任务测试: scan_start 立即返回 → task_status 查询 → task_wait 等待"""
import sys, json, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r"D:\Administrator\桌面\AI工作区\skills&mcp制作\yakit-mcp\tests")
from _common import ensure_engine
from yakit_mcp.server import yakit_scan_start, yakit_task_status, yakit_task_wait, yakit_task_list

ensure_engine()
print("== 1. yakit_scan_start（port_scan 8.8.8.8，应立即返回）==")
t0 = time.time()
r = json.loads(yakit_scan_start("port_scan", "8.8.8.8", "53,443,80", concurrent=20))
print(f"耗时 {time.time()-t0:.1f}s:", json.dumps(r, ensure_ascii=False)[:200])
tid = r.get("task_id")
if not tid:
    print("无 task_id"); sys.exit(1)

print("\n== 2. yakit_task_list ==")
print(yakit_task_list()[:400])

print("\n== 3. yakit_task_status（应立即返回状态）==")
t0 = time.time()
r = json.loads(yakit_task_status(tid))
print(f"耗时 {time.time()-t0:.1f}s: status={r.get('status')} progress={r.get('progress')} results={len(r.get('results') or [])}")

print("\n== 4. yakit_task_wait（等待完成）==")
t0 = time.time()
r = json.loads(yakit_task_wait(tid, timeout=90))
print(f"耗时 {time.time()-t0:.1f}s: status={r.get('status')} results={len(r.get('results') or [])}")
for line in (r.get("results") or [])[:5]:
    print("  >", str(line)[:150])

print("\n异步任务测试完成")