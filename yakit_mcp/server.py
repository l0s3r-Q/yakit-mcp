# -*- coding: utf-8 -*-
"""
yakit-mcp: Yakit 重放 + GUI 联动 + 截图 MCP Server

工具:
  yakit_status                 - 检查引擎/GUI 状态
  yakit_replay                 - 重放单个 HTTP 包（返回响应 + 入库 GUI 可见 + 可选截图）
  yakit_replay_batch           - 批量重放多个包
  yakit_capture                - 截取 Yakit 窗口画面（返回图片 + 存文件）
  yakit_query_flows            - 查询历史 HTTP 流量
  yakit_parse_packet           - 解析 Burp/Yakit 复制的 HTTP 报文
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# 让 yakit_mcp 包可导入（兼容: python -m yakit_mcp.server 和 python server.py 两种启动）
_PKG_DIR = str(Path(__file__).parent)          # .../yakit_mcp/
_PARENT_DIR = str(Path(__file__).parent.parent)  # .../yakit-mcp/
for _p in (_PKG_DIR, _PARENT_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import yakit_mcp.grpc_pb2 as ypb
from mcp.server.fastmcp import FastMCP
from yakit_mcp.capture import capture_window, capture_window_clean
from yakit_mcp.cdp import (
    cdp_click_send_and_wait,
    cdp_close_webfuzzer_tab,
    cdp_fill_and_send,
    cdp_new_webfuzzer_tab,
    cdp_ready,
    cdp_screenshot,
    cdp_send_to_tab,
    cdp_set_https_switch,
    launch_gui_with_cdp,
    open_webfuzzer,
)
from yakit_mcp.engine import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    YakEngine,
    basic_crawler,
    brute_types,
    clear_fuzzer_history,
    delete_fuzzer_label,
    find_yakit_engine,
    find_yakit_gui,
    list_fuzzer_history,
    list_fuzzer_labels,
    mitm_start,
    mitm_status,
    mitm_stop,
    parse_http_packet,
    port_scan,
    push_webfuzzer_tab,
    query_domains,
    query_http_flows,
    query_hosts,
    query_mitm_flows,
    query_ports,
    query_risks,
    replay_packet,
    save_fuzzer_label,
    simple_detect,
    start_brute,
)

mcp = FastMCP("yakit-mcp")

# 全局引擎单例
_engine: YakEngine | None = None


def get_engine() -> YakEngine:
    global _engine
    if _engine is None:
        _engine = YakEngine(
            host=os.environ.get("YAKIT_HOST", DEFAULT_HOST),
            port=int(os.environ.get("YAKIT_PORT", str(DEFAULT_PORT))),
        )
    return _engine


def _default_output_dir() -> str:
    return str(Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "yakit-mcp" / "screenshots")


# ---------------------------------------------------------------------------
# 工具 1: 状态检查
# ---------------------------------------------------------------------------
@mcp.tool()
def yakit_status() -> str:
    """检查 Yakit 引擎与 GUI 状态。返回引擎版本、是否运行、GUI 是否可找到。"""
    engine = get_engine()
    engine_running = engine.is_running()
    gui_path = find_yakit_gui()
    engine_path = find_yakit_engine()
    version = ""
    if engine_running:
        try:
            version = engine.version()
        except Exception:
            version = "?"
    return json.dumps({
        "engine_running": engine_running,
        "engine_version": version,
        "engine_path": engine_path or "",
        "gui_path": gui_path or "",
        "gui_running": _is_gui_running(),
        "endpoint": f"{engine.host}:{engine.port}",
    }, ensure_ascii=False, indent=2)


def _is_gui_running() -> bool:
    try:
        import subprocess
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Yakit.exe"],
            capture_output=True, text=True, timeout=5,
        )
        return "Yakit.exe" in r.stdout
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 工具 2: 解析报文
# ---------------------------------------------------------------------------
@mcp.tool()
def yakit_parse_packet(packet: str) -> str:
    """
    解析原始 HTTP 报文文本（Burp Repeater 复制 / Yakit 复制的包）。
    返回 method/path/host/headers/body/scheme 等结构化信息。
    参数:
      packet: 原始 HTTP 报文（含请求行、Headers、空行、Body）
    """
    try:
        info = parse_http_packet(packet)
        info.pop("request", None)
        return json.dumps(info, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "reason": str(e)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 工具 3: 重放单个包
# ---------------------------------------------------------------------------
@mcp.tool()
def yakit_replay(
    packet: str,
    is_https: bool = False,
    auto_protocol: bool = True,
    try_both: bool = False,
    sync_gui_https: bool = True,
    proxy: str = "",
    timeout: float = 30.0,
    no_follow_redirect: bool = False,
    save_to_gui: bool = True,
    capture: bool = False,
    capture_title: str = "Yakit",
    capture_output_dir: str = "",
    wait_gui_seconds: float = 2.0,
) -> str:
    """
    用 Yakit 引擎重放一个 HTTP 包（等价于 Web Fuzzer 发包）。
    返回: 状态码/响应头/响应体/耗时/任务ID。
    若 save_to_gui=True: 请求/响应写入 Yakit 数据库，GUI 的 Web Fuzzer 历史与流量记录中可见。
    若 capture=True: 重放后截取 Yakit GUI 窗口画面，返回 base64 图片 + 保存 PNG 文件。

    参数:
      packet: 原始 HTTP 报文文本（Burp 复制的包）
      is_https: 是否 HTTPS（默认 False；auto_protocol 会覆盖判断）
      auto_protocol: 自动识别协议（默认 True）——Host 带 :443/path 是 https:// 判 https；
                     Host 带 :80/path 是 http:// 判 http；无法判断时用 is_https 参数兜底
      try_both: 自动识别为 unknown 时，http 和 https 各发一次（默认 False）。
                推荐 True：HTTPS 站点抓的 Burp 包往往看不出协议，双试最稳
      proxy: 代理地址，如 "http://127.0.0.1:8080"
      timeout: 单请求超时秒数（默认 30）
      no_follow_redirect: 不跟随 302/301 重定向
      save_to_gui: 是否写入 Yakit GUI 可见的流量库（默认 True）
      capture: 是否截取 Yakit 窗口画面（默认 False）
      capture_title: 截图匹配的窗口标题（默认 "Yakit"）
      capture_output_dir: 截图保存目录（默认 %LOCALAPPDATA%/yakit-mcp/screenshots）
      wait_gui_seconds: 截图前等待秒数，让 GUI 刷新历史列表（默认 2）
    """
    engine = get_engine()
    result = {}
    try:
        from .engine import detect_protocol
        hint = detect_protocol(packet)
        result["protocol_detected"] = hint
        result["protocol_used"] = []

        # 协议决策
        if is_https:
            effective_https = True
        elif auto_protocol and hint in ("https", "http"):
            effective_https = (hint == "https")
        elif auto_protocol and hint == "unknown" and try_both:
            effective_https = None  # 双试
        else:
            effective_https = is_https

        # 双协议尝试
        if effective_https is None:
            attempts = [False, True]
        else:
            attempts = [effective_https]
        attempt_items = []
        for https in attempts:
            # 同步 GUI 强制 HTTPS 开关（若 CDP 可用）
            if sync_gui_https and cdp_ready(9333, timeout=1):
                try:
                    cdp_set_https_switch(9333, force_https=https)
                except Exception:
                    pass
            replay_result = replay_packet(
                engine, packet,
                is_https=https,
                proxy=proxy,
                timeout=timeout,
                no_follow_redirect=no_follow_redirect,
                return_raw=True,
            )
            item = {k: v for k, v in replay_result.items() if k != "raw_response"}
            item["protocol"] = "https" if https else "http"
            attempt_items.append(item)
            if save_to_gui and replay_result.get("ok"):
                from .engine import convert_to_httpflow
                flow = convert_to_httpflow(engine, replay_result["raw_response"])
                item["gui_visible"] = flow.get("ok", False)
                item["flow"] = flow
        result["attempts"] = attempt_items
        # 取第一个成功的作为主结果
        ok_items = [x for x in attempt_items if x.get("ok")]
        if ok_items:
            result.update({k: v for k, v in ok_items[0].items() if k not in ("gui_visible", "flow")})
            result["gui_visible"] = ok_items[0].get("gui_visible", False)
            result["flow"] = ok_items[0].get("flow")
            result["ok"] = True
            result["selected_protocol"] = ok_items[0]["protocol"]
        else:
            result["ok"] = False
            result["reason"] = "所有协议尝试均失败: " + "; ".join(str(x.get("reason", "")) for x in attempt_items)
    except Exception as e:
        result["ok"] = False
        result["reason"] = repr(e)

    # 截图
    if capture:
        if wait_gui_seconds > 0:
            import time
            time.sleep(wait_gui_seconds)
        out_dir = capture_output_dir or _default_output_dir()
        # 0) CDP send-to-tab 官方前端通道（新开干净 tab + 填请求）
        st = {"ok": False}
        if cdp_ready(9333, timeout=2):
            try:
                st = cdp_send_to_tab(9333, packet=packet,
                                     is_https=(result.get("selected_protocol") == "https"))
                result["send_to_tab"] = st
            except Exception:
                result["send_to_tab"] = {"ok": False}
        time.sleep(2)
        # 1) CDP 全自动: 打开 Web Fuzzer 页面 + 点击可见发送按钮等待响应 + 页面级截图
        if cdp_ready(9333, timeout=2):
            from .engine import find_yakit_gui
            gui = find_yakit_gui() or ""
            ow = open_webfuzzer(gui_path=gui)
            time.sleep(1)
            # 点【可见】发送按钮 + 等响应 + 切响应tab
            send_r = cdp_click_send_and_wait(9333, wait_seconds=6)
            result["send_click"] = send_r
            time.sleep(1)
            cap = cdp_screenshot(9333, output_dir=out_dir)
            if cap.get("ok"):
                cap["webfuzzer_opened"] = ow.get("clicked", "")
                cap["send_clicked"] = send_r.get("clicked", "")
                cap["response_found"] = send_r.get("response_found", False)
                result["capture"] = cap
                # 重放完成后自动关闭新开的 tab，防止窗口堆积卡顿
                if result.get("send_to_tab", {}).get("ok") or st.get("ok"):
                    try:
                        cl = cdp_close_webfuzzer_tab(9333)
                        result["tab_closed"] = cl
                    except Exception:
                        result["tab_closed"] = {"ok": False}
                return json.dumps(result, ensure_ascii=False, indent=2, default=str)
        # 2) PrintWindow 窗口截图（无视遮挡）
        cap = capture_window_clean(capture_title, output_dir=out_dir, timeout=8.0)
        if cap.get("ok"):
            result["capture"] = cap
        else:
            # 3) GUI 不可见 → 渲染响应视图（保证截图链路可用）
            from .render import render_and_save
            view = render_and_save(result, out_dir)
            result["capture"] = view
            result["capture"]["fallback_reason"] = cap.get("reason", "Yakit GUI 窗口不可见")

    return json.dumps(result, ensure_ascii=False, indent=2, default=str)


# ---------------------------------------------------------------------------
# 工具 4: 批量重放
# ---------------------------------------------------------------------------
@mcp.tool()
def yakit_replay_batch(
    packets: str,
    is_https: bool = False,
    timeout: float = 30.0,
    concurrency: int = 1,
) -> str:
    """
    批量重放多个 HTTP 包（JSON 数组字符串）。
    参数:
      packets: JSON 数组，如 ["GET /a HTTP/1.1\\r\\nHost: x\\r\\n\\r\\n", "POST /b ..."]
      is_https: 是否 HTTPS
      timeout: 单请求超时（默认 30）
      concurrency: 并发数（默认 1，引擎自动并发，建议 1-5）
    """
    engine = get_engine()
    try:
        items = json.loads(packets)
        if not isinstance(items, list):
            return json.dumps({"ok": False, "reason": "packets 必须是 JSON 数组"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"ok": False, "reason": f"packets 解析失败: {e}"}, ensure_ascii=False)

    results = []
    for i, pkt in enumerate(items[:50]):
        try:
            r = replay_packet(engine, pkt, is_https=is_https if is_https else None, timeout=timeout)
            results.append({
                "index": i,
                "ok": r.get("ok"),
                "status_code": r.get("status_code"),
                "url": r.get("url"),
                "duration_ms": r.get("duration_ms"),
                "reason": r.get("reason", ""),
            })
        except Exception as e:
            results.append({"index": i, "ok": False, "reason": repr(e)})

    ok_count = sum(1 for r in results if r.get("ok"))
    return json.dumps({
        "ok": True,
        "total": len(results),
        "success": ok_count,
        "failed": len(results) - ok_count,
        "results": results,
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 工具 5: 截图
# ---------------------------------------------------------------------------
@mcp.tool()
def yakit_capture(
    window_title: str = "Yakit",
    output_dir: str = "",
    timeout: float = 10.0,
    prefer_cdp: bool = True,
) -> str:
    """
    截取 Yakit GUI 画面。返回 base64 图片（Agent 可见）+ 保存 PNG 文件（供文档使用）。
    优先级: CDP 截图（Electron 页面级，最清晰）→ PrintWindow 窗口截图 → 渲染视图。
    参数:
      window_title: 窗口标题包含此关键词（默认 "Yakit"）
      output_dir: 截图保存目录（默认 %LOCALAPPDATA%/yakit-mcp/screenshots）
      timeout: 等待窗口出现的秒数（默认 10）
      prefer_cdp: 优先尝试 CDP 截图（默认 True）
    """
    out_dir = output_dir or _default_output_dir()

    # 1) CDP 优先
    if prefer_cdp and cdp_ready(9333, timeout=2):
        cap = cdp_screenshot(9333, output_dir=out_dir)
        if cap.get("ok"):
            return json.dumps(cap, ensure_ascii=False)

    # 2) PrintWindow 窗口截图
    cap = capture_window_clean(window_title, output_dir=out_dir, timeout=timeout)
    if not cap.get("ok"):
        return json.dumps(cap, ensure_ascii=False)
    return json.dumps({
        "ok": True,
        "saved_path": cap.get("saved_path", ""),
        "rect": cap.get("rect"),
        "window_title": cap.get("title", ""),
        "image_size": cap.get("size"),
        "image_base64": cap.get("image_base64", ""),
        "mime": "image/png",
        "mode": cap.get("mode", "window"),
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 工具 5.5: 打开 Web Fuzzer（CDP）
# ---------------------------------------------------------------------------
@mcp.tool()
def yakit_open_webfuzzer(launch_gui: bool = True) -> str:
    """
    用 CDP 打开 Yakit GUI 的 Web Fuzzer 页面（让重放结果在界面上显示）。
    前提: Yakit GUI 已以 --remote-debugging-port=9333 启动（或用本工具自动启动）。
    参数:
      launch_gui: 若 CDP 不可用是否自动以 CDP 模式启动 GUI（默认 True）
    """
    from .engine import find_yakit_gui
    gui = find_yakit_gui() or ""
    r = open_webfuzzer(gui_path=gui if launch_gui else "")
    return json.dumps(r, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 工具: 官方通道 - 推送新建 Web Fuzzer Tab（带请求内容）
# ---------------------------------------------------------------------------
@mcp.tool()
def yakit_open_webfuzzer_with_packet(packet: str, is_https: bool = False) -> str:
    """
    【官方通道】通过 gRPC DuplexConnection 推送 web_fuzzer_tab 事件，
    让 GUI 自动新建 Web Fuzzer tab 并填入请求内容（源码确认的 MCP 通道）。
    彻底绕开 Monaco/CDP 填包——新开干净 tab + 请求自动填入，无旧内容残留。

    Yakit 源码 (duplex.tsx): case 'web_fuzzer_tab': emiter.emit('onServerPushOpenWebFuzzerTab', ...)
    // MCP / 后端通知前端新建 Web Fuzzer Tab

    参数:
      packet: 原始 HTTP 请求报文
      is_https: 是否 HTTPS
    返回: {ok, sent, payload}
    """
    engine = get_engine()
    r = push_webfuzzer_tab(engine, packet, is_https)
    return json.dumps(r, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 工具 6: 查询流量
# ---------------------------------------------------------------------------
@mcp.tool()
def yakit_query_flows(keyword: str = "", limit: int = 20) -> str:
    """
    查询 Yakit 引擎中的历史 HTTP 流量记录（GUI 流量列表同源）。
    参数:
      keyword: 关键词过滤（URL/Host 等）
      limit: 返回条数上限（默认 20）
    """
    engine = get_engine()
    r = query_http_flows(engine, keyword=keyword, limit=limit)
    return json.dumps(r, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 工具 7: 清空 Web Fuzzer 历史（解决旧内容残留）
# ---------------------------------------------------------------------------
@mcp.tool()
def yakit_clear_history(task_id: int = 0) -> str:
    """
    清空 Yakit Web Fuzzer 历史任务（数据库层删除）。
    GUI 的"历史 tab 列表"（数字 tab）刷新后旧请求不再显示，解决"旧内容残留"问题。
    参数:
      task_id: 指定任务 id（0 = 删除全部，默认）
    返回: {ok, deleted_all, remaining}
    """
    engine = get_engine()
    r = clear_fuzzer_history(engine, task_id=task_id)
    return json.dumps(r, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 工具 8: 列出 Web Fuzzer 历史任务
# ---------------------------------------------------------------------------
@mcp.tool()
def yakit_list_tasks() -> str:
    """
    列出 Yakit Web Fuzzer 历史任务（GUI 历史 tab 的数据源）。
    返回: 任务 id/host/端口/流量数/成功失败数/创建时间
    """
    engine = get_engine()
    r = list_fuzzer_history(engine)
    return json.dumps(r, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 工具 9/10/11: 分组标签管理
# ---------------------------------------------------------------------------
@mcp.tool()
def yakit_list_labels() -> str:
    """
    列出 Yakit Web Fuzzer 分组标签（如"爆破 ID"“爆破密码"等）。
    返回: 标签 id/名称/描述/hash
    """
    engine = get_engine()
    r = list_fuzzer_labels(engine)
    return json.dumps(r, ensure_ascii=False, indent=2)


@mcp.tool()
def yakit_add_label(label: str, description: str = "") -> str:
    """
    新建 Yakit Web Fuzzer 分组标签。
    参数:
      label: 标签名（如"登录爆破"）
      description: 描述（可选）
    """
    engine = get_engine()
    r = save_fuzzer_label(engine, label, description)
    return json.dumps(r, ensure_ascii=False, indent=2)


@mcp.tool()
def yakit_delete_label(hash_value: str) -> str:
    """
    删除 Yakit Web Fuzzer 分组标签（按 hash 删除）。
    参数:
      hash_value: 标签的 hash（用 yakit_list_labels 查询）
    """
    engine = get_engine()
    r = delete_fuzzer_label(engine, hash_value)
    return json.dumps(r, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# MITM 中间人抓包
# ---------------------------------------------------------------------------
@mcp.tool()
def yakit_mitm_start(port: int = 8083, host: str = "0.0.0.0",
                     include_hostname: str = "", exclude_hostname: str = "") -> str:
    """
    启动 Yakit MITM 中间人抓包监听。
    抓到的 HTTP 流量写入引擎库（SourceType=mitm），用 yakit_mitm_flows 增量获取。
    参数:
      port: 监听端口（默认 8083）
      host: 监听地址（默认 0.0.0.0）
      include_hostname: 只抓这些域名（逗号分隔，空=全部）
      exclude_hostname: 排除这些域名（逗号分隔）
    """
    engine = get_engine()
    filters = {}
    if include_hostname:
        filters["include_hostname"] = [h.strip() for h in include_hostname.split(",") if h.strip()]
    if exclude_hostname:
        filters["exclude_hostname"] = [h.strip() for h in exclude_hostname.split(",") if h.strip()]
    r = mitm_start(engine, port=port, host=host, filters=filters or None)
    return json.dumps(r, ensure_ascii=False, indent=2)


@mcp.tool()
def yakit_mitm_stop(port: int = 8083) -> str:
    """停止 Yakit MITM 监听。"""
    engine = get_engine()
    r = mitm_stop(engine, port=port)
    return json.dumps(r, ensure_ascii=False, indent=2)


@mcp.tool()
def yakit_mitm_status() -> str:
    """查看当前 MITM 监听状态。"""
    engine = get_engine()
    r = mitm_status(engine)
    return json.dumps(r, ensure_ascii=False, indent=2)


@mcp.tool()
def yakit_mitm_flows(after_id: int = 0, limit: int = 50, keyword: str = "") -> str:
    """
    增量获取 MITM 抓到的 HTTP 流量（SourceType=mitm）。
    参数:
      after_id: 只返回 id 大于该值的流量（增量拉取，默认 0=全部）
      limit: 返回条数上限（默认 50）
      keyword: 关键词过滤（URL/Host）
    返回: 每条含 方法/URL/状态码/请求/响应 前 2000 字符
    """
    engine = get_engine()
    r = query_mitm_flows(engine, after_id=after_id, limit=limit, keyword=keyword)
    return json.dumps(r, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 主动扫描: 端口扫描 / 漏洞检测 / 爆破 / 爬虫
# ---------------------------------------------------------------------------
@mcp.tool()
def yakit_port_scan(targets: str, ports: str = "80,443,8080",
                    mode: str = "tcp", concurrent: int = 100,
                    fingerprint_mode: str = "all") -> str:
    """
    端口扫描（Yakit PortScan 引擎）。
    参数:
      targets: 目标（如 1.2.3.4 或 1.2.3.0/24 或 domain.com）
      ports: 端口范围（如 80,443,1-1000）
      mode: 扫描模式 tcp/syn（默认 tcp）
      concurrent: 并发数（默认 100）
      fingerprint_mode: 指纹识别 all/service/web（默认 all）
    返回: 扫描结果（发现端口/服务/指纹）
    """
    engine = get_engine()
    r = port_scan(engine, targets, ports, mode, concurrent, fingerprint_mode)
    return json.dumps(r, ensure_ascii=False, indent=2)


@mcp.tool()
def yakit_simple_detect(targets: str, ports: str = "80,443",
                        concurrent: int = 100, total_timeout: int = 600) -> str:
    """
    漏洞检测（Yakit SimpleDetect，nuclei 引擎 + 插件）。
    参数:
      targets: 目标
      ports: 检测端口
      concurrent: 并发
      total_timeout: 总超时秒数
    返回: 检测结果（发现的漏洞/指纹）
    """
    engine = get_engine()
    r = simple_detect(engine, targets, ports, concurrent, total_timeout)
    return json.dumps(r, ensure_ascii=False, indent=2)


@mcp.tool()
def yakit_start_brute(target: str, service_type: str = "ssh",
                      username: str = "", password: str = "",
                      username_file: str = "", password_file: str = "",
                      concurrent: int = 20) -> str:
    """
    弱口令爆破（Yakit StartBrute）。
    参数:
      target: 目标（host:port）
      service_type: 服务类型（ssh/mysql/redis/ftp/... 用 yakit_brute_types 查）
      username/password: 单账号密码
      username_file/password_file: 字典文件路径
      concurrent: 并发数
    返回: 爆破结果（成功/失败）
    """
    engine = get_engine()
    r = start_brute(engine, target, service_type, username, password,
                    username_file, password_file, concurrent)
    return json.dumps(r, ensure_ascii=False, indent=2)


@mcp.tool()
def yakit_brute_types() -> str:
    """获取可用的弱口令爆破服务类型列表。"""
    engine = get_engine()
    r = brute_types(engine)
    return json.dumps(r, ensure_ascii=False, indent=2)


@mcp.tool()
def yakit_basic_crawler(target: str, max_depth: int = 2,
                        max_urls: int = 100, concurrent: int = 10) -> str:
    """
    基础爬虫（Yakit StartBasicCrawler），爬取目标站点 URL。
    参数:
      target: 起始 URL（如 http://example.com）
      max_depth: 爬取深度（默认 2）
      max_urls: 最大 URL 数（默认 100）
      concurrent: 并发数
    返回: 爬取结果
    """
    engine = get_engine()
    r = basic_crawler(engine, target, max_depth, max_urls, concurrent)
    return json.dumps(r, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 资产与漏洞查询
# ---------------------------------------------------------------------------
@mcp.tool()
def yakit_query_ports(keyword: str = "", limit: int = 50,
                      hosts: str = "", ports: str = "") -> str:
    """
    查询端口资产（端口扫描结果入库后从这里取）。
    参数: keyword(关键词), hosts(主机过滤), ports(端口过滤), limit
    """
    engine = get_engine()
    r = query_ports(engine, keyword, limit, hosts, ports)
    return json.dumps(r, ensure_ascii=False, indent=2)


@mcp.tool()
def yakit_query_hosts(keyword: str = "", limit: int = 50) -> str:
    """查询主机资产。参数: keyword, limit"""
    engine = get_engine()
    r = query_hosts(engine, keyword, limit)
    return json.dumps(r, ensure_ascii=False, indent=2)


@mcp.tool()
def yakit_query_domains(keyword: str = "", limit: int = 50) -> str:
    """查询域名资产。参数: keyword, limit"""
    engine = get_engine()
    r = query_domains(engine, keyword, limit)
    return json.dumps(r, ensure_ascii=False, indent=2)


@mcp.tool()
def yakit_query_risks(keyword: str = "", limit: int = 50, severity: str = "") -> str:
    """
    查询漏洞/风险记录。
    参数: keyword(关键词), severity(严重级别 high/medium/low), limit
    """
    engine = get_engine()
    r = query_risks(engine, keyword, limit, severity)
    return json.dumps(r, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    mcp.run()


if __name__ == "__main__":
    main()
