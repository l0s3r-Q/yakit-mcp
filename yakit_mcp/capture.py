# -*- coding: utf-8 -*-
"""
yakit-mcp 截图模块: 定位 Yakit GUI 窗口并截取画面
返回: 图片 base64（给 Agent 看）+ 保存 PNG 文件（给用户存档）
"""
from __future__ import annotations

import base64
import io
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from PIL import Image


def _load_pywinauto():
    """按需加载 pywinauto（延迟导入，避免启动开销）"""
    try:
        import pywinauto
        return pywinauto
    except ImportError:
        raise RuntimeError(
            "缺少 pywinauto，请执行: pip install pywinauto mss"
        )


def find_window_rect(window_title: str = "Yakit", timeout: float = 10.0) -> dict | None:
    """
    定位窗口矩形区域
    返回 {left, top, width, height} 或 None
    """
    pywinauto = _load_pywinauto()
    from pywinauto import Desktop
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            windows = Desktop(backend="uia").windows()
            for w in windows:
                title = (w.window_text() or "").lower()
                if window_title.lower() in title:
                    rect = w.rectangle()
                    if rect.width() > 50 and rect.height() > 50:
                        return {
                            "left": rect.left,
                            "top": rect.top,
                            "width": rect.width(),
                            "height": rect.height(),
                            "title": w.window_text(),
                        }
        except Exception:
            pass
        time.sleep(0.5)
    return None


def find_window_hwnd(window_title: str = "Yakit", timeout: float = 10.0) -> int | None:
    """用 ctypes EnumWindows 查找窗口句柄（比 pywinauto UIA 更可靠，能抓到 Electron 窗口）"""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    buf = ctypes.create_unicode_buffer(512)
    result = []

    @WNDENUMPROC
    def cb(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            user32.GetWindowTextW(hwnd, buf, 512)
            t = buf.value
            if t and window_title.lower() in t.lower():
                result.append(hwnd)
        return True

    deadline = time.time() + timeout
    while time.time() < deadline and not result:
        result.clear()
        user32.EnumWindows(cb, 0)
        time.sleep(0.5)
    return result[0] if result else None


def _bring_to_front(hwnd: int):
    """尽量把窗口置顶（后台进程可能被系统限制，尽力而为）"""
    import ctypes
    user32 = ctypes.windll.user32
    SW_RESTORE = 9
    try:
        user32.ShowWindow(hwnd, SW_RESTORE)      # 恢复最小化
        user32.SetForegroundWindow(hwnd)         # 置前
        user32.BringWindowToTop(hwnd)            # 双保险
    except Exception:
        pass


def capture_window_clean(
    window_title: str = "Yakit",
    *,
    output_dir: str | None = None,
    timeout: float = 10.0,
    use_print_window: bool = True,
) -> dict:
    """
    截取窗口画面，使用 PrintWindow API 直接绘制窗口内容（无视遮挡/最小化/后台）
    返回: {ok, image_base64, saved_path, rect, title, mode: "window"}
    """
    if use_print_window:
        return _capture_via_printwindow(window_title, output_dir=output_dir, timeout=timeout)
    return capture_window(window_title, output_dir=output_dir, timeout=timeout)


def _capture_via_printwindow(window_title: str, output_dir: str | None, timeout: float) -> dict:
    """用 PrintWindow 截取窗口（不经屏幕合成，忽略遮挡）"""
    import ctypes
    from ctypes import wintypes
    import base64, io
    from datetime import datetime
    from pathlib import Path
    from PIL import Image

    # DPI aware（保证坐标准确）
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    user32 = ctypes.windll.user32
    hwnd = find_window_hwnd(window_title, timeout)
    if not hwnd:
        return {"ok": False, "reason": f"未找到标题包含 '{window_title}' 的窗口（请先启动 Yakit GUI）"}

    # 获取窗口客户区/整个窗口矩形
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w = rect.right - rect.left
    h = rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return {"ok": False, "reason": "窗口尺寸无效"}

    # 置顶尝试（尽力而为）
    _bring_to_front(hwnd)

    # 用 GetWindowDC + PrintWindow 绘制窗口内容到内存 DC
    hdc_window = user32.GetWindowDC(hwnd)
    hdc_mem = ctypes.windll.gdi32.CreateCompatibleDC(hdc_window)
    hbmp = ctypes.windll.gdi32.CreateCompatibleBitmap(hdc_window, w, h)
    ctypes.windll.gdi32.SelectObject(hdc_mem, hbmp)

    # PrintWindow 完整绘制（PW_RENDERFULLCONTENT = 2，支持 DirectX/GPU 内容）
    PW_RENDERFULLCONTENT = 2
    result = user32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT)
    if not result:
        # 回退: 不带 flag
        result = user32.PrintWindow(hwnd, hdc_mem, 0)

    # 读取像素
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h  # 负数 = 自顶向下
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0  # BI_RGB

    buf_size = w * h * 4
    buf = ctypes.create_string_buffer(buf_size)
    ctypes.windll.gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bmi), 0)

    # 清理 GDI 资源
    ctypes.windll.gdi32.DeleteObject(hbmp)
    ctypes.windll.gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(hwnd, hdc_window)

    img = Image.frombytes("RGB", (w, h), bytes(buf), "raw", "BGRX")
    # 压缩
    max_side = 1600
    if max(img.size) > max_side:
        ratio = max_side / max(img.size)
        img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)

    b64 = base64.b64encode(img.tobytes()).decode("ascii") if False else ""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    saved_path = ""
    if output_dir:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        saved_path = str(out / f"yakit_capture_{ts}.png")
        img.save(saved_path, format="PNG")

    return {
        "ok": True,
        "image_base64": b64,
        "saved_path": saved_path,
        "rect": {"left": rect.left, "top": rect.top, "width": w, "height": h},
        "title": "",
        "size": img.size,
        "mime": "image/png",
        "mode": "window",
    }


def capture_window(
    window_title: str = "Yakit",
    *,
    output_dir: str | None = None,
    timeout: float = 10.0,
    dpi_aware: bool = True,
) -> dict:
    """
    截取 Yakit（或其他标题匹配）窗口画面
    返回: {ok, image_base64, saved_path, rect, title}
    """
    if dpi_aware:
        try:
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-Monitor DPI
            except Exception:
                ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    rect = find_window_rect(window_title, timeout)
    if not rect:
        return {"ok": False, "reason": f"未找到标题包含 '{window_title}' 的窗口（请先启动 Yakit GUI）"}

    try:
        import mss
    except ImportError:
        raise RuntimeError("缺少 mss，请执行: pip install mss")

    with mss.mss() as sct:
        monitor = {
            "left": rect["left"],
            "top": rect["top"],
            "width": rect["width"],
            "height": rect["height"],
        }
        shot = sct.grab(monitor)
        img = Image.frombytes("RGB", shot.size, shot.rgb)
    # 压缩到合理大小（最长边 1600）
    max_side = 1600
    if max(img.size) > max_side:
        ratio = max_side / max(img.size)
        img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)

    # base64（PNG）
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    # 存文件
    saved_path = ""
    if output_dir:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        saved_path = str(out / f"yakit_capture_{ts}.png")
        img.save(saved_path, format="PNG")

    return {
        "ok": True,
        "image_base64": b64,
        "saved_path": saved_path,
        "rect": rect,
        "title": rect.get("title", ""),
        "size": img.size,
        "mime": "image/png",
    }
