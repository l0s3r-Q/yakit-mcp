# -*- coding: utf-8 -*-
"""从 main.js 找 local-password 模式密码"""
import re, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
data = open(r'D:\Administrator\桌面\AI工作区\skills&mcp制作\yakit-mcp\tmp8\main_chunk.js', 'rb').read()
print('main.js 存在:', len(data) > 0)
# 找 local-password / local-pwd / 9011
for pat in [rb'local-password', rb'localPassword', rb'--secret', rb'9011', rb'check-secret-local-grpc', rb'SecretKey', rb'secret-key']:
    hits = [m.start() for m in re.finditer(pat, data)]
    print(f'\n{pat.decode()}: {len(hits)} 处')
    for h in hits[:3]:
        ctx = data[max(0, h-100):h+150]
        txt = ''.join(chr(b) if 32 <= b < 127 else ' ' for b in ctx)
        print(f'  @{h}: {txt[:220]}')
