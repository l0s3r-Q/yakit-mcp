# -*- coding: utf-8 -*-
"""演示: Agent 自动生成 Burp 包 → 重放 → 截图"""
import subprocess, sys, time, json, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

OUT = r"D:\Administrator\桌面\AI工作区\skills&mcp制作\yakit-mcp\tmp9"

# 1. 先启动 Yakit GUI(CDP模式) 拿真实窗口截图
flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
subprocess.Popen([r"D:\My_apps\Yakit\Yakit.exe", "--remote-debugging-port=9333", "--remote-allow-origins=*"],
                 creationflags=flags, close_fds=True)
print('[1] GUI 已启动 (CDP 9333)')

# 2. Agent 自动生成请求包（模拟: 测试一个带参数的 GET）
print('\n[2] Agent 自动生成 Burp 包:')
packet = """GET /get?id=1001&name=test&debug=1 HTTP/1.1
Host: httpbin.org
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0
Accept: application/json
Connection: close

"""
print(packet)

# 3. 重放 + 截图
print('[3] 调用 yakit_replay...')
sys.path.insert(0, r"C:\Users\36078\skills\mcp\yakit-mcp")
from yakit_mcp.server import yakit_replay
r = json.loads(yakit_replay(packet, is_https=False, auto_protocol=True, try_both=True,
                             save_to_gui=True, capture=True,
                             capture_output_dir=OUT, wait_gui_seconds=2))
print(f'    selected: {r.get("selected_protocol")} | status: {r.get("status_code")} | dur: {r.get("duration_ms")}ms')
print(f'    url: {r.get("url")}')
cap = r.get("capture", {})
print(f'    截图 mode: {cap.get("mode")} | saved: {cap.get("saved_path")}')
print(f'    base64: {len(cap.get("image_base64",""))} 字符')

# 4. 响应体摘要
resp = r.get("response_raw", "")
import re
# 提取 JSON 部分
if resp:
    print(f'\n[4] 响应摘要:')
    lines = resp.split("\n")
    for l in lines[:6]:
        print(f'    {l[:100]}')