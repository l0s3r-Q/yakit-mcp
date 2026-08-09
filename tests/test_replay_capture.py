# -*- coding: utf-8 -*-
"""测试: 重放 + 截图（GUI 不可见时渲染回退）"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from yakit_mcp.server import yakit_replay

out = r"%WORKSPACE%\yakit-mcp\tmp\shots"
r = json.loads(yakit_replay(
    """GET /get HTTP/1.1
Host: httpbin.org
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)
Accept: application/json

""",
    is_https=False,
    save_to_gui=True,
    capture=True,
    capture_output_dir=out,
    wait_gui_seconds=0.5,
))
print("ok:", r.get("ok"), "| status:", r.get("status_code"))
print("gui_visible:", r.get("gui_visible"))
cap = r.get("capture", {})
print("capture.ok:", cap.get("ok"))
print("capture.mode:", cap.get("mode"))
print("capture.saved_path:", cap.get("saved_path"))
print("capture.fallback_reason:", cap.get("fallback_reason"))
print("capture.base64 len:", len(cap.get("image_base64", "")))
