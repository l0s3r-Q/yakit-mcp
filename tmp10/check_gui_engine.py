# -*- coding: utf-8 -*-
"""验证: GUI 运行时的引擎连接（GUI 引擎 vs 独立引擎）"""
import sys, json, socket
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r"C:\Users\36078\skills\mcp\yakit-mcp")
from yakit_mcp.engine import YakEngine
from yakit_mcp import grpc_pb2 as ypb

# GUI 在跑，直接连 10053（GUI 引擎）
eng = YakEngine(auto_start=False)  # 不自动启动
print('GUI 引擎 10053 监听:', eng.is_running())
if eng.is_running():
    stub = eng.connect()
    print('版本:', eng.version())
    # 查历史（GUI引擎数据库是开的）
    resp = stub.QueryHistoryHTTPFuzzerTask(ypb.Empty())
    print('历史任务数:', len(list(resp.Tasks if resp.Tasks else [])))
    # 清空试试
    from yakit_mcp.engine import clear_fuzzer_history
    r = clear_fuzzer_history(eng)
    print('清空:', json.dumps(r, ensure_ascii=False))
else:
    print('10053 无监听（GUI 引擎没起来或端口不同）')
    # 看 GUI 引擎端口
    import subprocess
    out = subprocess.run(['netstat', '-ano'], capture_output=True, text=True).stdout
    for line in out.split('\n'):
        if 'LISTENING' in line and '127.0.0.1:100' in line:
            print('  监听:', line.strip())