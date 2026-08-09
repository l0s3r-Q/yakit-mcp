---
name: yakit-mcp
description: Yakit 重放与截图。当用户要求"用Yakit重放这个包"、"复现burp包"、"Yakit发包"、"重放后截图"、"把包丢进Yakit"、"Yakit抓包放包"、"截取Yakit窗口"时使用。MCP 工具: yakit_replay/yakit_replay_batch/yakit_capture/yakit_query_flows/yakit_status/yakit_parse_packet。
---

# Yakit 重放 + 截图 Skill

驱动本机 Yakit 引擎（gRPC 10053）重放 HTTP 包，可选联动 Yakit GUI 显示并截图。

## 适用场景

- 用户在测试中获取了 Burp 包（原始 HTTP 报文），要求"用 Yakit 复现/重放"
- 要求"重放后截图"，需要看到 Response 画面（存文档）
- 批量重放多个包
- 查询历史流量

## 核心流程

1. **拿到 Burp 包文本**（用户粘贴的原始报文，含请求行/Headers/空行/Body）
2. 调 `yakit_replay(packet=..., auto_protocol=True, try_both=True, sync_gui_https=True, capture=True)`：
   - 引擎自动启动（若 Yakit GUI 未运行，独立引擎发包）
   - 自动识别协议（http/https/unknown），unknown 时双协议各发一次
   - `save_to_gui=True` 写入 Yakit 流量库（GUI 的流量记录可见）
   - `capture=True` 时：CDP 打开 Web Fuzzer → **新开干净 tab（123456 右侧 +）** → 填请求 → 点发送 → 截图
3. 返回结构：协议识别结果 + 各协议尝试明细 + 状态码/响应头/响应体/耗时 + 截图 base64 + 截图文件路径

## CDP 全自动 GUI 操作（capture=True 时）

1. **启动/连接 GUI**：`Yakit.exe --remote-debugging-port=9333 --remote-allow-origins=*`（Chrome 118+ 必须带 allow-origins，否则 WebSocket 403）
2. **进入项目**：首次启动有"项目管理"引导 → 点 `[default]` 进入项目；升级提示弹窗点"取 消"
3. **打开 Web Fuzzer**：点左侧导航"Web Fuzzer"
4. **新开干净 tab**：Web Fuzzer 多实例标签栏（数字 tab 如 123456 右侧）的 `+` 按钮 → 新开空编辑器（**解决旧请求内容残留**）
5. **填请求**：CDP `Input.insertText` 模拟键盘输入（Monaco 编辑器的 textarea 是输入代理，直接 set value 不生效）
6. **点发送**：点"发送请求"按钮（等价手动操作）
7. **截图**：CDP `Page.captureScreenshot` 页面级高清（1923×1425）
8. **关闭 tab**：截图后自动点 tab 的 × 关闭新开的小窗口（防止窗口堆积卡顿）

## 工具清单（43 个，全功能版）

### 核心重放与流量
| 工具 | 作用 |
|------|------|
| `yakit_status()` | 引擎/GUI 状态检查 |
| `yakit_replay(packet, auto_protocol, try_both, sync_gui_https, proxy, timeout, save_to_gui, capture, ...)` | 重放单包（核心，全自动链路） |
| `yakit_replay_batch(packets_json, concurrency)` | 批量重放 |
| `yakit_query_flows(keyword, limit)` | 查询历史流量 |
| `yakit_parse_packet(packet)` | 解析报文（method/host/headers/body/协议线索） |
| `yakit_extract_url(packet)` | 从请求包提取 URL |

### GUI 联动与截图
| 工具 | 作用 |
|------|------|
| `yakit_open_webfuzzer(launch_gui)` | 用 CDP 打开 Yakit GUI 的 Web Fuzzer 页面 |
| `yakit_open_webfuzzer_with_packet(packet, is_https)` | 官方 IPC 通道新开干净 tab 填请求 |
| `yakit_capture(window_title, output_dir, prefer_cdp)` | 截取 Yakit 画面（CDP → PrintWindow → 渲染三级降级） |

### 历史与分组
| 工具 | 作用 |
|------|------|
| `yakit_clear_history(task_id)` | 数据库层清空 Web Fuzzer 历史（根治旧内容残留） |
| `yakit_list_tasks()` | 列出历史任务 |
| `yakit_list_labels()` / `yakit_add_label()` / `yakit_delete_label()` | 分组标签增/查/删 |

### MITM 抓包
| 工具 | 作用 |
|------|------|
| `yakit_mitm_start(port, filters)` | 启动 MITM 监听 |
| `yakit_mitm_stop()` / `yakit_mitm_status()` | 停止/状态 |
| `yakit_mitm_flows(after_id, limit)` | 增量获取抓到流量 |

### 主动扫描
| 工具 | 作用 |
|------|------|
| `yakit_port_scan(targets, ports)` | 端口扫描 |
| `yakit_simple_detect(target)` | 漏洞检测（nuclei） |
| `yakit_start_brute(target, types)` / `yakit_brute_types()` | 弱口令爆破 |
| `yakit_basic_crawler(target)` | 基础爬虫 |

### 资产查询
| 工具 | 作用 |
|------|------|
| `yakit_query_ports()` / `yakit_query_hosts()` / `yakit_query_domains()` / `yakit_query_risks()` | 端口/主机/域名/风险（漏洞） |

