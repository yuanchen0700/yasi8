# Nanobot 部署与文档下载实战记录

> 本文档完整记录了一次在云开发环境中部署 [nanobot](https://github.com/HKUDS/nanobot)（个人 AI 助手）的全部过程，包括：
> 安装、配置 OpenRouter 模型、通过 3002 端口打开 WebUI、解决 HTTPS 下 WebSocket 连接问题、以及为 agent 编写"文档下载"技能。适合作为新手学习参考。

---

## 目录

1. [背景与目标](#1-背景与目标)
2. [安装 nanobot](#2-安装-nanobot)
3. [初始化配置](#3-初始化配置)
4. [配置 LLM Provider（OpenRouter 免费模型）](#4-配置-llm-provideropenrouter-免费模型)
5. [启动 WebUI（3002 端口）](#5-启动-webui3002-端口)
6. [获取对外访问链接](#6-获取对外访问链接)
7. [修复 HTTPS 下 WebSocket 连接失败](#7-修复-https-下-websocket-连接失败)
8. [为 agent 编写 document-download 技能](#8-为-agent-编写-document-download-技能)
9. [整体架构与原理总结](#9-整体架构与原理总结)
10. [常用命令速查表](#10-常用命令速查表)
11. [踩坑记录](#11-踩坑记录)

---

## 1. 背景与目标

在云开发环境（沙箱）中搭建一个可以**通过网页聊天**的 AI 助手：

- 部署 nanobot（约 4000 行代码的超轻量 AI agent 框架）
- 接入 OpenRouter 的免费模型，实现零成本对话
- 通过平台的 **3002 端口预览能力**暴露一个网页，在浏览器里和 agent 对话
- 为了让 agent 交付的文档"可下载"，额外编写了一个 skill

> 核心环境信息：Linux（Debian bookworm）、Python 3.11.2、安装路径 `~/.nanobot/`

---

## 2. 安装 nanobot

### 2.1 官方安装脚本

nanobot 官方提供一键安装脚本：

```bash
curl -fsSL https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.sh | sh
```

**安全实践**：不要盲目执行 `curl | sh`，先下载下来审查脚本内容：

```bash
curl -fsSL https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.sh -o /tmp/nanobot_install.sh
cat /tmp/nanobot_install.sh   # 审查后再执行
```

审查要点：
- 脚本从 PyPI 安装 `nanobot-ai` 包
- 自动检测 `uv` / `pipx` / 虚拟环境，选择隔离安装方式
- 末尾会自动运行交互式向导（可用环境变量 `NANOBOT_SKIP_WIZARD=1` 跳过）

### 2.2 首次执行遇到的问题

```
Error: could not install nanobot from PyPI.
The virtual environment was not created successfully because ensurepip is not available.
```

**原因**：Debian 系统的 Python 默认不带 `venv` 模块，需要单独安装 `python3-venv`。

**解决**：

```bash
apt-get update && apt-get install -y python3-venv
```

> 注意：`apt-get update` 必须先执行，否则可能报 "Package not available"。

### 2.3 正式安装

```bash
NANOBOT_SKIP_WIZARD=1 sh /tmp/nanobot_install.sh
```

安装过程会自动：
1. 创建专用虚拟环境 `~/.nanobot/venv`
2. 在虚拟环境中安装 `nanobot-ai` 及依赖
3. 验证版本：`nanobot v0.3.0`

**关键路径**：

| 内容 | 路径 |
|------|------|
| Python 虚拟环境 | `~/.nanobot/venv/` |
| 配置文件 | `~/.nanobot/config.json` |
| 工作区（agent 运行目录） | `~/.nanobot/workspace/` |
| 启动命令 | `~/.nanobot/venv/bin/python -m nanobot` |

---

## 3. 初始化配置

```bash
~/.nanobot/venv/bin/python -m nanobot onboard
```

输出会提示：
- 创建 `config.json`
- 创建 `AGENTS.md` / `USER.md` / `SOUL.md` 等 agent 人格文件
- 初始化 git 存储的 workspace 和 memory

生成后的 `config.json` 结构（关键部分）：

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "auto",
      "workspace": "~/.nanobot/workspace"
    }
  },
  "providers": {
    "openrouter": { "apiKey": null },
    "deepseek":   { "apiKey": null },
    "openai":     { "apiKey": null }
  },
  "channels": {
    "websocket": { "enabled": true }
  },
  "gateway": {
    "host": "127.0.0.1",
    "port": 18790
  }
}
```

> 默认模型是 `anthropic/claude-opus-4-5`（需要 Anthropic key），此时所有 provider 的 key 都是空的，**必须配置一个可用的模型服务商**才能对话。

---

## 4. 配置 LLM Provider（OpenRouter 免费模型）

### 4.1 选择服务商

本机没有现成的大模型 API Key，选择 **OpenRouter**（聚合多家模型的网关），使用其**免费模型**实现零成本对话。

### 4.2 查询当前可用的免费模型

OpenRouter 有专门的免费模型列表，可以通过 API 实时查询：

```bash
curl -fsSL -H "Authorization: Bearer $YOUR_KEY" https://openrouter.ai/api/v1/models -o /tmp/models.json
```

用 Python 过滤出免费模型（`pricing.prompt == "0"` 或 ID 带 `:free`）：

```python
import json
d = json.load(open('/tmp/models.json'))
free = [m['id'] for m in d['data'] if ':free' in m['id'] or m.get('pricing', {}).get('prompt') == '0']
print('\n'.join(free))
```

本次查询到约 17 个免费模型，其中有一个特殊的 **`openrouter/free`** —— 它是 OpenRouter 的"免费自动路由"，会自动把请求分发给可用的免费模型，适合不想纠结选哪个模型的情况。

### 4.3 写入配置

```python
import json
p = '/root/.nanobot/config.json'
d = json.load(open(p))
d['providers']['openrouter']['apiKey'] = 'sk-or-v1-xxxx'   # 你的 key
d['agents']['defaults']['provider'] = 'openrouter'
d['agents']['defaults']['model'] = 'openrouter/free'
json.dump(d, open(p, 'w'), indent=2, ensure_ascii=False)
```

### 4.4 验证对话可用

```bash
~/.nanobot/venv/bin/python -m nanobot agent -m "hello"
```

返回类似 `Hello! How can I assist you today?` 即表示模型配置成功。

> **安全提示**：API Key 写入的是用户自己提供的 key，不读取、不透传环境中的任何其他密钥。

---

## 5. 启动 WebUI（3002 端口）

### 5.1 启动命令

```bash
~/.nanobot/venv/bin/python -m nanobot webui --port 3002 --no-open --yes
```

参数说明：

| 参数 | 作用 |
|------|------|
| `--port 3002` | WebUI 端口（同时也是 WebSocket 端口） |
| `--no-open` | 不自动打开浏览器（云环境无图形界面） |
| `--yes` | 跳过交互确认（第一次不带 `--yes` 会报 "needs confirmation"） |

### 5.2 启动成功的标志

日志中会出现：

```
WebUI: http://127.0.0.1:3002/#/?bootstrapSecret=...
WebSocket server listening on ws://127.0.0.1:3002/
Gateway health: http://127.0.0.1:18790/health
```

nanobot 架构上分两层：
- **gateway**（网关，端口 18790）：负责消息路由、session 管理、agent 循环
- **WebUI**（端口 3002）：网页前端 + WebSocket 入口，同时提供 HTTP 文件服务

### 5.3 后台运行方式

用 `&` 或 nohup 后台运行时，注意使用工具自带的 **background terminal** 功能管理（不要用 `pkill` 杀进程），保持进程长期驻留。

---

## 6. 获取对外访问链接

云环境里用户无法直接访问 `127.0.0.1:3002`，需要通过平台提供的**端口预览能力**把本地端口暴露成公网 HTTPS 地址。

调用平台预览接口（对应工具 `request_preview`，参数为本地端口号）：

```
请求端口 3002 → 获得 https://3002-xxxx.monkeycode-ai.online
```

验证方式：

```bash
curl -s -o /dev/null -w "%{http_code}" https://3002-xxxx.monkeycode-ai.online/
# 返回 200
```

### WebUI 登录

WebUI 有认证保护，需要在页面输入 **bootstrap secret**（对应配置文件里的 `channels.websocket.tokenIssueSecret`）：

```bash
# 查看 secret
python -c "import json; print(json.load(open('/root/.nanobot/config.json'))['channels']['websocket']['tokenIssueSecret'])"
```

流程：打开网页 → 输入 secret → 进入聊天界面。

---

## 7. 修复 HTTPS 下 WebSocket 连接失败

### 7.1 现象

浏览器打开页面后报错：

```
Failed to construct 'WebSocket': An insecure WebSocket connection may not be initiated from a page loaded over HTTPS.
Couldn't reach nanobot
```

### 7.2 原因分析

- 页面是通过 **HTTPS**（`https://3002-xxx.monkeycode-ai.online`）加载的
- 但 nanobot 后端返回给前端的 WebSocket 地址是 **`ws://`**（明文、不安全）
- 浏览器安全策略禁止：HTTPS 页面不允许发起 `ws://` 连接，必须用 `wss://`

### 7.3 根因定位

前端拿到 WebSocket 地址的流程：

```
前端请求 GET /webui/bootstrap
  ↓
后端返回 {"ws_url": "ws://3002-xxx.monkeycode-ai.online/", ...}
  ↓
前端用这个地址创建 WebSocket
```

后端代码 `_bootstrap_ws_url()` 决定协议：

```python
def _bootstrap_ws_url(self, request):
    proto = request.headers.get('X-Forwarded-Proto', '')
    secure = proto in {'https', 'wss'} or bool(self.config.ssl_certfile)
    scheme = 'wss' if secure else 'ws'
    return f'{scheme}://{host}{path}'
```

后端依赖 HTTP 头 **`X-Forwarded-Proto`** 判断请求是否走了 HTTPS。但平台的预览代理**没有传递这个头**，导致 `secure=False`，于是返回了 `ws://`。

### 7.4 修复方案

直接修改后端源码 `ws_http.py`，增加一条规则：**只要请求来自非 localhost 域名，就强制使用 wss**。

```python
# 修改前
secure = proto in {"https", "wss"} or bool(self.config.ssl_certfile.strip())

# 修改后
secure = proto in {"https", "wss"} or bool(self.config.ssl_certfile.strip())
if not secure and host and not _is_localhost(host):
    secure = True
```

### 7.5 验证修复

```bash
# 1. 重启服务
# 2. 检查 bootstrap 返回的 ws_url 已是 wss
curl -s "https://3002-xxx.monkeycode-ai.online/webui/bootstrap" -H "X-Nanobot-Auth: <secret>"
# → "ws_url": "wss://3002-xxx.monkeycode-ai.online/"

# 3. 用 Python 真实建立一个 wss 连接
import asyncio, json, urllib.request, websockets
tok = json.load(urllib.request.urlopen(...))['token']
async def main():
    async with websockets.connect(f'wss://3002-xxx.monkeycode-ai.online/?token={tok}') as ws:
        print('CONNECTED')
        await ws.send(json.dumps({'type': 'ping'}))
        print(await asyncio.wait_for(ws.recv(), 10))
asyncio.run(main())
# 收到 {"event": "ready", ...} 即成功
```

### 7.6 修复后的效果

刷新页面即可正常对话。此问题本质是**反向代理场景下协议推断**的经典问题：WebSocket 的 `ws`/`wss` 必须与页面 HTTP 协议一致，且需要正确解析代理链路传来的协议头。

---

## 8. 为 agent 编写 document-download 技能

### 8.1 需求

用户让 nanobot 写文档时，**拿不到文件本身**（agent 跑在远端沙箱）。希望把文档变成一个**可下载的网址**。

### 8.2 nanobot 的 skill 机制

- 自定义 skill 放在 **workspace** 下：`<workspace>/skills/<skill-name>/SKILL.md`
- 启动时自动扫描，`name` 和 `description` 决定何时触发
- 可选 `scripts/`（可执行脚本）、`references/`（参考文档）、`assets/`（资源文件）

```
document-download/
├── SKILL.md
└── scripts/
    └── serve_downloads.py
```

### 8.3 SKILL.md 核心内容

```markdown
---
name: document-download
description: 把生成的文档或文件变成可下载的网址... Triggers include "下载", "发我", "给我链接", "download", "send me the file"...
---

# 文档下载链接（Document Download）

## 首选方式：公网上传（最简单可靠）
# tmpfiles.org
curl -sf -F"file=@/path/doc.md" https://tmpfiles.org/api/v1/upload

# litterbox（可设有效期 1h/12h/24h/72h）
curl -sf -F"reqtype=fileupload" -F"time=1h" -F"fileToUpload=@/path/doc.md" \
  https://litterbox.catbox.moe/resources/internals/api.php

## 备选方式：本地文件服务器
python3 scripts/serve_downloads.py --port 8000 --files /path/a.md /path/b.pdf
```

### 8.4 脚本 serve_downloads.py

用 Python 标准库 `http.server` 实现的下载服务器，关键点：

- 响应对每个文件带上 `Content-Disposition: attachment`，**强制浏览器下载**而非打开
- 支持 `--files 文件1 文件2`（精确指定）和 `--dir 目录`（整目录）两种模式
- 根路径 `/` 生成 HTML 文件列表
- 同时实现 `do_GET` 和 `do_HEAD`

### 8.5 技能的实际使用效果

agent 收到"写文档并发我链接"后：
1. 生成文档文件
2. 调用 `curl` 上传到 tmpfiles.org
3. 拿到公开 URL 直接回复用户

### 8.6 可用性测试

实测各公网分享服务（2026-08）：

| 服务 | 状态 |
|------|------|
| tmpfiles.org | 可用（推荐） |
| litterbox.catbox.moe | 可用 |
| 0x0.st | 已关闭上传（503，AI 垃圾上传太多） |
| catbox.moe 主站 | 需 userhash（412） |
| transfer.sh / bashupload.com | 网络不可达 |
| file.io | 301 重定向，不适用 |

---

## 9. 整体架构与原理总结

### 9.1 nanobot 运行架构

```
浏览器（用户）
   │  HTTPS / wss://  (经平台预览代理)
   ▼
WebUI 端口 3002
   │  ① bootstrap 拿 token + ws_url
   │  ② wss WebSocket 长连接（聊天消息）
   ▼
nanobot gateway（端口 18790）
   │  agent 循环、工具调用、session 管理
   ▼
LLM（OpenRouter 免费模型）
```

### 9.2 三条关键链路

| 链路 | 协议 | 说明 |
|------|------|------|
| 网页加载 | HTTPS | 平台预览代理把公网 HTTPS 转发到本地 3002 |
| 聊天 | wss WebSocket | 前端与 gateway 的长连接 |
| 模型调用 | HTTPS (OpenRouter API) | agent 在服务端调用 LLM |

### 9.3 本次解决的核心问题

1. **Debian 缺 venv** → `apt-get install -y python3-venv`
2. **无模型 Key** → 用 OpenRouter 免费模型 `openrouter/free`
3. **HTTPS 页面连不了 ws://** → 后端强制非 localhost 请求使用 wss
4. **用户拿不到文件** → 写 skill 让 agent 生成可下载链接

---

## 10. 常用命令速查表

```bash
# 启动 WebUI（端口 3002，后台运行）
~/.nanobot/venv/bin/python -m nanobot webui --port 3002 --no-open --yes

# 命令行直接和 agent 对话
~/.nanobot/venv/bin/python -m nanobot agent -m "你的问题"

# 查看状态
~/.nanobot/venv/bin/python -m nanobot status

# 查看/修改配置
cat ~/.nanobot/config.json

# 检查 WebUI 健康
curl -s http://127.0.0.1:18790/health

# 本地下载服务器（skill 自带脚本）
python3 ~/.nanobot/workspace/skills/document-download/scripts/serve_downloads.py \
  --port 8000 --files 文档.pdf 报告.md
```

---

## 11. 踩坑记录

| # | 现象 | 原因 | 解决 |
|---|------|------|------|
| 1 | venv 创建失败 ensurepip 不可用 | Debian 未装 python3-venv | `apt-get install -y python3-venv` |
| 2 | `apt-get` 报包不存在 | 源未更新 | 先 `apt-get update` |
| 3 | `webui` 命令报 needs confirmation | 首次需交互确认 | 加 `--yes` |
| 4 | 页面 "Couldn't reach nanobot" | HTTPS 页面连 ws:// 被浏览器拒绝 | 后端非 localhost 强制 wss |
| 5 | bootstrap 返回 ws:// 而非 wss:// | 预览代理未传 X-Forwarded-Proto | 改 `_bootstrap_ws_url` 增加域名判断 |
| 6 | 0x0.st / catbox 上传失败 | 服务已关闭或需认证 | 改用 tmpfiles.org / litterbox |

---

## 附：文件位置汇总

| 内容 | 路径 |
|------|------|
| nanobot 虚拟环境 | `~/.nanobot/venv/` |
| nanobot 配置文件 | `~/.nanobot/config.json` |
| nanobot workspace | `~/.nanobot/workspace/` |
| document-download skill | `~/.nanobot/workspace/skills/document-download/` |
| 被修改的后端源码 | `~/.nanobot/venv/lib/python3.11/site-packages/nanobot/webui/ws_http.py` |
| WebUI 前端产物 | `~/.nanobot/venv/lib/python3.11/site-packages/nanobot/web/dist/` |
