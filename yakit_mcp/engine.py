# -*- coding: utf-8 -*-
"""
yakit-mcp: Yakit 引擎 gRPC 驱动 + GUI 联动 + 窗口截图
核心模块: 引擎管理 / HTTPFuzzer 重放 / HTTPFlow 入库
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import grpc

from . import grpc_pb2 as ypb
from . import grpc_pb2_grpc as ygrpc

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
        if self.auto_start and not self.is_running():
            if not self.start():
                raise RuntimeError(f"引擎启动失败（{self.host}:{self.port}），请检查日志")
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
        self._stub = ygrpc.YakStub(self._channel)
        return self._stub

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