### 编码与反连
| 工具 | 作用 |
|------|------|
| `yakit_codec(text, codec_type)` / `yakit_codec_methods()` | 编解码（53 种方法） |
| `yakit_auto_decode(data)` | 自动解码 |
| `yakit_dnslog_domain()` / `yakit_dnslog_query(token)` | DNSLog 反连 |
| `yakit_reverse_server()` | 反连服务器信息 |

### 插件体系
| 工具 | 作用 |
|------|------|
| `yakit_query_plugins(keyword, tags)` | 查询本地插件（1599+） |
| `yakit_exec_plugin(script_name, params)` | 执行插件 |
| `yakit_exec_packet_plugin(script_name, packet)` | 对包执行插件 |
| `yakit_plugin_tags()` | 插件标签列表 |

### 攻防工具
| 工具 | 作用 |
|------|------|
| `yakit_yso_generate(gadget, class_name, options)` / `yakit_yso_gadgets()` | YSO payload 生成 |
| `yakit_reverse_shell(ip, port)` / `yakit_reverse_shell_programs()` | 反弹 shell 命令 |
| `yakit_webshell_query(tag)` / `yakit_webshell_ping(id)` | WebShell 管理 |

## 截图三级降级策略

1. **CDP 截图**（`mode: "cdp"`）：Electron 页面级截图，1923×1425 高清，最清晰——GUI 以 `--remote-debugging-port=9333 --remote-allow-origins=*` 启动时可用
2. **PrintWindow 窗口截图**（`mode: "window"`）：无视遮挡/最小化，截窗口内容
3. **渲染视图**（`mode: "rendered"`）：GUI 不可见时 PIL 绘制 Web Fuzzer 风格图，保证链路永远可用

## 关键参数

- `packet`: 原始 HTTP 报文（Burp Repeater 复制格式即可）
- `auto_protocol`: 自动识别协议（默认 True）——Host 带 :443 / path 是 https:// 判 https；:80 / http:// 判 http；无线索判 unknown
- `try_both`: unknown 时 http+https 各发一次（默认 False，推荐 True——HTTPS 站点抓的 Burp 包 Host 往往无端口，必须双试）
- `is_https`: 手动指定（默认 False，auto_protocol 优先）
- `capture`: True 时重放后截图（需 Yakit GUI 窗口可见）
- `capture_title`: 窗口标题关键词，默认 "Yakit"
- `capture_output_dir`: 截图保存目录，默认 `%LOCALAPPDATA%\yakit-mcp\screenshots`
- `save_to_gui`: 默认 True，重放进流量库

返回: `protocol_detected`（识别结果）+ `attempts`（各协议尝试结果）+ `selected_protocol`（选中协议）

## 协议识别规则

| 线索 | 判定 |
|------|------|
| Host 带 `:443` | https |
| Host 带 `:80` | http |
| 请求行 path 是 `https://` | https |
| 请求行 path 是 `http://` | http |
| Yakit 复制包带 `__yakit_is_https: true` | https |
| **无任何线索** | **unknown（recommend try_both=True 双试）** |

## 注意事项

1. **截图需要 Yakit GUI 窗口真实可见**（不能最小化到托盘）；若 GUI 未开，capture 返回 `ok:false` 但重放结果仍有效
2. **GUI 未运行时的重放**：MCP 自动独立启动引擎（10053），重放+入库照常；GUI 之后启动可见历史
3. **GUI 运行时的重放**：GUI 自带引擎占用 10053，MCP 直接复用其引擎（同一端口），重放内容实时出现在 GUI 的「Web Fuzzer 历史」和「流量记录」
4. **HTTPS 包**：Burp 复制的包需确认 scheme；若包内无标注，默认按 http，可用 `is_https=True` 显式指定
5. 截图返回 base64（Agent 直接看图）+ PNG 文件（用户贴文档）

## 示例

```
用户: 用Yakit重放这个包并截图: POST /api/login HTTP/1.1\nHost: target.com\n...\n
Agent: yakit_replay(packet="...", is_https=True, capture=True)
  → 返回 status_code/响应 + 截图
```

## 部署信息

- MCP: `%LOCAL_HOME%\skills\mcp\yakit-mcp\`（python -m yakit_mcp.server）
- 真源: `%WORKSPACE%\yakit-mcp\`
- 引擎: Yakit 安装目录 `%YAKIT_DIR%\bins\yak.zip`（自动解压到 `%LOCALAPPDATA%\yakit-mcp\engine\`）
- proto: 从 Yakit GUI `app.asar` 提取（`protos/grpc.proto`）

## 高级能力（v0.3+ 新增 15 工具）

- **异步任务**: `yakit_scan_start`（后台扫描立即返回）→ `yakit_task_status` / `yakit_task_wait` / `yakit_task_list`
- **一键扫描**: `yakit_quick_scan(target)`（端口扫描+指纹+资产自动带出）
- **通用执行**: `yakit_exec_script(code)`（Yak Runner 等价，Agent 可写任意 Yak 代码）
- **批量插件**: `yakit_exec_batch_packet_plugin("插件A,插件B", packet)`（单包多插件）
- **CSRF**: `yakit_generate_csrf_poc(packet)` 生成 POC HTML
- **取证**: `yakit_export_flows(keyword)` 导出流量（含请求/响应）
- **字典**: `yakit_payload_save(group, content)` / `yakit_payload_query(group)`
- **WebShell**: `yakit_webshell_create/info/generate`
- **反连**: `yakit_reverse_configure(tunnel_addr)`

## 错误信息人话化

引擎原始错误（UNAUTHENTICATED/panic 等）会自动翻译为可读提示（`reason_human` 字段）。
