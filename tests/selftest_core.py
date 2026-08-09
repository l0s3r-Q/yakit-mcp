# -*- coding: utf-8 -*-
"""核心自测: 引擎启动 + 解析报文 + 重放 + 入库 + 状态"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from yakit_mcp.engine import YakEngine, parse_http_packet, replay_packet, convert_to_httpflow, query_http_flows
from yakit_mcp.capture import capture_window

print("=== 1. 引擎启动 ===")
eng = YakEngine(auto_start=True)
ok = eng.start()
print("引擎运行:", ok, "| 版本:", eng.version() if ok else "-")

print("\n=== 2. 解析 Burp 包 ===")
pkt = """POST /api/login HTTP/1.1
Host: httpbin.org
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)
Content-Type: application/json
Content-Length: 32

{"username":"admin","password":"123456"}"""
info = parse_http_packet(pkt)
print(json.dumps({k: v for k, v in info.items() if k != 'request'}, ensure_ascii=False, indent=2))

print("\n=== 3. 重放（httpbin POST）===")
r = replay_packet(eng, pkt, return_raw=True)
print("ok:", r.get("ok"), "| status:", r.get("status_code"), "| dur:", r.get("duration_ms"), "ms")
print("url:", r.get("url"))
print("响应体前 120:", (r.get("response_raw") or "")[:120].replace("\n", " "))

print("\n=== 4. 入库 GUI 可见 ===")
if r.get("raw_response") is not None:
    f = convert_to_httpflow(eng, r["raw_response"])
    print("入库:", json.dumps(f, ensure_ascii=False))

print("\n=== 5. 查询流量 ===")
q = query_http_flows(eng, keyword="httpbin", limit=5)
print("查询:", json.dumps({k: v for k, v in q.items() if k != 'flows'}, ensure_ascii=False))
if q.get("flows"):
    print("最新一条:", json.dumps(q["flows"][0], ensure_ascii=False))

print("\n=== 6. 截图（无 GUI 时预期失败但优雅返回）===")
cap = capture_window("Yakit", output_dir=r"%WORKSPACE%\yakit-mcp\tmp\shots")
print(json.dumps({k: (v if k != 'image_base64' else f"<{len(v)} chars>") for k, v in cap.items()}, ensure_ascii=False))

eng.close()
print("\n=== 自测完成 ===")
