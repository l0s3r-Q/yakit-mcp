# -*- coding: utf-8 -*-
"""测试截图功能（需要 Yakit GUI 运行）"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from yakit_mcp.capture import capture_window, find_window_rect

print("=== 查找窗口 ===")
rect = find_window_rect("Yakit", timeout=5)
print("窗口矩形:", json.dumps(rect, ensure_ascii=False) if rect else "未找到")

print("\n=== 截图 ===")
cap = capture_window("Yakit", output_dir=r"D:\Administrator\桌面\AI工作区\skills&mcp制作\yakit-mcp\tmp\shots")
print("ok:", cap.get("ok"))
print("title:", cap.get("title"))
print("size:", cap.get("size"))
print("saved_path:", cap.get("saved_path"))
print("base64 长度:", len(cap.get("image_base64", "")))
