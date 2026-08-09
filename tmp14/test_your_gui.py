# -*- coding: utf-8 -*-
"""连你的 GUI 引擎(9011) → 认证 → 推送官方通道 tab"""
import sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r"C:\Users\36078\skills\mcp\yakit-mcp")
from yakit_mcp.engine import YakEngine, push_webfuzzer_tab

eng = YakEngine(auto_start=False)
eng.port=9011
eng.host="127.0.0.1"
print('9011 监听:', eng.is_running())
if not eng.is_running():
    print('引擎不在 9011'); sys.exit(1)
eng.port = 9011

# 抓密码 + 连接
pwd = eng._grab_engine_password()
print('抓密码:', 'OK' if pwd else '失败(无密码)')
try:
    v = eng.version()
    print('版本:', v, '(认证OK)')
except Exception as e:
    print('认证失败:', repr(e)[:200])
    sys.exit(1)

# 清空历史（你的 GUI 数据库）
from yakit_mcp.engine import clear_fuzzer_history
cl = clear_fuzzer_history(eng)
print('清历史:', json.dumps(cl, ensure_ascii=False)[:150])

# 推送官方通道 tab
PKT = """GET /get?hello=world&from=mcp HTTP/1.1
Host: httpbin.org
User-Agent: yakit-mcp-test

"""
r = push_webfuzzer_tab(eng, PKT, is_https=False, tab_name="MCP测试")
print('推送:', json.dumps({k: v for k, v in r.items() if k != 'payload'}, ensure_ascii=False))

# 再重放一下确认引擎工作
from yakit_mcp.engine import replay_packet
rr = replay_packet(eng, PKT, is_https=False)
print('重放:', rr.get('ok'), rr.get('status_code'), rr.get('url'))