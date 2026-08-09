# -*- coding: utf-8 -*-
"""GUI 启动后立刻抓引擎进程命令行（拿 random local password）"""
import subprocess, sys, time, urllib.request, json, re
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

CDP = 9333
flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
subprocess.Popen([r"D:\My_apps\Yakit\Yakit.exe", f"--remote-debugging-port={CDP}", "--remote-allow-origins=*"],
                 creationflags=flags, close_fds=True)
print('[0] GUI 启动，等引擎进程出现...')

# 轮询进程列表，一旦 yak 引擎出现立即抓命令行
import ctypes
from ctypes import wintypes

for attempt in range(40):
    # 用 tasklist 找 yak 进程
    tl = subprocess.run(['tasklist'], capture_output=True, text=True, timeout=10).stdout
    yaks = [l for l in tl.split('\n') if 'yak' in l.lower() and '.exe' in l]
    if yaks:
        print(f'[1] 发现 yak 进程 [{attempt}]:')
        for y in yaks[:5]:
            print('   ', y.strip())
        # 用 wmic/powershell 拿命令行
        try:
            r = subprocess.run(
                ['powershell', '-NoProfile', '-Command',
                 "Get-CimInstance Win32_Process -Filter \"Name like '%yak%'\" | ForEach-Object { $_.ProcessId.ToString() + '||' + $_.CommandLine }"],
                capture_output=True, text=True, timeout=15)
            print('\n[2] 引擎命令行:')
            for line in r.stdout.strip().split('\n'):
                if '||' in line:
                    pid, cmd = line.split('||', 1)
                    print(f'  PID {pid}: {cmd[:200]}')
                    # 提取 --local-password 后的密码
                    m = re.search(r'--local-password\s+(\S+)', cmd)
                    if m:
                        print(f'\n  ★ 密码: {m.group(1)}')
                        # 保存密码
                        with open(r'D:\Administrator\桌面\AI工作区\skills&mcp制作\yakit-mcp\tmp11\engine_pwd.txt', 'w') as f:
                            f.write(m.group(1))
                        print('  已保存到 engine_pwd.txt')
        except Exception as e:
            print('  拿命令行失败:', repr(e))
        break
    time.sleep(1)
else:
    print('引擎进程未出现')
    # 最后再查一次
    tl = subprocess.run(['tasklist'], capture_output=True, text=True, timeout=10).stdout
    print([l for l in tl.split('\n') if 'yak' in l.lower()][:5])