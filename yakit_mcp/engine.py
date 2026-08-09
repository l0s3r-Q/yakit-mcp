# -*- coding: utf-8 -*-
"""
yakit-mcp: Yakit 引擎 gRPC 驱动 + GUI 联动 + 窗口截图
核心模块: 引擎管理 / HTTPFuzzer 重放 / HTTPFlow 入库
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import grpc

from . import grpc_pb2 as ypb
from . import grpc_pb2_grpc as ygrpc


class _AuthInterceptor(
    grpc.UnaryUnaryClientInterceptor,
    grpc.UnaryStreamClientInterceptor,
    grpc.StreamUnaryClientInterceptor,
    grpc.StreamStreamClientInterceptor,
):
    """gRPC 客户端拦截器: 为所有请求注入 authorization metadata（local-password 模式）"""

    def __init__(self, metadata):
        self._metadata = metadata

    def _with_metadata(self, client_call_details):
        return client_call_details._replace(metadata=self._metadata)

    def intercept_unary_unary(self, continuation, client_call_details, request):
        return continuation(self._with_metadata(client_call_details), request)

    def intercept_unary_stream(self, continuation, client_call_details, request):
        return continuation(self._with_metadata(client_call_details), request)

    def intercept_stream_unary(self, continuation, client_call_details, request_iterator):
        return continuation(self._with_metadata(client_call_details), request_iterator)

    def intercept_stream_stream(self, continuation, client_call_details, request_iterator):
        return continuation(self._with_metadata(client_call_details), request_iterator)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
DEFAULT_PORT = 10053
DEFAULT_HOST = "127.0.0.1"

# Yakit 安装目录探测
def find_yakit_engine() -> str | None:
    """查找 yak 引擎可执行文件"""
    candidates = [
        os.environ.get("YAKIT_ENGINE", ""),
        r"D:\My_apps\Yakit\bins\yak_windows_amd64.exe",
        r"D:\My_apps\Yakit\bins\yak.exe",
        r"C:\Yakit\bins\yak_windows_amd64.exe",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    # 从 yak.zip 解压
    for z in [r"D:\My_apps\Yakit\bins\yak.zip", r"C:\Yakit\bins\yak.zip"]:
        if Path(z).exists():
            import zipfile
            out = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "yakit-mcp" / "engine"
            out.mkdir(parents=True, exist_ok=True)
            exe = out / "bins" / "yak_windows_amd64.exe"
            if not exe.exists():
                try:
                    with zipfile.ZipFile(z) as zf:
                        zf.extractall(out)
                except Exception:
                    pass
            if exe.exists():
                return str(exe)
    return None


def find_yakit_gui() -> str | None:
    """查找 Yakit GUI 可执行文件"""
    candidates = [
        r"D:\My_apps\Yakit\Yakit.exe",
        r"C:\Program Files\Yakit\Yakit.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Yakit\Yakit.exe"),
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


class YakEngine:
    """Yakit 引擎管理器: 探测/启动/连接"""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, auto_start: bool = True):
        self.host = host
        self.port = port
        self.auto_start = auto_start
        self._proc: subprocess.Popen | None = None
        self._channel: grpc.Channel | None = None
        self._stub: ygrpc.YakStub | None = None
        # 关键: 默认用 GUI 的项目目录（与 GUI 同一数据库，避免 database is closed / 数据不同步）
        self._home = os.environ.get("YAKIT_HOME", str(Path(r"D:\My_apps\Yakit\yakit-projects")))
        if not Path(self._home).exists():
            self._home = os.environ.get("YAKIT_HOME", str(Path(os.environ.get("APPDATA", "")) / "Yakit"))

    # -- 端口探测 ----------------------------------------------------------
    @staticmethod
    def _port_open(host: str, port: int, timeout: float = 0.8) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def is_running(self) -> bool:
        return self._port_open(self.host, self.port)

    # -- 启动 --------------------------------------------------------------
    def start(self, timeout: float = 45) -> bool:
        """启动 yak 引擎 gRPC server（若未运行）"""
        if self.is_running():
            return True
        engine = find_yakit_engine()
        if not engine:
            raise RuntimeError("未找到 yak 引擎，请安装 Yakit 或设置 YAKIT_ENGINE 环境变量")
        log = Path(os.environ.get("LOCALAPPDATA", "")) / "yakit-mcp" / "engine.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        logf = open(log, "ab")
        self._proc = subprocess.Popen(
            [engine, "grpc", "--port", str(self.port), "--home", self._home],
            stdout=logf, stderr=logf,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            if os.name == "nt" else 0,
            close_fds=True,
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_running():
                return True
            time.sleep(1)
        return self.is_running()

    # -- 连接 --------------------------------------------------------------
    def connect(self) -> ygrpc.YakStub:
        if self._stub and self._channel:
            return self._stub
        # 修复: 先探测 GUI 是否在跑 + 探测真实引擎端口（GUI 引擎可能不在 10053）
        if not self.is_running():
            found = self._probe_engine_port()
            if found:
                self.port = found
        if self.auto_start and not self.is_running():
            if not self.start():
                raise RuntimeError(f"引擎启动失败（{self.host}:{self.port}），请检查日志")
        # GUI 引擎 local-password 模式(9011): 从引擎进程命令行提取随机密码
        auth_metadata = None
        if self.port == 9011:
            pwd = self._grab_engine_password()
            if pwd:
                auth_metadata = (("authorization", f"bearer {pwd}"),)
        self._channel = grpc.insecure_channel(
            f"{self.host}:{self.port}",
            options=[
                ("grpc.max_receive_message_length", 200 * 1024 * 1024),
                ("grpc.max_send_message_length", 200 * 1024 * 1024),
            ],
        )
        try:
            grpc.channel_ready_future(self._channel).result(timeout=10)
        except Exception as e:
            raise RuntimeError(f"gRPC 连接失败: {e!r}")
        if auth_metadata:
            self._stub = ygrpc.YakStub(grpc.intercept_channel(self._channel, _AuthInterceptor(auth_metadata)))
        else:
            self._stub = ygrpc.YakStub(self._channel)
        return self._stub

    @staticmethod
    def _extract_password_from_cmd(cmdline: str) -> str | None:
        """从引擎命令行提取 --local-password 后的密码"""
        import re
        m = re.search(r'--local-password\s+(\S+)', cmdline)
        if m:
            pwd = m.group(1).strip().strip('"')
            if pwd and pwd not in ('""', "''"):
                return pwd
        return None

    def _grab_engine_password(self) -> str | None:
        """从 yak 引擎进程命令行抓 local-password（GUI 每次启动生成的随机密码）"""
        try:
            import subprocess
            r = subprocess.run(
                ['powershell', '-NoProfile', '-Command',
                 "Get-CimInstance Win32_Process | Where-Object { $_.Name -like '*yak*' } | ForEach-Object { $_.CommandLine }"],
                capture_output=True, text=True, timeout=15)
            for line in r.stdout.split('\n'):
                if 'grpc' in line and '--local-password' in line:
                    pwd = self._extract_password_from_cmd(line)
                    if pwd:
                        return pwd
        except Exception:
            pass
        return None

    def _probe_engine_port(self) -> int | None:
        """探测可能存在的引擎端口（GUI 引擎实际端口）"""
        candidates = [10053, 9011, 8087, 63333]
        # 额外: 从 yak 进程的监听端口找
        try:
            import subprocess
            out = subprocess.run(['netstat', '-ano'], capture_output=True, text=True, timeout=10).stdout
            yak_pids = set()
            tl = subprocess.run(['tasklist'], capture_output=True, text=True, timeout=10).stdout
            for line in tl.split('\n'):
                if 'yak' in line.lower() and 'yak_windows' in line.lower() or 'yak.exe' in line.lower():
                    parts = line.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        yak_pids.add(parts[1])
            for line in out.split('\n'):
                if 'LISTENING' in line:
                    parts = line.split()
                    if len(parts) >= 5 and parts[4] in yak_pids:
                        addr = parts[1]
                        port = int(addr.rsplit(':', 1)[-1])
                        if port not in candidates:
                            candidates.append(port)
        except Exception:
            pass
        for p in candidates:
            if self._port_open(self.host, p):
                return p
        return None

    @property
    def stub(self) -> ygrpc.YakStub:
        return self.connect()

    def version(self) -> str:
        try:
            resp = self.stub.Version(ypb.Empty())
            return resp.Version
        except Exception:
            return "unknown"

    def close(self):
        if self._channel:
            self._channel.close()
            self._channel = None
            self._stub = None


# ---------------------------------------------------------------------------
# 重放逻辑
# ---------------------------------------------------------------------------
def parse_http_packet(packet_text: str) -> dict:
    """
    解析原始 HTTP 报文文本（Burp 复制的包 / Yakit 复制的包）
    返回 {request, is_https, host, port, method, path, scheme, headers, body, protocol_hint}
    protocol_hint: "https" | "http" | "unknown"（协议线索）
    """
    text = packet_text.strip()
    if not text:
        raise ValueError("HTTP 报文为空")
    # 支持换行符归一化
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")
    # 请求行: METHOD SP PATH SP HTTP/x.y
    request_line = lines[0].strip()
    parts = request_line.split(" ")
    if len(parts) < 3:
        raise ValueError(f"请求行格式错误: {request_line!r}")
    method, path, version = parts[0], parts[1], parts[2]

    # 解析 headers
    headers = {}
    header_lines = []
    body_start = None
    for i, line in enumerate(lines[1:], start=1):
        if not line.strip():
            body_start = i + 1
            break
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
        header_lines.append(line)

    body = ""
    if body_start is not None:
        body = "\n".join(lines[body_start:])

    # Host 推断
    host_header = headers.get("host", "")
    is_https = headers.get("__yakit_is_https", "") == "true" or path.startswith("https://")
    scheme = "https" if is_https else "http"
    host = host_header
    port = 443 if scheme == "https" else 80
    if ":" in host_header:
        h, _, p = host_header.rpartition(":")
        if p.isdigit():
            host, port = h, int(p)
    # 协议线索（严格: 只有明确线索才判，否则 unknown）
    protocol_hint = "unknown"
    if path.startswith("https://") or headers.get("__yakit_is_https") == "true":
        protocol_hint = "https"
    elif path.startswith("http://"):
        protocol_hint = "http"
    elif host_header.endswith(":443"):
        protocol_hint = "https"
    elif host_header.endswith(":80"):
        protocol_hint = "http"
    return {
        "request": text,
        "is_https": is_https,
        "host": host,
        "port": port,
        "method": method,
        "path": path,
        "scheme": scheme,
        "headers": headers,
        "body": body,
        "protocol_hint": protocol_hint,
    }


def detect_protocol(packet_text: str) -> str:
    """自动识别协议: 'http' | 'https' | 'unknown'"""
    try:
        return parse_http_packet(packet_text)["protocol_hint"]
    except Exception:
        return "unknown"


def push_webfuzzer_tab(engine: YakEngine, packet: str, is_https: bool = False, tab_name: str = "MCP") -> dict:
    """
    【官方通道】通过 gRPC DuplexConnection 推送 web_fuzzer_tab 事件，
    让 GUI 自动新建 Web Fuzzer tab 并填入请求（源码确认: MCP/后端通知前端新建 Web Fuzzer Tab）。
    彻底绕开 Monaco 编辑器填包（解决旧内容残留 + 填包问题）。
    Config 结构对齐源码 MultipleNodeInfo（含 id/verbose/groupId/pageParams.request），
    openFlag=true 时前端 setCurrentTabKey 切到新 tab 前台显示。
    返回: {ok, sent, reason}
    """
    stub = engine.connect()
    try:
        import time as _time
        # 构造 Config: 对齐 MultipleNodeInfo / ComponentParams 结构（源码 MainOperatorContentType.d.ts）
        config = {
            "id": f"mcp-{int(_time.time() * 1000)}",
            "verbose": tab_name,
            "groupId": "0",
            "sortFieId": 1,
            "pageParams": {
                "id": f"mcp-{int(_time.time() * 1000)}",
                "groupId": "0",
                "isHttps": is_https,
                "request": packet,
                "advancedConfigValue": {},
            },
        }
        payload = {
            "openFlag": True,
            "data": [
                {
                    "PageId": "",
                    "Type": "page",
                    "Config": json.dumps(config, ensure_ascii=False)
                }
            ],
        }
        req = ypb.DuplexConnectionRequest(
            Data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            MessageType="web_fuzzer_tab",
            Timestamp=int(time.time() * 1000),
        )
        # 双向流: 发一条就够（服务端收到即推送前端）
        responses = []
        def gen():
            yield req
        for resp in stub.DuplexConnection(gen(), timeout=10):
            responses.append(resp)
            break
        return {"ok": True, "sent": True, "payload": payload}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def replay_packet(
    engine: YakEngine,
    packet_text: str,
    *,
    is_https: bool | None = None,
    proxy: str = "",
    timeout: float = 30.0,
    no_follow_redirect: bool = False,
    max_retries: int = 0,
    return_raw: bool = False,
) -> dict:
    """
    用 Yakit 引擎重放一个 HTTP 包（Web Fuzzer 引擎）
    返回结构化结果；return_raw=True 时附加 "raw_response" 字段（FuzzerResponse 对象）
    """
    info = parse_http_packet(packet_text)
    req = ypb.FuzzerRequest()
    req.Request = info["request"]
    req.IsHTTPS = is_https if is_https is not None else info["is_https"]
    req.NoSystemProxy = True
    req.PerRequestTimeoutSeconds = timeout
    if proxy:
        req.Proxy = proxy
    if no_follow_redirect:
        req.NoFollowRedirect = True
    if max_retries > 0:
        req.MaxRetryTimes = max_retries

    stub = engine.connect()
    results = []
    for resp in stub.HTTPFuzzer(req, timeout=timeout + 30):
        results.append(resp)
    if not results:
        return {"ok": False, "reason": "无响应流返回"}

    resp = results[0]
    response_raw = resp.ResponseRaw if resp.ResponseRaw else b""
    try:
        response_text = response_raw.decode("utf-8", errors="replace")
    except Exception:
        response_text = str(response_raw)

    result = {
        "ok": resp.Ok,
        "reason": resp.Reason,
        "status_code": resp.StatusCode,
        "method": resp.Method,
        "host": resp.Host,
        "url": resp.Url,
        "remote_addr": resp.RemoteAddr,
        "content_type": resp.ContentType,
        "body_length": resp.BodyLength,
        "duration_ms": resp.DurationMs,
        "total_duration_ms": resp.TotalDurationMs,
        "task_id": resp.TaskId,
        "is_https": resp.IsHTTPS,
        "timestamp": resp.Timestamp,
        "uuid": resp.UUID,
        "proxy": resp.Proxy,
        "request_raw": (resp.RequestRaw or b"").decode("utf-8", errors="replace"),
        "response_raw": response_text,
        "response_headers": [
            {"key": h.Header, "value": h.Value} for h in (resp.Headers or [])
        ],
        "matched_by_filter": resp.MatchedByFilter,
        "matched_by_matcher": resp.MatchedByMatcher,
        "hit_color": resp.HitColor,
    }
    if return_raw:
        result["raw_response"] = resp
    return result


def convert_to_httpflow(engine: YakEngine, fuzzer_response: ypb.FuzzerResponse) -> dict:
    """把 Fuzzer 响应转成 HTTPFlow 入库（GUI 流量列表可见）"""
    stub = engine.connect()
    try:
        flow = stub.ConvertFuzzerResponseToHTTPFlow(fuzzer_response)
        return {
            "ok": True,
            "id": flow.Id,
            "url": flow.Url,
            "method": flow.Method,
            "status_code": flow.StatusCode,
            "hash": flow.Hash,
            "created_at": flow.CreatedAt,
        }
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def query_http_flows(engine: YakEngine, keyword: str = "", limit: int = 20) -> dict:
    """查询历史 HTTP 流量"""
    stub = engine.connect()
    req = ypb.QueryHTTPFlowRequest()
    req.Keyword = keyword
    req.Pagination.Limit = limit
    req.Pagination.Page = 1
    try:
        resp = stub.QueryHTTPFlows(req)
        flows = []
        for f in resp.Data or []:
            flows.append({
                "id": f.Id,
                "method": f.Method,
                "url": f.Url,
                "status_code": f.StatusCode,
                "content_type": f.ContentType,
                "body_length": f.BodyLength,
                "is_https": f.IsHTTPS,
                "created_at": f.CreatedAt,
                "hash": f.Hash,
            })
        return {"ok": True, "total": resp.Total, "flows": flows}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def clear_fuzzer_history(engine: YakEngine, task_id: int = 0, clear_configs: bool = True) -> dict:
    """
    清空 Web Fuzzer 历史（数据库层，解决"旧内容残留"）。
    1. 删除历史任务（web_fuzzer_tasks → UI 历史 tab 列表消失）
    2. 可选: 清空 fuzzer 配置归档（web_fuzzer_configs）
    task_id=0 时删除全部任务；指定 id 只删该任务。
    """
    stub = engine.connect()
    result = {}
    try:
        req = ypb.DeleteHistoryHTTPFuzzerTaskRequest(Id=task_id)
        stub.DeleteHistoryHTTPFuzzerTask(req)
        resp = stub.QueryHistoryHTTPFuzzerTask(ypb.Empty())
        result["remaining_tasks"] = len(list(resp.Tasks if resp.Tasks else []))
        result["tasks_ok"] = True
    except Exception as e:
        result["tasks_ok"] = False
        result["tasks_reason"] = repr(e)

    if clear_configs:
        try:
            r = stub.DeleteFuzzerConfig(ypb.DeleteFuzzerConfigRequest(DeleteAll=True))
            result["configs_ok"] = True
            result["configs_deleted"] = r.EffectRows
        except Exception as e:
            result["configs_ok"] = False
            result["configs_reason"] = repr(e)

    result["ok"] = result.get("tasks_ok", False) or result.get("configs_ok", False)
    result["deleted_all"] = task_id == 0
    return result


def list_fuzzer_history(engine: YakEngine) -> dict:
    """列出 Web Fuzzer 历史任务（tab 数据源）"""
    stub = engine.connect()
    try:
        resp = stub.QueryHistoryHTTPFuzzerTask(ypb.Empty())
        tasks = []
        for t in resp.Tasks or []:
            tasks.append({
                "id": t.Id,
                "host": t.Host,
                "port": t.Port,
                "http_flow_total": t.HTTPFlowTotal,
                "success": t.HTTPFlowSuccessCount,
                "failed": t.HTTPFlowFailedCount,
                "created_at": t.CreatedAt,
            })
        return {"ok": True, "total": len(tasks), "tasks": tasks}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def list_fuzzer_labels(engine: YakEngine) -> dict:
    """列出 Web Fuzzer 分组标签（FuzzerLabel）"""
    stub = engine.connect()
    try:
        resp = stub.QueryFuzzerLabel(ypb.Empty())
        labels = []
        for l in resp.Data or []:
            labels.append({
                "id": l.Id,
                "label": l.Label,
                "description": l.Description,
                "hash": l.Hash,
            })
        return {"ok": True, "total": len(labels), "labels": labels}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def save_fuzzer_label(engine: YakEngine, label: str, description: str = "") -> dict:
    """新建 Web Fuzzer 分组标签"""
    stub = engine.connect()
    try:
        stub.SaveFuzzerLabel(ypb.SaveFuzzerLabelRequest(Data=[
            ypb.FuzzerLabel(Label=label, Description=description)
        ]))
        return {"ok": True, "label": label, "description": description}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def delete_fuzzer_label(engine: YakEngine, hash_value: str) -> dict:
    """删除 Web Fuzzer 分组标签（按 hash）"""
    stub = engine.connect()
    try:
        stub.DeleteFuzzerLabel(ypb.DeleteFuzzerLabelRequest(Hash=hash_value))
        return {"ok": True, "hash": hash_value}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


# ---------------------------------------------------------------------------
# MITM 中间人抓包
# ---------------------------------------------------------------------------
# MITM 流管理（全局单例，避免多流冲突）
_mitm_streams: dict = {}


def mitm_start(engine: YakEngine, port: int = 8083, host: str = "0.0.0.0",
               filters: dict | None = None, timeout: float = 5.0) -> dict:
    """
    启动 MITM 中间人抓包监听（MITMV2 双向流）。
    抓到的流量写入 http_flows 表（SourceType=mitm），用 yakit_mitm_flows 增量获取。
    返回: {ok, port, reason}
    """
    global _mitm_streams
    stub = engine.connect()
    try:
        req = ypb.MITMV2Request()
        req.Host = host
        req.Port = port
        # 过滤器
        if filters:
            fd = ypb.MITMFilterData()
            for k, v in filters.items():
                if k == "include_hostname" and v:
                    fd.IncludeHostname.extend(v if isinstance(v, list) else [v])
                elif k == "exclude_hostname" and v:
                    fd.ExcludeHostname.extend(v if isinstance(v, list) else [v])
                elif k == "exclude_suffix" and v:
                    fd.ExcludeSuffix.extend(v if isinstance(v, list) else [v])
                elif k == "exclude_content_types" and v:
                    fd.ExcludeContentTypes.extend(v if isinstance(v, list) else [v])
            req.FilterData.CopyFrom(fd)
            req.UpdateFilter = True

        def gen():
            yield req
            # 保持流打开（引擎会持续推送流量事件）
            import time as _t
            while True:
                _t.sleep(60)

        # 后台线程启动流（避免阻塞 MCP 调用）
        import threading
        result_box = {}

        def _run():
            try:
                stream = stub.MITMV2(gen(), timeout=timeout)
                first = next(stream, None)
                result_box["stream"] = stream
                result_box["first"] = first
            except Exception as e:
                result_box["error"] = repr(e)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=timeout)
        if "error" in result_box:
            return {"ok": False, "reason": result_box["error"]}
        stream = result_box.get("stream")
        if stream is None:
            return {"ok": False, "reason": "MITM 启动超时（可能端口被占用或引擎不支持）"}
        # 保存流引用（保持连接）
        _mitm_streams[port] = stream
        return {"ok": True, "port": port, "host": host, "started": True}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def mitm_stop(engine: YakEngine, port: int = 8083) -> dict:
    """停止 MITM 监听（关闭流）"""
    global _mitm_streams
    try:
        stream = _mitm_streams.pop(port, None)
        if stream:
            try:
                stream.cancel()
            except Exception:
                pass
        return {"ok": True, "port": port, "stopped": True}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def mitm_status(engine: YakEngine) -> dict:
    """查看当前 MITM 监听状态"""
    global _mitm_streams
    return {"ok": True, "active_ports": list(_mitm_streams.keys())}


def query_mitm_flows(engine: YakEngine, after_id: int = 0, limit: int = 50,
                     keyword: str = "") -> dict:
    """
    增量获取 MITM 抓到的 HTTP 流量（SourceType=mitm）。
    after_id: 只返回 id 大于该值的流量（增量拉取，默认 0=全部）
    """
    stub = engine.connect()
    try:
        req = ypb.QueryHTTPFlowRequest()
        req.SourceType = "mitm"
        req.Pagination.Limit = limit
        req.Pagination.Page = 1
        if after_id > 0:
            req.AfterId = after_id
        if keyword:
            req.Keyword = keyword
        resp = stub.QueryHTTPFlows(req)
        flows = []
        for f in resp.Data or []:
            flows.append({
                "id": f.Id,
                "method": f.Method,
                "url": f.Url,
                "status_code": f.StatusCode,
                "is_https": f.IsHTTPS,
                "content_type": f.ContentType,
                "body_length": f.BodyLength,
                "created_at": f.CreatedAt,
                "source_type": f.SourceType,
                "request": (f.Request or b"").decode("utf-8", errors="replace")[:2000],
                "response": (f.Response or b"").decode("utf-8", errors="replace")[:2000],
            })
        return {"ok": True, "total": resp.Total, "flows": flows}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


# ---------------------------------------------------------------------------
# 主动扫描: 端口扫描 / 漏洞检测 / 弱口令爆破 / 爬虫
# ---------------------------------------------------------------------------
def port_scan(engine: YakEngine, targets: str, ports: str = "80,443,8080",
              mode: str = "tcp", concurrent: int = 100, fingerprint_mode: str = "all") -> dict:
    """
    端口扫描（PortScan）。
    参数: targets(如 1.1.1.1 或 1.1.1.0/24), ports(如 80,443,1-1000), mode(tcp/syn), fingerprint_mode(all/service/web)
    返回: 扫描结果流（发现的端口/服务/指纹）
    """
    stub = engine.connect()
    try:
        req = ypb.PortScanRequest()
        req.Targets = targets
        req.Ports = ports
        req.Mode = mode
        req.Concurrent = concurrent
        req.FingerprintMode = fingerprint_mode
        req.SaveToDB = True
        results = []
        for resp in stub.PortScan(req, timeout=300):
            text = resp.Message or resp.Raw or b""
            if text:
                results.append(text.decode("utf-8", errors="replace") if isinstance(text, bytes) else text)
        # 解析 JSON 流（Yakit 扫描结果: {"type":"log"/"progress", "content":{...}}）
        parsed = []
        for line in results:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                ctype = obj.get("type", "")
                content = obj.get("content", {})
                if isinstance(content, dict):
                    level = content.get("level", "")
                    data = content.get("data", "")
                    # 提取有用信息（跳过纯状态卡）
                    if data and "feature-status" not in level and ctype != "progress":
                        try:
                            inner = json.loads(data)
                            parsed.append({"type": ctype, "level": level, "data": inner})
                        except Exception:
                            parsed.append({"type": ctype, "level": level, "data": data[:300]})
            except Exception:
                if "feature-status" not in line:
                    parsed.append({"raw": line[:300]})
        return {"ok": True, "targets": targets, "ports": ports,
                "total_events": len(results), "parsed": parsed[:60]}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def simple_detect(engine: YakEngine, targets: str, ports: str = "80,443",
                  concurrent: int = 100, total_timeout: int = 600) -> dict:
    """
    漏洞检测（SimpleDetect，基于 nuclei 引擎 + Yakit 插件）。
    参数: targets(目标), ports(端口), concurrent(并发), total_timeout(总超时秒)
    返回: 检测结果流（发现的漏洞/指纹）
    """
    stub = engine.connect()
    try:
        # SimpleDetect 基于 PortScan + 漏洞插件
        scan = ypb.PortScanRequest()
        scan.Targets = targets
        scan.Ports = ports
        scan.Mode = "tcp"
        scan.Concurrent = concurrent
        scan.SaveToDB = True
        record = ypb.RecordPortScanRequest()
        record.PortScanRequest.CopyFrom(scan)
        results = []
        for resp in stub.SimpleDetect(record, timeout=total_timeout + 30):
            text = resp.Message or resp.Raw or b""
            if text:
                results.append(text)
        return {"ok": True, "targets": targets, "results": results[:200]}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def start_brute(engine: YakEngine, targets: str, service_type: str = "ssh",
                username: str = "", password: str = "",
                username_file: str = "", password_file: str = "",
                concurrent: int = 20) -> dict:
    """
    弱口令爆破（StartBrute）。
    参数:
      targets: 目标(host:port)
      service_type: 服务类型(ssh/mysql/redis/... 用 yakit_brute_types 查)
      username/password: 单账号密码
      username_file/password_file: 字典文件路径
    """
    stub = engine.connect()
    try:
        req = ypb.StartBruteParams()
        req.Target = targets
        req.BruteType = service_type
        req.Concurrent = concurrent
        if username:
            req.Username = username
        if password:
            req.Password = password
        if username_file:
            req.UsernameFile = username_file
        if password_file:
            req.PasswordFile = password_file
        results = []
        for resp in stub.StartBrute(req, timeout=300):
            text = resp.Message or resp.Raw or b""
            if text:
                results.append(text)
        return {"ok": True, "target": targets, "type": service_type, "results": results[:100]}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def brute_types(engine: YakEngine) -> dict:
    """获取可用的爆破服务类型"""
    stub = engine.connect()
    try:
        resp = stub.GetAvailableBruteTypes(ypb.Empty())
        return {"ok": True, "types": list(resp.Types or [])}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def basic_crawler(engine: YakEngine, target: str, max_depth: int = 2,
                  max_urls: int = 100, concurrent: int = 10) -> dict:
    """
    基础爬虫（StartBasicCrawler）。
    参数: target(起始URL), max_depth(深度), max_urls(最大URL数)
    返回: 爬取结果（发现的 URL）
    """
    stub = engine.connect()
    try:
        req = ypb.StartBasicCrawlerRequest()
        req.Target = target
        req.MaxDepth = max_depth
        req.MaxUrls = max_urls
        req.Concurrent = concurrent
        resp = stub.StartBasicCrawler(req, timeout=300)
        return {"ok": True, "result": resp.Raw or resp.Message or ""}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


# ---------------------------------------------------------------------------
# 资产查询: 端口 / 主机 / 域名 / 风险
# ---------------------------------------------------------------------------
def query_ports(engine: YakEngine, keyword: str = "", limit: int = 50,
                hosts: str = "", ports: str = "") -> dict:
    """查询端口资产（扫描结果入库后从这里取）"""
    stub = engine.connect()
    try:
        req = ypb.QueryPortsRequest()
        req.Pagination.Limit = limit
        req.Pagination.Page = 1
        if keyword:
            req.Keywords = keyword
        if hosts:
            req.Hosts = hosts
        if ports:
            req.Ports = ports
        resp = stub.QueryPorts(req)
        items = []
        for p in resp.Data or []:
            items.append({
                "id": p.Id,
                "host": p.Host,
                "port": p.Port,
                "service": p.Service,
                "state": p.State,
                "title": p.Title,
                "proto": p.Proto,
                "fingerprint": p.Fingerprint,
                "updated_at": p.UpdatedAt,
            })
        return {"ok": True, "total": resp.Total, "ports": items}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def query_hosts(engine: YakEngine, keyword: str = "", limit: int = 50) -> dict:
    """查询主机资产"""
    stub = engine.connect()
    try:
        req = ypb.QueryHostsRequest()
        req.Pagination.Limit = limit
        req.Pagination.Page = 1
        if keyword:
            req.Keywords = keyword
        resp = stub.QueryHosts(req)
        items = []
        for h in resp.Data or []:
            items.append({
                "id": h.Id,
                "ip": h.IP,
                "domain": h.Domain,
                "is_public": h.IsInPublicNet,
                "ports_count": h.Ports,
                "updated_at": h.UpdatedAt,
            })
        return {"ok": True, "total": resp.Total, "hosts": items}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def query_domains(engine: YakEngine, keyword: str = "", limit: int = 50) -> dict:
    """查询域名资产"""
    stub = engine.connect()
    try:
        req = ypb.QueryDomainsRequest()
        req.Pagination.Limit = limit
        req.Pagination.Page = 1
        if keyword:
            req.Keywords = keyword
        resp = stub.QueryDomains(req)
        items = []
        for d in resp.Data or []:
            items.append({
                "id": d.Id,
                "domain": d.Domain,
                "ip": d.IP,
                "updated_at": d.UpdatedAt,
            })
        return {"ok": True, "total": resp.Total, "domains": items}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def query_risks(engine: YakEngine, keyword: str = "", limit: int = 50,
                severity: str = "") -> dict:
    """查询漏洞/风险记录"""
    stub = engine.connect()
    try:
        req = ypb.QueryRisksRequest()
        req.Pagination.Limit = limit
        req.Pagination.Page = 1
        if keyword:
            req.Keywords = keyword
        if severity:
            req.Level = severity
        resp = stub.QueryRisks(req)
        items = []
        for r in resp.Data or []:
            items.append({
                "id": r.Id,
                "risk_type": r.RiskType,
                "url": r.Url,
                "title": r.Title,
                "severity": r.Severity,
                "description": (r.Description or "")[:300],
                "target": r.IP or r.Host,
                "updated_at": r.UpdatedAt,
            })
        return {"ok": True, "total": resp.Total, "risks": items}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}
