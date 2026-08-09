# -*- coding: utf-8 -*-
"""挖 local-password 的 password 来源"""
import sys, re
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

data = open(r'D:\My_apps\Yakit\resources\app.asar', 'rb').read()
idx = data.find(b'--local-password')
print('@', idx)
# 往前取 3000 字节找 password 赋值
chunk = data[idx-3000:idx+800]
txt = ''.join(chr(b) if 32 <= b < 127 else '\n' for b in chunk)
lines = [l.strip() for l in txt.split('\n') if l.strip()]
for l in lines[-35:]:
    print(' ', l[:200])