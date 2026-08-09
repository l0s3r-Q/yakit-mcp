# -*- coding: utf-8 -*-
"""WAF 识别实测"""
import sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r"D:\Administrator\桌面\AI工作区\skills&mcp制作\yakit-mcp\tests")
from _common import ensure_engine
from yakit_mcp.server import yakit_waf_detect

ensure_engine()
print("== WAF 检测 baidu.com ==")
r = json.loads(yakit_waf_detect("https://www.baidu.com/"))
print(json.dumps(r, ensure_ascii=False, indent=2)[:900])