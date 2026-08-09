# -*- coding: utf-8 -*-
"""从 app.asar 二进制直接搜 local-password 机制"""
import re, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
data = open(r'D:\My_apps\Yakit\resources\app.asar', 'rb').read()
print('asar 大小:', len(data))
for pat in [rb'local-password', rb'localPassword', rb'local-pwd', rb'check-secret-local-grpc', rb'grpc.*9011', rb'9011']:
    hits = [m.start() for m in re.finditer(pat, data)]
    print(f'\n{pat.decode()}: {len(hits)} 处')
    for h in hits[:4]:
        ctx = data[max(0, h-120):h+200]
        txt = ''.join(chr(b) if 32 <= b < 127 else ' ' for b in ctx)
        print(f'  @{h}: {txt[:260]}')
