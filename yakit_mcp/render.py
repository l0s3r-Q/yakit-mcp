# -*- coding: utf-8 -*-
"""
yakit-mcp 响应视图渲染: 当 Yakit GUI 不可见时，把重放结果渲染成
"Yakit Web Fuzzer 风格"的图片（Request/Response 双栏面板），保证截图链路可用。
"""
from __future__ import annotations

import base64
import io
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# 配色（Yakit 暗色主题风格）
BG = (30, 32, 38)
PANEL = (38, 41, 50)
PANEL_BORDER = (55, 60, 70)
TEXT = (210, 215, 225)
DIM = (140, 148, 160)
ACCENT = (86, 156, 214)   # 蓝
GREEN = (106, 190, 120)
RED = (224, 108, 117)
ORANGE = (229, 164, 92)
METHOD_COLORS = {
    "GET": (97, 175, 239),
    "POST": (198, 120, 221),
    "PUT": (229, 192, 123),
    "DELETE": (224, 108, 117),
    "HEAD": (86, 156, 214),
    "OPTIONS": (150, 150, 150),
}


def _font(size: int):
    """尝试加载常见中文字体，失败则用默认"""
    for fp in [
        r"C:\Windows\Fonts\msyh.ttc",        # 微软雅黑
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\consola.ttf",     # Consolas 等宽
        r"C:\Windows\Fonts\cour.ttf",
    ]:
        try:
            return ImageFont.truetype(fp, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _wrap(text: str, font, max_width: int) -> list[str]:
    """按像素宽度换行"""
    lines = []
    for raw_line in text.split("\n"):
        if not raw_line:
            lines.append("")
            continue
        cur = ""
        for ch in raw_line:
            if font.getlength(cur + ch) > max_width and cur:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        lines.append(cur)
    return lines


def render_response_image(result: dict, width: int = 1200) -> Image.Image:
    """
    把重放结果渲染成 Yakit Web Fuzzer 风格图片
    result: yakit_replay 的返回 dict
    """
    height = 760
    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)

    font_h = _font(15)
    font_m = _font(13)
    font_s = _font(11)
    font_title = _font(17)

    # ---- 顶栏 ----
    d.rectangle([0, 0, width, 46], fill=PANEL)
    d.text((16, 12), "Web Fuzzer - 重放结果", font=font_title, fill=TEXT)
    status = result.get("status_code", 0)
    status_color = GREEN if 200 <= status < 300 else (RED if status >= 400 else ORANGE)
    d.text((width - 260, 15), f"HTTP {status}", font=font_title, fill=status_color)
    dur = result.get("duration_ms", 0)
    d.text((width - 150, 17), f"{dur} ms", font=font_m, fill=DIM)

    # ---- 元信息行 ----
    y = 58
    method = result.get("method", "GET").upper()
    mcolor = METHOD_COLORS.get(method, (150, 150, 150))
    url = result.get("url", "")
    d.text((16, y), method, font=font_m, fill=mcolor)
    d.text((90, y), url, font=font_m, fill=TEXT)
    d.text((16, y + 22), f"Remote: {result.get('remote_addr', '-')}   Body: {result.get('body_length', 0)} bytes   TaskId: {result.get('task_id', '-')}", font=font_s, fill=DIM)

    # ---- 双栏: Request | Response ----
    col_w = (width - 16 * 3) // 2
    y_top = 100
    panel_h = height - y_top - 16

    def draw_panel(x, title, title_color, text_lines, body_lines, show_body=True):
        d.rectangle([x, y_top, x + col_w, y_top + panel_h], fill=PANEL, outline=PANEL_BORDER)
        d.text((x + 10, y_top + 8), title, font=font_m, fill=title_color)
        d.line([x, y_top + 32, x + col_w, y_top + 32], fill=PANEL_BORDER)
        yy = y_top + 42
        for line in text_lines[:26]:
            d.text((x + 10, yy), line, font=font_s, fill=TEXT)
            yy += 17
        if show_body:
            d.line([x, yy + 2, x + col_w, yy + 2], fill=(45, 48, 56))
            yy += 10
            d.text((x + 10, yy), "Body:", font=font_s, fill=ACCENT)
            yy += 17
            for line in body_lines[:18]:
                d.text((x + 10, yy), line, font=font_s, fill=(180, 190, 200))
                yy += 16

    # Request 栏
    req_text = result.get("request_raw", "")
    req_lines = _wrap(req_text, font_s, col_w - 20)
    d.text((16, y_top + 8), "Request", font=font_m, fill=ACCENT)
    draw_panel(16, "Request", ACCENT, req_lines, [], show_body=False)

    # Response 栏
    resp_raw = result.get("response_raw", "")
    resp_lines = _wrap(resp_raw, font_s, col_w - 20)
    draw_panel(16 + col_w + 16, "Response", GREEN, resp_lines, [], show_body=False)

    # ---- 底部时间戳 ----
    d.text((16, height - 24), f"yakit-mcp render @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", font=font_s, fill=DIM)

    return img


def render_and_save(result: dict, output_dir: str | None = None) -> dict:
    """渲染响应视图并返回 base64 + 保存文件"""
    img = render_response_image(result)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    saved = ""
    if output_dir:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        saved = str(out / f"yakit_response_view_{ts}.png")
        img.save(saved, format="PNG")
    return {
        "ok": True,
        "image_base64": b64,
        "saved_path": saved,
        "mime": "image/png",
        "size": img.size,
        "mode": "rendered",  # 非真实 GUI 截图，是渲染视图
    }
