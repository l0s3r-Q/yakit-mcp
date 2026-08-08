# yakit-mcp

驱动本机 Yakit 引擎（gRPC 127.0.0.1:10053）重放 HTTP 包，并通过 Chrome DevTools Protocol（CDP）控制 Yakit GUI 展示请求/响应画面并截图。Agent 说"用 Yakit 重放这个包并截图"即可完成全链路自动化。

---

## 背景与动机

在 Web 渗透测试中，测试人员经常在 Burp Suite 中抓取 HTTP 请求包，需要在 Yakit 中复现验证，并把"请求 + 响应"的画面截图存档（用于报告、文档、教学）。

本 MCP 的目标：**一句话完成"抓包 → 重放 → GUI 展示 → 截图"全链路**，让 AI Agent 能直接驱动 Yakit 完成原本需要人工操作的流程。

核心价值：
- **不依赖手工点击**：CDP 自动化等价模拟"填入请求 → 点发送 → 看响应"的完整人工操作
- **协议自适应**：Burp 包往往不带协议信息，自动识别 + http/https 双试探
- **截图三级降级**：任何环境下都能拿到"请求+响应"画面

## 功能总览

| 能力 | 说明 |
|------|------|
| 重放 | 原始 HTTP 报文 → Yakit Web Fuzzer 引擎（`/ypb.Yak/HTTPFuzzer`），返回状态码/响应头/响应体/耗时 |
| 协议识别 | Host `:443`/path `https://` → https；`:80`/`http://` → http；无线索 → unknown |
| 协议双试探 | unknown 时 http + https 各发一遍（对应 Yakit"强制 HTTPS"勾选/不勾选） |
| GUI 联动 | 重放结果写入流量库（`ConvertFuzzerResponseToHTTPFlow`），GUI「流量记录」实时可见 |
| CDP 控制 | 自动化：打开 Web Fuzzer 页面 → 新开干净 tab → 填入请求 → 点发送 → 截图 |
| HTTPS 开关同步 | `sync_gui_https` 同步 Web Fuzzer 的"强制 HTTPS"开关，截图真实反映勾选状态 |
| 截图三级降级 | CDP 页面级高清 → PrintWindow 窗口截图（无视遮挡）→ PIL 渲染兜底 |
| 批量重放 | JSON 数组批量发包 |
| 历史查询 | 查引擎库中的 HTTP 流量记录 |
| 报文解析 | 提取 method/host/headers/body/协议线索 |

## 快速开始

### 环境要求

- Windows（本工具面向 Windows + Yakit 桌面版）
- Python 3.11+
- Yakit 桌面版（`D:\My_apps\Yakit\Yakit.exe` 或自动探测）

### 安装

```bash
pip install -r requirements.txt
```

### 启动 MCP Server

```bash
python -m yakit_mcp.server
```

（stdio 模式，由 Reasonix / Claude 等 MCP 客户端自动拉起）

### 调用示例

```python
# 用户场景: 重放 Burp 复制的包 + 截图
yakit_replay(
    packet="POST /api/login HTTP/1.1\nHost: target.com\nContent-Type: application/json\n\n{\"user\":\"admin\"}",
    auto_protocol=True,      # 自动识别 http/https
    try_both=True,           # unknown 时双协议各发一次
    save_to_gui=True,        # 写入流量库（GUI 历史可见）
    capture=True,            # 重放后截图（返回 base64 + PNG 文件）
)
```

返回 JSON 结构：

```json
{
  "ok": true,
  "protocol_detected": "https",
  "selected_protocol": "https",
  "status_code": 200,
  "url": "https://target.com/api/login",
  "duration_ms": 120,
  "response_raw": "HTTP/1.1 200 OK\r\n...",
  "user_visible": true,
  "flow": {"id": 51},
  "capture": {
    "mode": "cdp",
    "saved_path": "C:\\Users\\...\\screenshots\\yakit_cdp_20260809_010744.png",
    "image_base64": "..."
  }
}
```

## 协议识别与双试探（重要）

### 识别规则

| 线索 | 判定 |
|------|------|
| Host 带 `:443` | https |
| Host 带 `:80` | http |
| Request 行 path 是 `https://` | https |
| Request 行 path 是 `http://` | http |
| `__yakit_is_https: true`（Yakit 复制包标注） | https |
| **无任何线索** | **unknown（推荐 try_both=True）** |

> HTTPS 站点抓的 Burp 包 Host 往往不写端口，无法判断协议 → **必须双试**。这是渗透测试中的常见场景，也是本工具默认推荐 `try_both=True` 的原因。

### 双端尝试

`try_both=True` 时：
1. 先以 `http` 发一次（`FuzzerRequest.IsHTTPS=false`）
2. 再以 `https` 发一次（`FuzzerRequest.IsHTTPS=true`）
3. 返回 `attempts[]` 包含两次的完整明细

### GUI 开关同步

Web Fuzzer 界面的"强制 HTTPS"开关（`.ant-switch`，默认勾选）通过 CDP 自动同步：
- 尝试 http 时 → 关掉开关
- 尝试 https 时 → 打开开关
- 截图真实反映勾选状态（截图存档时能看出用的是哪个协议）

## CDP 控制架构

Yakit GUI 是 Electron 应用，本工具以 `--remote-debugging-port=9333` 启动它，通过 Chrome DevTools Protocol 完全自动化控制：

