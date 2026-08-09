# -*- coding: utf-8 -*-
"""
yakit-mcp 长任务异步化模块
- 扫描/检测/爆破类任务后台线程执行（不阻塞 MCP 调用）
- 任务状态查询（进度/结果/完成）
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Callable, Optional

import grpc

from . import grpc_pb2 as ypb

# 全局任务注册表 {task_id: TaskInfo}
_TASKS: dict[str, dict] = {}
_LOCK = threading.Lock()


class TaskInfo:
    """后台任务状态"""

    def __init__(self, name: str, runtime_id: str = ""):
        self.task_id = uuid.uuid4().hex[:12]
        self.name = name
        self.runtime_id = runtime_id
        self.status = "running"  # running | done | failed
        self.progress = 0.0
        self.started_at = time.time()
        self.finished_at: Optional[float] = None
        self.results: list = []
        self.summary: dict = {}
        self.error: str = ""


def _register(info: TaskInfo) -> str:
    with _LOCK:
        _TASKS[info.task_id] = info
    return info.task_id


def list_tasks() -> dict:
    """列出所有任务（含状态）"""
    with _LOCK:
        items = []
        for tid, info in _TASKS.items():
            items.append({
                "task_id": tid,
                "name": info.name,
                "runtime_id": info.runtime_id,
                "status": info.status,
                "progress": round(info.progress, 2),
                "elapsed": round(time.time() - info.started_at, 1),
                "result_count": len(info.results),
            })
        items.sort(key=lambda x: x["elapsed"], reverse=True)
        return {"ok": True, "total": len(items), "tasks": items}


def get_task(task_id: str) -> dict:
    """查询单个任务状态 + 结果"""
    with _LOCK:
        info = _TASKS.get(task_id)
        if not info:
            return {"ok": False, "reason": f"任务不存在: {task_id}"}
        return {
            "ok": True,
            "task_id": task_id,
            "name": info.name,
            "runtime_id": info.runtime_id,
            "status": info.status,
            "progress": round(info.progress, 2),
            "elapsed": round(time.time() - info.started_at, 1),
            "error": info.error,
            "summary": info.summary,
            "results": info.results[:100],
        }


def wait_task(task_id: str, timeout: float = 120, interval: float = 2.0) -> dict:
    """等待任务完成（轮询），返回最终结果"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = get_task(task_id)
        if r.get("status") in ("done", "failed"):
            return r
        time.sleep(interval)
    r = get_task(task_id)
    r["timeout"] = True
    return r


def _run_stream_task(task_id: str, gen_func: Callable, collect_interval: float = 0.5):
    """后台线程: 消费 gRPC 流并更新任务状态"""
    info = _TASKS.get(task_id)
    if not info:
        return
    try:
        for resp in gen_func():
            info.results.append(resp)
            # 尝试从 ExecResult 提取进度
            try:
                if hasattr(resp, "Progress") and resp.Progress > 0:
                    info.progress = resp.Progress
                if hasattr(resp, "RuntimeID") and resp.RuntimeID and not info.runtime_id:
                    info.runtime_id = resp.RuntimeID
            except Exception:
                pass
            info.progress = min(info.progress + 0.01, 0.99)
        info.status = "done"
        info.progress = 1.0
    except Exception as e:
        info.status = "failed"
        info.error = repr(e)[:500]
    finally:
        info.finished_at = time.time()


def start_stream_task(name: str, gen_func: Callable) -> str:
    """
    启动后台流式任务。
    gen_func: 返回 gRPC 流的可调用对象（stub.PortScan(req) 等）
    返回: task_id
    """
    info = TaskInfo(name)
    tid = _register(info)
    t = threading.Thread(target=_run_stream_task, args=(tid, gen_func), daemon=True)
    t.start()
    return tid
