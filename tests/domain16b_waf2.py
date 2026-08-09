# -*- coding: utf-8 -*-
"""WAF 规则命中验证: 对带 CDN/代理特征的目标"""
import sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r"D:\Administrator\桌面\AI工作区\skills&mcp制作\yakit-mcp\tests")
from _common import ensure_engine
from yakit_mcp.server import yakit_waf_detect

ensure_engine()

# httpbin 走 AWS（可能有 awselb 特征）
print("== WAF 检测 httpbin.org（AWS 托管）==")
r = json.loads(yakit_waf_detect("http://httpbin.org/get"))
print(json.dumps(r, ensure_ascii=False, indent=2)[:900])