```
yakit_mcp.cdp
├── open_webfuzzer()            打开 Web Fuzzer 页面（弹窗自适应：项目管理/升级提示）
├── cdp_new_webfuzzer_tab()     新开干净 tab（数字 tab 右侧 + 按钮）
├── cdp_fill_and_send()         填入请求包（CDP Input.insertText）→ 点"发送请求"
├── cdp_set_https_switch()      "强制 HTTPS"开关状态
└── cdp_screenshot()            页面级高清截图
```

### 关键细节

**弹窗自适应**：首次启动有"项目管理"引导（点 `[default]` 进入项目）和升级提示弹窗（点"取 消"），CDP 自动循环处理直到主界面。

**Tab 管理**：
- 新增：Web Fuzzer 多实例 tab 栏（数字（如 123456）右侧 `+` 按钮）→ 新开空白编辑器
- 关闭：点击 tab 的 `×` 关闭按钮（防止小窗口越开越多导致 Yakit 卡顿）
- 每个请求使用新 tab，避免向旧编辑器追加导致请求体混乱

**Monaco 编辑器**：
- `textarea.inputarea` 是输入代理（value 不可信）
- 直接用 `Input.insertText` 模拟真实键盘输入最可靠
- 通过 `.view-line` DOM 读取渲染内容验证

## 截图三级降级

| 优先级 | 方式 | mode | 特点 |
|--------|------|------|------|
| 1 | CDP `Page.captureScreenshot` | `cdp` | 1923×2315 页面级高清，最清晰 |
| 2 | PrintWindow 直接 Win32 绘制窗口 | `window` | **无视其他窗口遮挡**，无需把 Yakit 置顶级 |
| 3 | PIL 渲染 Web Fuzzer 风格图 | `rendered` | GUI 不可见时兜底，永远有图 |

所有 mode 均返回：
- `image_base64`（MCP image content，Agent 可见）
- `saved_path`（PNG 文件，存档/文档用）

保存目录默认 `%LOCALAPPDATA%\yakit-mcp\screenshots\`，可用 `capture_output_dir` 指定。

## 引擎管理

### 引擎来源

- 优先：Yakit 上位目录 `bins/yak_windows_amd64.exe`（若已解压）
- 否则：从 `bins/yak.zip` 自动解压到 `%LOCALAPPDATA%\yakit-mcp\engine\`
- 环境变量：`YAKIT_ENGINE`（指定 exe）、`YAKIT_HOME`（数据目录）

### 启动方式

- **GUI 未运行**：MCP 自动独立启动引擎（`yak_windows_amd64.exe grpc --port 10053`），重放 + 入库照常
- **GUI 已运行**：GUI 自带引擎占 10053，MCP 直接复用（联动），重放内容实时出现在界面

### gRPC 关键接口

| 接口 | 用途 |
|------|------|
| `/ypb.Yak/HTTPFuzzer` | 重放（FuzzerRequest → stream FuzzerResponse） |
| `/ypb.Yak/ConvertFuzzerResponseToHTTPFlow` | 入库（GUI 可见） |
| `/ypb.Yak/QueryHTTPFlows` | 历史流量查询 |
| `/ypb.Yak/SetCurrentProject` / `GetDefaultProjectEx` | 项目管理（CDP 引导） |

proto 从 Yakit GUI `app.asar` 提取（`protos/grpc.proto`），用 `grpc_tools.protoc` 生成 Python 类。

## 项目结构

```
yakit-mcp/
├── README.md            # 本文档
├── SKILL.md             # Agent Skill（触发词 + 使用流程）
├── requirements.txt     # 依赖
├── protos/
│   └── grpc.proto       # Yakit gRPC 协议定义（从 app.asar 提取）
├── yakit_mcp/           # MCP Server（Python 包）
│   ├── server.py        # 入口 + 7 个 MCP 工具
│   ├── engine.py        # 引擎管理 + 重放 + 协议识别 + 入库
│   ├── cdp.py           # CDP 控制 GUI（开页/新tab/填包/发送/HTTPS开关/截图）
│   ├── capture.py       # PrintWindow 窗口截图
│   └── render.py        # PIL 渲染兜底
└── tests/               # 自测脚本
```

## 部署方式

### MCP 注册（config.toml）

```toml
[[plugins]]
name    = "yakit-mcp"
type    = "stdio"
command = "python"
args    = ["C:\\...\\yakit-mcp\\yakit_mcp\\server.py"]
```

### Skill 部署

`SKILL.md` 放到 skills 目录（触发词自动发现）。

## 已知限制（v0.1-beta）

- 新增/关闭 Tab 按钮（`+`/`×`）依赖 hover 显示，已实现多级查找逻辑，需在 GUI 长时间运行的真实环境完整验证
- Yakit 首次启动的引导弹窗（项目管理/版本提示）已自适应处理，但极端状态（引擎版本不匹配循环弹窗）可能仍需手动介入一次
- 截图依赖 Yakit GUI 可见（CDP 模式）；GUI 不在时降级为渲染视图

## 开发作者

- 框架：Python MCP SDK（FastMCP）
- 协议：Yakit gRPC（proto 提取自 Yakit GUI app.asgar）
- 截图：CDP / Win32 PrintWindow / PIL