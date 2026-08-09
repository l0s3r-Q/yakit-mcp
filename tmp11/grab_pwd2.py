# -*- coding: utf-8 -*-
"""精确找 yak_windows 引擎进程命令行（含 --local-password 密码）"""
import subprocess, sys, time, re
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

for attempt in range(50):
    r = subprocess.run(
        ['powershell', '-NoProfile', '-Command',
         "Get-CimInstance Win32_Process | Where-Object { $_.Name -like '*yak*' } | ForEach-Object { $_.ProcessId.ToString() + '||' + $_.CommandLine }"],
        capture_output=True, text=True, timeout=20)
    found = False
    for line in r.stdout.strip().split('\n'):
        if '||' in line and ('grpc' in line or 'local-password' in line):
            pid, cmd = line.split('||', 1)
            print(f'[{attempt}] PID {pid}: {cmd[:250]}')
            m = re.search(r'--local-password\s+(\S+)', cmd)
            if m:
                print(f'  ★ 密码: {m.group(1)}')
                with open(r'D:\Administrator\桌面\AI工作区\skills&mcp制作\yakit-mcp\tmp11\engine_pwd.txt', 'w') as f:
                    f.write(m.group(1))
                found = True
    if found:
        break
    if attempt % 5 == 0:
        print(f'[{attempt}] 等引擎...')
    time.sleep(2)
else:
    print('未找到引擎进程（可能没起来或名字不同）')
    # 兜底: 列出所有含 yak 的进程名
    tl = subprocess.run(['tasklist'], capture_output=True, text=True).stdout
    for l in tl.split('\n'):
        if 'yak' in l.lower():
            print('  tasklist:', l.strip())