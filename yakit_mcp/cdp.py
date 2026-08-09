# -*- coding: utf-8 -*-
"""
yakit-mcp CDP 控制模块: 通过 Chrome DevTools Protocol 控制 Yakit GUI
（Electron 应用，启动时带 --remote-debugging-port）
实现: 打开 Web Fuzzer 页面 / 页面截图 / 执行 JS
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import base64
import io
from datetime import datetime

from PIL import Image

CDP_PORT_DEFAULT = 9333


def _load_websocket():
    try:
        import websocket  # noqa
        return websocket
    except ImportError:
        raise RuntimeError("缺少 websocket-client，请执行: pip install websocket-client")


def launch_gui_with_cdp(gui_path: str, port: int = CDP_PORT_DEFAULT) -> bool:
    """以 CDP 模式启动 Yakit GUI（若已在运行则复用）"""
    if cdp_ready(port, timeout=2):
        return True
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen([gui_path, f"--remote-debugging-port={port}", "--remote-allow-origins=*"],
                     creationflags=flags, close_fds=True)
    return cdp_ready(port, timeout=30)


def cdp_ready(port: int, timeout: float = 5) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
                return bool(json.loads(r.read()))
        except Exception:
            time.sleep(0.4)
    return False


def list_pages(port: int = CDP_PORT_DEFAULT) -> list[dict]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=3) as r:
            return json.loads(r.read())
    except Exception:
        return []


def _find_main_page(port: int) -> dict | None:
    for p in list_pages(port):
        url = p.get("url", "")
        if "main/index.html" in url:
            return p
    return None


def _rpc(ws, method: str, params: dict | None = None, msg_id: list | None = None) -> dict:
    mid = (msg_id[0] if msg_id else 0) + 1
    if msg_id:
        msg_id[0] = mid
    ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    while True:
        resp = json.loads(ws.recv())
        if resp.get("id") == mid:
            return resp


def _eval(ws, expression: str, msg_id: list) -> dict:
    r = _rpc(ws, "Runtime.evaluate", {
        "expression": expression,
        "returnByValue": True,
        "awaitPromise": True,
    }, msg_id)
    return r.get("result", {}).get("result", {}).get("value")


def cdp_set_https_switch(port: int = CDP_PORT_DEFAULT, force_https: bool | None = None) -> dict:
    """
    通过 CDP 设置 Web Fuzzer 页面的"强制 HTTPS"开关（GUI 勾选状态）
    返回: {ok, current_checked, set_to, reason}
    force_https=None 时只读取状态
    """
    if not cdp_ready(port, timeout=3):
        return {"ok": False, "reason": "CDP 不可用"}
    main = _find_main_page(port)
    if not main:
        return {"ok": False, "reason": "无主页面"}
    websocket = _load_websocket()
    ws = websocket.create_connection(main["webSocketDebuggerUrl"], timeout=15)
    msg_id = [0]
    try:
        _rpc(ws, "Runtime.enable", {}, msg_id)
        # 读取开关状态
        state = _eval(ws, """(() => {
            const label = [...document.querySelectorAll('label')].find(e => e.textContent.trim() === '强制 HTTPS');
            if (!label) return null;
            let item = label;
            for (let i = 0; i < 6 && item; i++) {
                const sw = item.querySelector('.ant-switch');
                if (sw) return sw.getAttribute('aria-checked') === 'true';
                item = item.parentElement;
            }
            return null;
        })()""", msg_id)
        if state is None:
            ws.close()
            return {"ok": True, "changed": False, "reason": "未找到 强制 HTTPS 开关（可能不在 Web Fuzzer 页面）"}

        changed = False
        if force_https is not None and bool(state) != force_https:
            # 点击切换
            _eval(ws, """(() => {
                const label = [...document.querySelectorAll('label')].find(e => e.textContent.trim() === '强制 HTTPS');
                let item = label;
                for (let i = 0; i < 6 && item; i++) {
                    const sw = item.querySelector('.ant-switch');
                    if (sw) { sw.click(); return 'ok'; }
                    item = item.parentElement;
                }
                return 'nf';
            })()""", msg_id)
            changed = True
        ws.close()
        return {"ok": True, "changed": changed, "before": bool(state), "after": force_https if force_https is not None else bool(state)}
    except Exception as e:
        try:
            ws.close()
        except Exception:
            pass
        return {"ok": False, "reason": repr(e)}


def cdp_new_webfuzzer_tab(port: int = CDP_PORT_DEFAULT) -> dict:
    """
    通过 CDP 点击 Web Fuzzer 标签栏的 "+" 按钮，新开一个干净的 Web Fuzzer tab。
    Yakit 的 Web Fuzzer 多实例 tab 栏在主导航区（MainOperatorContent_tab-menu-sub-body），
    数字 tab（如 123456）右侧有 "+" 新增按钮。
    返回: {ok, clicked, reason}
    """
    if not cdp_ready(port, timeout=3):
        return {"ok": False, "reason": "CDP 不可用"}
    main = _find_main_page(port)
    if not main:
        return {"ok": False, "reason": "无主页面"}
    websocket = _load_websocket()
    ws = websocket.create_connection(main["webSocketDebuggerUrl"], timeout=15)
    msg_id = [0]
    try:
        _rpc(ws, "Runtime.enable", {}, msg_id)
        # 找数字 tab 容器里的 + 按钮
        result = _eval(ws, """(() => {
            // 方式1: 找数字 tab（123456 样式），在其祖先容器内找 +
            const six = [...document.querySelectorAll('*')].find(e => {
                const t = e.textContent.trim();
                return /^\\d{4,}$/.test(t) && e.children.length === 0;
            });
            if (six) {
                let c = six.parentElement;
                for (let i = 0; i < 6 && c; i++) {
                    const plus = [...c.querySelectorAll('*')].find(e => {
                        const t = (e.textContent || '').trim();
                        const cls = (e.className || '').toString();
                        return (t === '+' || t === '＋') && e.children.length === 0
                            || /(^|\\s)(plus|add)(\\s|$)/i.test(cls);
                    });
                    if (plus) { plus.click(); return 'clicked plus near numeric tab'; }
                    c = c.parentElement;
                }
            }
            // 方式2: 主导航 tab 容器里的 + / plus 图标
            const tabbar = document.querySelector('[class*=tab-menu-sub-body], [class*=tab-menu-sub]');
            if (tabbar) {
                const plus = [...tabbar.querySelectorAll('*')].find(e => {
                    const t = (e.textContent || '').trim();
                    const cls = (e.className || '').toString();
                    return (t === '+' || t === '＋') && e.children.length === 0
                        || /anticon-plus/.test(cls) || /(^|\\s)plus(\\s|$)/i.test(cls);
                });
                if (plus) { (plus.closest('button,div,span') || plus).click(); return 'clicked plus in tab bar'; }
            }
            // 方式3: 全局 anticon-plus 图标
            const icon = document.querySelector('.anticon-plus');
            if (icon) { (icon.closest('button, div, span') || icon).click(); return 'clicked global plus icon'; }
            return 'no plus found';
        })()""", msg_id)
        time.sleep(1.5)
        ws.close()
        return {"ok": bool(result) and 'clicked' in str(result), "clicked": str(result)}
    except Exception as e:
        try:
            ws.close()
        except Exception:
            pass
        return {"ok": False, "reason": repr(e)}


def cdp_close_webfuzzer_tab(port: int = CDP_PORT_DEFAULT, tab_text: str = "") -> dict:
    """
    通过 CDP 关闭 Web Fuzzer tab（点 × 关闭按钮），防止窗口增多卡顿。
    tab_text: 指定关闭的 tab 文本（如 "123456"）；空则关闭当前活动的 tab。
    返回: {ok, closed, reason}
    """
    if not cdp_ready(port, timeout=3):
        return {"ok": False, "reason": "CDP 不可用"}
    main = _find_main_page(port)
    if not main:
        return {"ok": False, "reason": "无主页面"}
    websocket = _load_websocket()
    ws = websocket.create_connection(main["webSocketDebuggerUrl"], timeout=15)
    msg_id = [0]
    try:
        _rpc(ws, "Runtime.enable", {}, msg_id)
        # 找 tab 上的关闭按钮并点击
        result = _eval(ws, """(() => {
            // 方式1: 数字 tab（如 123456）附近的关闭按钮（anticon-close / CloseOutlined）
            const tabTarget = %s;
            const six = tabTarget
                ? [...document.querySelectorAll('*')].find(e => e.textContent.trim() === tabTarget && e.children.length === 0)
                : null;
            // 找 tab 容器
            let container = null;
            if (six) {
                container = six.parentElement;
                for (let i = 0; i < 5 && container; i++) {
                    const close = [...container.querySelectorAll('*')].find(e => {
                        const cls = (e.className || '').toString();
                        return /anticon-close|close/i.test(cls) && e.children.length === 0;
                    });
                    if (close) { close.click(); return 'clicked close btn for tab'; }
                    container = container.parentElement;
                }
            }
            // 方式2: 任意 tab 容器内的关闭按钮（如果只有一个 tab，关它）
            const tabbar = document.querySelector('[class*=tab-menu-sub-body], [class*=tab-menu-sub]');
            if (tabbar) {
                const close = [...tabbar.querySelectorAll('*')].find(e => {
                    const cls = (e.className || '').toString();
                    return /anticon-close|close/i.test(cls) && e.children.length === 0;
                });
                if (close) { close.click(); return 'clicked close in tab bar'; }
            }
            // 方式3: 按钮含 × 文本
            const xbtns = [...document.querySelectorAll('span, i, button')].filter(e => {
                const t = e.textContent.trim();
                return t === '×' || t === 'x' || t === '✕' || t === '✖';
            });
            if (xbtns.length) { xbtns[0].click(); return 'clicked x btn'; }
            return 'no close btn found';
        })()""" % (repr(tab_text) if tab_text else "null"), msg_id)
        time.sleep(1.5)
        ws.close()
        return {"ok": bool(result) and 'clicked' in str(result), "closed": str(result)}
    except Exception as e:
        try:
            ws.close()
        except Exception:
            pass
        return {"ok": False, "reason": repr(e)}


def cdp_fill_and_send(port: int = CDP_PORT_DEFAULT, packet: str = "", force_https: bool | None = None) -> dict:
    """
    通过 CDP 在 Web Fuzzer 编辑器填入请求包并点击"发送请求"。
    返回: {ok, filled, sent, editor_head}
    """
    if not cdp_ready(port, timeout=3):
        return {"ok": False, "reason": "CDP 不可用"}
    main = _find_main_page(port)
    if not main:
        return {"ok": False, "reason": "无主页面"}
    websocket = _load_websocket()
    ws = websocket.create_connection(main["webSocketDebuggerUrl"], timeout=15)
    msg_id = [0]
    try:
        _rpc(ws, "Runtime.enable", {}, msg_id)
        if force_https is not None:
            cdp_set_https_switch(port, force_https=force_https)
        # 聚焦 Monaco 编辑器
        _eval(ws, """(() => {
            const ed = document.querySelector('.monaco-editor');
            if (ed) {
                const r = ed.getBoundingClientRect();
                const opts = {bubbles: true, cancelable: true, clientX: r.left + 80, clientY: r.top + 40};
                ed.dispatchEvent(new MouseEvent('mousedown', opts));
                ed.dispatchEvent(new MouseEvent('mouseup', opts));
            }
        })()""", msg_id)
        time.sleep(0.5)
        # 填入请求（Input.insertText 模拟键盘输入）
        _rpc(ws, "Input.insertText", {"text": packet}, msg_id)
        time.sleep(1.5)
        # 读渲染内容确认
        head = _eval(ws, """(() => {
            const ls = [...document.querySelectorAll('.view-line')];
            return ls.length ? JSON.stringify(ls.slice(0, 3).map(l => l.textContent)) : 'no-editor';
        })()""", msg_id)
        # 点击发送
        sent = _eval(ws, """(() => {
            const all = [...document.querySelectorAll('button')];
            const t = all.find(e => {
                const t = e.textContent.trim();
                return t.startsWith('发送请求') && !t.startsWith('暂停');
            });
            if (t) { t.click(); return 'clicked'; }
            return 'nf';
        })()""", msg_id)
        ws.close()
        return {"ok": True, "filled": True, "sent": str(sent), "editor_head": str(head)}
    except Exception as e:
        try:
            ws.close()
        except Exception:
            pass
        return {"ok": False, "reason": repr(e)}


def cdp_click_send_and_wait(port: int = CDP_PORT_DEFAULT, wait_seconds: int = 8) -> dict:
    """
    通过 CDP 点击 Web Fuzzer 页面【可见的】"发送请求"按钮，等待响应。
    （过滤隐藏按钮——多 tab 页面有多个发送按钮，只有当前活动 tab 的可见）
    返回: {ok, clicked, response_found}
    """
    if not cdp_ready(port, timeout=3):
        return {"ok": False, "reason": "CDP 不可用"}
    main = _find_main_page(port)
    if not main:
        return {"ok": False, "reason": "无主页面"}
    websocket = _load_websocket()
    ws = websocket.create_connection(main["webSocketDebuggerUrl"], timeout=15)
    msg_id = [0]
    try:
        _rpc(ws, "Runtime.enable", {}, msg_id)
        clicked = _eval(ws, """(() => {
            const all = [...document.querySelectorAll('button')];
            const t = all.find(e => {
                const r = e.getBoundingClientRect();
                const t2 = e.textContent.trim();
                return t2.startsWith('发送请求') && !t2.startsWith('暂停')
                    && r.width > 0 && r.top > 0 && r.top < 900;
            });
            if (t) { t.click(); return 'clicked:' + t.textContent.trim(); }
            return 'nf';
        })()""", msg_id)
        time.sleep(wait_seconds)
        # 切"响应"tab（如果存在）
        _eval(ws, """(() => {
            const all = [...document.querySelectorAll('*')].filter(e => e.children.length === 0);
            const cand = all.find(e => {
                const t = e.textContent.trim();
                return (t === '响应' || t === 'Response' || t === '原文') && e.offsetParent !== null;
            });
            if (cand) { cand.click(); return 'ok'; }
            return 'nf';
        })()""", msg_id)
        time.sleep(1.5)
        # 检测响应
        resp = _eval(ws, """(() => {
            const t = document.body.innerText;
            return t.includes('HTTP/1.1') || t.includes('HTTP/2') ? 'yes' : 'no';
        })()""", msg_id)
        ws.close()
        return {"ok": True, "clicked": str(clicked), "response_found": str(resp) == 'yes'}
    except Exception as e:
        try:
            ws.close()
        except Exception:
            pass
        return {"ok": False, "reason": repr(e)}


def cdp_send_to_tab(port: int = CDP_PORT_DEFAULT, packet: str = "", is_https: bool = False, open_flag: bool = True) -> dict:
    """
    【终极方案】通过 CDP 在 Yakit 渲染进程执行 ipcRenderer.invoke('send-to-tab')，
    触发前端官方逻辑新开 Web Fuzzer tab 并填入请求（源码: HTTPFuzzerPage.tsx:710 +
    communication.js send-to-tab → fetch-send-to-tab → MainOperatorContent addFuzzer）。
    绕开 Monaco 填包，新 tab 干净无旧内容。
    """
    if not cdp_ready(port, timeout=3):
        return {"ok": False, "reason": "CDP 不可用"}
    main = _find_main_page(port)
    if not main:
        return {"ok": False, "reason": "无主页面"}
    websocket = _load_websocket()
    ws = websocket.create_connection(main["webSocketDebuggerUrl"], timeout=15)
    msg_id = [0]
    try:
        _rpc(ws, "Runtime.enable", {}, msg_id)
        # 构造 JS: 用 window.require('electron').ipcRenderer.invoke('send-to-tab')
        js_req = json.dumps(packet, ensure_ascii=False)
        js = f"""(async () => {{
            const REQ = {js_req};
            const params = {{type: 'fuzzer', data: {{isHttps: {'true' if is_https else 'false'}, request: REQ, openFlag: {'true' if open_flag else 'false'}}}}};
            try {{
                if (window.require) {{
                    const ipc = window.require('electron').ipcRenderer;
                    if (ipc && ipc.invoke) {{
                        await ipc.invoke('send-to-tab', params);
                        return 'ok';
                    }}
                    return 'no-invoke';
                }}
                return 'no-require';
            }} catch (e) {{ return 'ERR: ' + e.message; }}
        }})()"""
        result = _eval(ws, js, msg_id)
        time.sleep(2)
        ws.close()
        return {"ok": str(result) == "ok", "result": str(result)}
    except Exception as e:
        try:
            ws.close()
        except Exception:
            pass
        return {"ok": False, "reason": repr(e)}


def open_webfuzzer(port: int = CDP_PORT_DEFAULT, gui_path: str = "") -> dict:
    """
    用 CDP 打开 Yakit GUI 的 Web Fuzzer 页面
    流程: 连接主页面 → 关闭所有弹窗 → 点击 Web Fuzzer 导航
    返回: {ok, reason, clicked, pages}
    """
    if not cdp_ready(port, timeout=3):
        if gui_path and Path(gui_path).exists():
            if not launch_gui_with_cdp(gui_path, port):
                return {"ok": False, "reason": "GUI CDP 启动失败"}
        else:
            return {"ok": False, "reason": f"CDP {port} 不可用且未提供 GUI 路径"}

    main = _find_main_page(port)
    if not main:
        return {"ok": False, "reason": "未找到主页面（可能还在加载）"}

    websocket = _load_websocket()
    ws = websocket.create_connection(main["webSocketDebuggerUrl"], timeout=15)
    msg_id = [0]
    try:
        _rpc(ws, "Runtime.enable", {}, msg_id)
        _rpc(ws, "Page.enable", {}, msg_id)

        # 1) 等页面加载（body 有内容）
        for _ in range(20):
            v = _eval(ws, "document.body ? document.body.innerText.length : -1", msg_id)
            if isinstance(v, int) and v > 100:
                break
            time.sleep(1)

        # 2) 循环关闭弹窗（项目管理/升级提示等），直到出现主界面导航
        dialog_labels = ["进入项目", "进入", "确 定", "确定", "暂 不", "暂不", "取 消", "取消", "关 闭", "关闭", "×"]
        nav_keywords = ["Web Fuzzer", "首页", "流量记录", "MITM", "端口扫描"]
        closed_rounds = 0
        for _ in range(10):
            texts = _eval(ws, """(() => {
                const all = [...document.querySelectorAll('*')].filter(e => e.children.length === 0);
                const texts = all.map(e => e.textContent.trim()).filter(t => t && t.length < 25);
                return JSON.stringify([...new Set(texts)]);
            })()""", msg_id) or "[]"
            if any(k in texts for k in nav_keywords):
                break
            clicked = False
            for label in dialog_labels:
                r = _eval(ws, f"""(() => {{
                    const all = [...document.querySelectorAll('button, [role=button], [class*=btn], [class*=Button], span, div, a')];
                    const t = all.find(e => e.textContent.trim() === '{label}' && e.children.length === 0);
                    if (t) {{ t.click(); return 'ok'; }}
                    return null;
                }})()""", msg_id)
                if r:
                    clicked = True
                    break
            if not clicked:
                break
            closed_rounds += 1
            time.sleep(1)

        # 3) 点击 Web Fuzzer 导航
        clicked_nav = _eval(ws, """(() => {
            const keywords = ['Web Fuzzer', 'WEB FUZZER', 'webfuzzer'];
            const all = [...document.querySelectorAll('*')].filter(e => e.children.length === 0);
            for (const kw of keywords) {
                const t = all.find(e => (e.textContent.trim()).toLowerCase() === kw.toLowerCase());
                if (t) { t.click(); return kw; }
            }
            const any = [...document.querySelectorAll('*')].find(e => e.textContent.includes('Web Fuzzer') && e.children.length < 5);
            if (any) { any.click(); return 'fuzzy'; }
            return '';
        })()""", msg_id)
        time.sleep(2)

        ws.close()
        return {
            "ok": True,
            "clicked": clicked_nav or "",
            "closed_dialogs": closed_rounds,
            "pages": [p.get("url") for p in list_pages(port)],
        }
    except Exception as e:
        ws.close()
        return {"ok": False, "reason": repr(e)}


def cdp_screenshot(port: int = CDP_PORT_DEFAULT, output_dir: str = "") -> dict:
    """
    用 CDP Page.captureScreenshot 截取 Yakit GUI 当前页面
    返回: {ok, image_base64, saved_path}
    """
    main = _find_main_page(port)
    if not main:
        return {"ok": False, "reason": "未找到主页面"}

    websocket = _load_websocket()
    ws = websocket.create_connection(main["webSocketDebuggerUrl"], timeout=15)
    msg_id = [0]
    try:
        r = _rpc(ws, "Page.captureScreenshot", {"format": "png"}, msg_id)
        if "data" not in r.get("result", {}):
            return {"ok": False, "reason": "截图失败: " + json.dumps(r.get("result", {}))[:200]}
        b64 = r["result"]["data"]
        img = Image.open(io.BytesIO(base64.b64decode(b64)))

        saved = ""
        if output_dir:
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            saved = str(out / f"yakit_cdp_{ts}.png")
            img.save(saved, format="PNG")
        ws.close()
        return {
            "ok": True,
            "image_base64": b64,
            "saved_path": saved,
            "size": img.size,
            "mime": "image/png",
            "mode": "cdp",
        }
    except Exception as e:
        ws.close()
        return {"ok": False, "reason": repr(e)}
