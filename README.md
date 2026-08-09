# yakit-mcp

驱动 Yakit 引擎（gRPC）重放 HTTP 请求包，并通过 CDP 控制 Yakit GUI 展示请求/响应画面并截图。
一句话完成"抓包 → 重放 → GUI 展示 → 截图"全链路自动化。

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![Platform](https://img.shields.io/badge/Platform-Windows-green)
![MCP](https://img.shields.io/badge/MCP-Server-orange)

---

## 目录

- [背景与动机](#背景与动机)
- [功能总览](#功能总览)
- [快速开始](#快速开始)
- [工具清单](#工具清单-43-个)
- [协议识别与双试探](#协议识别与双试探)
- [完整链路工作流](#完整链路工作流)
- [截图方案](#截图方案)
- [Yakit GUI 自动化机制](#yakit-gui-自动化机制)
- [项目结构](#项目结构)
- [部署方式](#部署方式)
- [常见问题](#常见问题)
- [开发路线](#开发路线)

## 背景与动机

在 Web 渗透测试中，测试人员经常在 Burp Suite 中抓取 HTTP 请求包，需要在 Yakit 中复现验证，并把"请求 + 响应"的画面截图存档（用于报告、文档、教学）。

本 MCP 的目标：**一句话完成"抓包 → 重放 → GUI 展示 → 截图"全链路**，让 AI Agent 直接驱动 Yakit 完成原本需要人工操作的流程。

核心价值：
- **不依赖手工点击**：CDP 自动化等价模拟"填入请求 → 点发送 → 看响应"
- **协议自适应**：Burp 包往往不带协议信息，自动识别 + http/https 双试探
- **截图三级降级**：任何环境下都能拿到"请求+响应"画面

## 功能总览

| 能力 | 说明 |
|------|------|
| 重放 | 原始 HTTP 报文 → Yakit Web Fuzzer 引擎（`/ypb.Yak/HTTPFuzzer`） |
| 协议识别 | Host `:443`/path `https://` → https；`:80`/`http://` → http；无线索 → unknown |
| 协议双试探 | unknown 时 http + https 各发一遍（对应 Yakit"强制 HTTPS"勾选） |
| GUI 联动 | 重放结果写入流量库，GUI「流量记录」实时可见 |
| CDP 控制 | 打开 Web Fuzzer → 新开干净 tab → 填请求 → 点发送 |
| 截图三级降级 | CDP 页面级 → PrintWindow 无视遮挡 → PIL 渲染兜底 |
| 历史管理 | 数据库层清空/列出 Web Fuzzer 历史（根治"旧内容残留"） |
| 分组标签 | Web Fuzzer 分组标签的增/查/删 |
| MITM 抓包 | 启动/停止 MITM 监听，增量获取抓到的流量 |
| 主动扫描 | 端口扫描 / 漏洞检测 / 弱口令爆破 / 基础爬虫 |
| 资产查询 | 端口 / 主机 / 域名 / 风险（漏洞）四类资产 |
| 编码工具 | 编解码（53 种方法）/ 自动解码 / URL 提取 |
| 反连 | DNSLog 域名申请与记录查询 / 反连服务器信息 |
| 插件体系 | 插件查询（1599+）/ 插件执行 / 对包执行插件 / 标签列表 |
| 攻防工具 | YSO payload 生成 / 反弹 shell 命令 / WebShell 管理 |
| 批量重放 | JSON 数组批量发包 |
| 报文解析 | 提取 method/host/headers/body/协议线索 |

## 快速开始

### 环境要求

- Windows（面向 Yakit 桌面版）
- Python 3.11+
- Yakit 桌面版（自动探测安装位置，或用 `YAKIT_ENGINE` 指定）

### 安装

```bash
pip install -r requirements.txt
```

### 启动 MCP Server

```bash
# 方式1: 包方式
python -m yakit_mcp.server

# 方式2: 脚本方式（MCP 客户端 config 常用）
python yakit_mcp/server.py
```

### 调用示例

```python
# 重放 Burp 复制的包 + 截图
yakit_replay(
    packet="POST /api/login HTTP/1.1\nHost: target.com\nContent-Type: application/json\n\n{\"user\":\"admin\"}",
    auto_protocol=True,   # 自动识别 http/https
    try_both=True,        # unknown 时双协议各发一次
    save_to_gui=True,     # 写入流量库
    capture=True,         # 重放后截图（base64 + PNG 文件）
)
```

## 工具清单（43 个）

### 核心重放与流量

| 工具 | 说明 |
|------|------|
| `yakit_status()` | 引擎/GUI 状态、版本、路径 |
| `yakit_replay(packet, auto_protocol, try_both, ...)` | **核心**：重放 + 协议双试 + GUI 联动 + 可选截图 |
| `yakit_replay_batch(packets_json, concurrency)` | 批量重放 |
| `yakit_query_flows(keyword, limit)` | 查询历史 HTTP 流量 |
| `yakit_parse_packet(packet)` | 解析报文（method/host/headers/body/协议线索） |
| `yakit_extract_url(packet)` | 从请求包提取 URL |

### GUI 联动与截图

| 工具 | 说明 |
|------|------|
| `yakit_open_webfuzzer(launch_gui)` | CDP 打开 Web Fuzzer 页面 |
| `yakit_open_webfuzzer_with_packet(packet, is_https)` | 官方 IPC 通道新开 tab 填请求 |
| `yakit_capture(window_title, output_dir, prefer_cdp)` | 截取 Yakit 画面（三级降级） |

### 历史与分组管理

| 工具 | 说明 |
|------|------|
| `yakit_clear_history(task_id)` | 数据库层清空 Web Fuzzer 历史 |
| `yakit_list_tasks()` | 列出 Web Fuzzer 历史任务 |
| `yakit_list_labels()` / `yakit_add_label()` / `yakit_delete_label()` | 分组标签增/查/删 |

### MITM 中间人抓包

| 工具 | 说明 |
|------|------|
| `yakit_mitm_start(port, filters)` | 启动 MITM 监听（后台流） |
| `yakit_mitm_stop()` | 停止 MITM |
| `yakit_mitm_status()` | MITM 运行状态 |
| `yakit_mitm_flows(after_id, limit)` | 增量获取 MITM 抓到的流量 |

### 主动扫描

| 工具 | 说明 |
|------|------|
| `yakit_port_scan(targets, ports, mode, concurrent)` | 端口扫描 |
| `yakit_simple_detect(target)` | 漏洞检测（nuclei 引擎） |
| `yakit_start_brute(target, types, username_dict, password_dict)` | 弱口令爆破（26 种类型） |
| `yakit_brute_types()` | 可用爆破类型 |
| `yakit_basic_crawler(target, max_depth, max_urls)` | 基础爬虫 |

### 资产与漏洞查询

| 工具 | 说明 |
|------|------|
| `yakit_query_ports(ip, limit)` | 端口资产查询 |
| `yakit_query_hosts(keyword, limit)` | 主机资产查询 |
| `yakit_query_domains(keyword, limit)` | 域名资产查询 |
| `yakit_query_risks(keyword, severity, limit)` | 漏洞/风险查询 |

### 编码与反连

| 工具 | 说明 |
|------|------|
| `yakit_codec(text, codec_type)` | 编解码（53 种方法） |
| `yakit_codec_methods()` | 可用编解码方法列表 |
| `yakit_auto_decode(data)` | 自动解码（无需指定编码） |
| `yakit_dnslog_domain()` | 申请 DNSLog 反连域名 |
| `yakit_dnslog_query(token)` | 查询 DNSLog 记录 |
| `yakit_reverse_server()` | 全局反连服务器信息 |

### 插件体系

| 工具 | 说明 |
|------|------|
| `yakit_query_plugins(keyword, tags, limit)` | 查询本地插件（1599+） |
| `yakit_exec_plugin(script_name, params)` | 执行插件（按名查 id） |
| `yakit_exec_packet_plugin(script_name, packet)` | 对 HTTP 包执行插件 |
| `yakit_plugin_tags()` | 插件标签列表 |

### 攻防工具

| 工具 | 说明 |
|------|------|
| `yakit_yso_generate(gadget, class_name, options)` | YSO 序列化 payload 生成（dnslog/win_cmd 等） |
| `yakit_yso_gadgets()` | YSO gadget 列表 |
| `yakit_reverse_shell(ip, port, system, shell_type)` | 反弹 shell 命令生成 |
| `yakit_reverse_shell_programs()` | 反弹 shell 程序列表 |
| `yakit_webshell_query(tag, limit)` | WebShell 列表查询 |
| `yakit_webshell_ping(id)` | Ping WebShell（按 id） |

## 协议识别与双试探

### 识别规则

| 线索 | 判定 |
|------|------|
| Host 带 `:443` / path `https://` / `__yakit_is_https=true` | https |
| Host 带 `:80` / path `http://` | http |
| **无任何线索（Burp 抓 HTTPS 站点最常见）** | **unknown → try_both 双试** |

`try_both=True` 时 http + https 各发一次，返回 `attempts[]` 明细 + `selected_protocol`。

## 完整链路工作流

```
用户: "用 Yakit 重放这个包并截图: GET /get?a=1 HTTP/1.1 Host: httpbin.org"
  │
  ▼
① 引擎连接: 探测 GUI 引擎端口(9011) → 抓 local-password → gRPC 认证
② 协议识别: unknown → http/https 双试
③ 重放: HTTPFuzzer 发包 → 200 OK
④ 入库: ConvertFuzzerResponseToHTTPFlow → GUI 流量记录可见
⑤ CDP 操作: window.require('electron').ipcRenderer.invoke('send-to-tab')
   → 新开干净 tab + 填请求（绕开 Monaco，无旧内容残留）
⑥ 点发送: 可见发送按钮 → 等响应 → 切响应 tab
⑦ 截图: CDP 页面级 / PrintWindow 无视遮挡
  │
  ▼
返回: {status, response_raw, attempts[], capture:{image_base64, saved_path}}
```

## 截图方案

| 优先级 | 方式 | mode | 特点 |
|--------|------|------|------|
| 1 | CDP `Page.captureScreenshot` | `cdp` | 1923×1425 页面级高清 |
| 2 | PrintWindow Win32 绘制 | `window` | **无视遮挡**，Yakit 被其他窗口盖住也能截 |
| 3 | PIL 渲染 Web Fuzzer 风格图 | `rendered` | GUI 不可见时兜底 |

所有模式返回 `image_base64` + `saved_path`（PNG 文件）。

## Yakit GUI 自动化机制

本工具逆向分析了 Yakit 前端源码（yaklang/yakit 仓库），确认的关键机制：

1. **GUI 引擎**：`yak grpc --local-password <随机密码> --port 9011`，密码每次启动随机，从进程命令行提取
2. **send-to-tab（新开 tab 填请求）**：Electron 内部 IPC
   ```
   前端: ipcRenderer.invoke('send-to-tab', {type:'fuzzer', data:{isHttps, request, openFlag}})
   主进程: win.webContents.send('fetch-send-to-tab', params)
   渲染进程: addFuzzer(data) → 新开干净 tab 填请求
   ```
   CDP 在渲染进程执行 `window.require('electron').ipcRenderer.invoke(...)` 即可外部触发
3. **旧内容残留**：历史任务存 SQLite（`web_fuzzer_tasks`/`web_fuzzer_configs`），`yakit_clear_history` 数据库层删除根治

### 不打扰用户的设计

- Yakit GUI **常驻打开**（用户正常使用），MCP 全程复用（不杀不重启）
- 窗口被其他软件盖住时：CDP 操作照常 + PrintWindow 截图无视遮挡
- **唯一注意**：窗口不要最小化（最小化冻结 CDP 操作；PrintWindow 仍可用）

## 项目结构

```
yakit-mcp/
├── README.md
├── SKILL.md              # Agent Skill（触发词 + 使用流程）
├── requirements.txt
├── protos/
│   └── grpc.proto        # Yakit gRPC 协议定义（从 app.asar 提取）
├── yakit_mcp/
│   ├── server.py         # 入口 + 43 个 MCP 工具
│   ├── engine.py         # 引擎管理/认证/重放/协议识别/历史管理
│   ├── cdp.py            # CDP 控制 GUI（send-to-tab/填包/发送/截图）
│   ├── capture.py        # PrintWindow 窗口截图
│   └── render.py         # PIL 渲染兜底
└── tests/                # 自测脚本
```

## 部署方式

### Reasonix / MCP 客户端注册

```toml
[[plugins]]
name    = "yakit-mcp"
type    = "stdio"
command = "python"
args    = ["%LOCAL_HOME%\\skills\\mcp\\yakit-mcp\\yakit_mcp\\server.py"]
```

### Skill 部署

`SKILL.md` 放到 skills 目录（触发词自动发现）。

## 常见问题

**Q: 为什么截图是渲染视图（rendered）而不是真实界面？**
A: Yakit GUI 未运行或窗口不可达时降级为 PIL 渲染视图。保持 Yakit 打开即可拿到真实截图。

**Q: Yakit 窗口最小化后 CDP 操作超时？**
A: Electron 最小化冻结渲染。保持窗口非最小化（被其他窗口盖住没关系）。

**Q: 新 tab 填的请求为什么是旧的？**
A: 旧内容在 `web_fuzzer_tasks` 数据库和前端内存。先调 `yakit_clear_history()` 清历史，再用 `send-to-tab` 新开 tab（天然干净）。

## 开发路线

- [x] 引擎 gRPC 认证（9011 local-password）
- [x] 重放 + 协议双试探
- [x] CDP 控制 GUI（send-to-tab 新开 tab）
- [x] 截图三级降级
- [x] 历史管理（数据库层清空）
- [x] 分组标签管理
- [ ] MITM 抓包能力
- [ ] 非 default 项目发包
- [ ] 批量发包的 tab 管理

## 免责声明

本工具仅用于**授权的安全测试**。请勿用于未授权的目标。使用者需自行承担法律责任。
