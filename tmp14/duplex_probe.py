# -*- coding: utf-8 -*-
"""深挖: DuplexConnection 推送后引擎的响应（是否有回显/转发确认）"""
import sys, json, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r"C:\Users\36078\skills\mcp\yakit-mcp")
from yakit_mcp.engine import YakEngine
from yakit_mcp import grpc_pb2 as ypb

eng = YakEngine(auto_start=False)
eng.port = 9011
eng.host = '127.0.0.1'
pwd = eng._grab_engine_password()
print('密码:', 'OK' if pwd else '无')
stub = eng.connect()
print('版本:', eng.version())

# 推送 + 读取引擎所有响应（确认是否转发/回显）
config = {
    "id": f"mcp-{int(time.time()*1000)}",
    "verbose": "MCP测试2",
    "groupId": "0",
    "sortFieId": 1,
    "pageParams": {
        "id": f"mcp-{int(time.time()*1000)}",
        "groupId": "0",
        "isHttps": False,
        "request": "GET /get?a=1 HTTP/1.1\nHost: httpbin.org\nUser-Agent: t\n\n",
        "advancedConfigValue": {},
    },
}
payload = {"openFlag": True, "data": [{"PageId": "", "Type": "page", "Config": json.dumps(config, ensure_ascii=False)}]}
req = ypb.DuplexConnectionRequest(
    Data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
    MessageType="web_fuzzer_tab",
    Timestamp=int(time.time() * 1000),
)

def gen():
    yield req

print('\n发送并等待响应(15s)...')
try:
    for i, resp in enumerate(stub.DuplexConnection(gen(), timeout=15)):
        print(f'  [resp {i}] type={resp.MessageType} data={resp.Data[:200]}')
        # 引擎收到后可能广播其他事件
        if i > 5:
            break
    print('(流结束或无更多响应)')
except Exception as e:
    print('流异常:', repr(e)[:200])

# 2. 静默听引擎广播（不发送，等推送）
print('\n仅监听引擎广播(10s)...')
try:
    empty_count = 0
    for i, resp in enumerate(stub.DuplexConnection(iter([]), timeout=10)):
        print(f'  [广播 {i}] type={resp.MessageType} data={str(resp.Data)[:200]}')
        if i > 5:
            break
except Exception as e:
    print('  监听结束:', str(e)[:100])
print('=== 完成 ===')