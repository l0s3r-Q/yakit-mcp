# -*- coding: utf-8 -*-
"""找 Random Local Password 的生成/存储（getLocalPassword / secret 写入位置）"""
import sys, re
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

data = open(r'D:\My_apps\Yakit\resources\app.asar', 'rb').read()

# 找 password/port 从哪来（asyncStartSecretLocalYakEngineServer 的调用方）
idx = data.find(b'asyncStartSecretLocalYakEngineServer')
print('定义 @', idx)
# 找调用处
calls = [m.start() for m in re.finditer(rb'asyncStartSecretLocalYakEngineServer\(', data)]
print('调用处:', calls)
for c in calls[1:3]:
    chunk = data[c-600:c+300]
    txt = ''.join(chr(b) if 32 <= b < 127 else '\n' for b in chunk)
    lines = [l.strip() for l in txt.split('\n') if l.strip()]
    print(f'\n--- 调用上下文 @{c} ---')
    for l in lines[-15:]:
        print(' ', l[:180])

# 找 getSecretLocalPassword / password 生成
for pat in [rb'getSecretLocal', rb'randomPassword', rb'randomBytes', rb'generatePassword', rb'crypto.*random', rb'\.password\s*=']:
    hits = [m.start() for m in re.finditer(pat, data)]
    print(f'\n{pat.decode()}: {len(hits)} 处')
    for h in hits[:3]:
        ctx = data[max(0, h-80):h+120]
        txt = ''.join(chr(b) if 32 <= b < 127 else ' ' for b in ctx)
        print(f'  @{h}: {txt[:180]}')