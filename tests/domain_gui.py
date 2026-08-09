# -*- coding: utf-8 -*-
"""
yakit-mcp 全功能实战测试 —— 第 2 域: GUI 联动（open_webfuzzer/capture）
说明: 本会话环境 GUI 生命周期受限，若 GUI 不在则记录环境限制；引擎功能照测。
"""
import sys, json, os, time, subprocess
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))
from _common import ensure_engine, p

from yakit_mcp.server import yakit_status, yakit_open_webfuzzer, yakit_capture, yakit_replay

engine, gui_alive = ensure_engine()
print(f"引擎: {engine.host}:{engine.port} v{engine.version()} GUI={gui_alive}")

# 尝试启动 GUI（本环境可能被回收，尽力而为）
if not gui_alive:
    YAKIT = r"D:\My_apps\Yakit\Yakit.exe"
    subprocess.run(['taskkill', '/F', '/IM', 'Yakit.exe'], capture_output=True)
    time.sleep(1)
    subprocess.Popen([YAKIT, '--remote-debugging-port=9333', '--remote-allow-origins=*'],
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP, close_fds=True)
    print("已尝试启动 GUI，等待 15s...")
    time.sleep(15)

print("\n########## 1. yakit_open_webfuzzer ##########")
try:
    p("open_webfuzzer", yakit_open_webfuzzer(launch_gui=False))
except Exception as e:
    print("open_webfuzzer 异常:", repr(e)[:200])

print("\n########## 2. yakit_capture ##########")
try:
    r = json.loads(yakit_capture())
    print("mode:", r.get("mode"), "ok:", r.get("ok"))
    print("saved:", r.get("saved_path") or r.get("path") or "")
    print("reason:", str(r.get("reason", ""))[:150])
except Exception as e:
    print("capture 异常:", repr(e)[:200])

print("\n########## 3. yakit_replay(capture=True) 重放+截图 ##########")
pkt = "GET / HTTP/1.1\r\nHost: www.baidu.com\r\nConnection: close\r\n\r\n"
try:
    r = json.loads(yakit_replay(pkt, capture=True, save_to_gui=True))
    print("status:", r.get("status_code"), "capture.mode:", (r.get("capture") or {}).get("mode"))
    print("capture.saved:", (r.get("capture") or {}).get("saved_path", ""))
    print("capture.ok:", (r.get("capture") or {}).get("ok"))
except Exception as e:
    print("replay+capture 异常:", repr(e)[:200])

print("\nGUI 联动域测试完成")