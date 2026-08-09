# -*- coding: utf-8 -*-
"""yakit-mcp 全功能测试公共框架: 确保引擎就绪（优先 GUI 引擎，否则独立引擎）"""
import sys, os, json, time, os, subprocess, socket

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "yakit_mcp"))


def ensure_engine(timeout=40):
    """返回 (engine, gui_alive)。引擎优先复用 GUI 的，否则启动独立引擎。"""
    from yakit_mcp.server import yakit_status, get_engine
    # 1) 等 GUI 引擎（如果 GUI 在跑）
    gui_alive = False
    for i in range(int(timeout / 2)):
        time.sleep(2)
        try:
            st = json.loads(yakit_status())
            if st.get("engine_running"):
                gui_alive = st.get("gui_running", False)
                return get_engine(), gui_alive
        except Exception:
            pass
    # 2) 启动独立引擎
    engine = get_engine()
    try:
        ok = engine.start(timeout=40)
        if ok:
            return engine, False
    except Exception as e:
        pass
    # 3) 最终探测
    from yakit_mcp.engine import YakEngine, DEFAULT_HOST
    for port in (9011, 10053, 8087):
        try:
            s = socket.socket(); s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                s.close()
                e = YakEngine(DEFAULT_HOST, port, auto_start=False)
                try:
                    e.connect()
                    return e, False
                except Exception:
                    pass
            s.close()
        except Exception:
            pass
    raise RuntimeError("引擎不可用")


def p(title, obj):
    print(f"\n===== {title} =====")
    if isinstance(obj, str):
        print(obj)
    else:
        print(json.dumps(obj, ensure_ascii=False, indent=2)[:1500])