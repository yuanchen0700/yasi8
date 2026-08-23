---
name: document-download
description: 把生成的文档或文件变成可下载的网址，让用户通过链接下载而不是只能看到文件路径。Use when the user asks to receive a document/file as a downloadable URL, or when you generate a report, notes, or any artifact the user cannot directly access. Triggers include "下载", "发我", "给我链接", "download", "send me the file", "make it downloadable".
---

# 文档下载链接（Document Download）

把本地文件变成用户可以直接下载的网址。用户在 WebUI 中通常拿不到生成的文件本身，因此交付文档时必须同时给出可下载链接。

## 何时使用

- 用户让你生成报告、笔记、代码文件、PDF 等，说"拿不到文件"、"给我下载链接"、"发我"。
- 你生成了一个文件，用户当前通过网页与你交互，无法访问服务器文件系统。

## 首选方式：本地预览域名（最可靠，优先使用）

平台提供的**端口预览能力**可以把本地端口暴露成公网 HTTPS 域名（例如 `8000-xxxx.monkeycode-ai.online`）。把文件放进一个静态文件服务器的目录，再给用户**同一个域名**下的文件链接即可下载。

为什么优先：实测公网分享服务（tmpfiles.org 等）在部分网络区域会被屏蔽（`ERR_CONNECTION_ABORTED`），而预览域名和 WebUI 同源，用户只要能打开页面就一定能下载文件。

### 步骤

1. 把待下载文件放到一个静态目录，例如 `/path/to/docs/`。
2. 用 `exec` 工具启动静态文件服务器（后台运行）：
   ```bash
   python3 -m http.server 8000 --bind 0.0.0.0 --directory /path/to/docs
   ```
   若该目录已有运行中的服务器（例如文档站），直接复用，跳过启动。
   ```
3. 通过平台**端口预览能力**为 8000 端口申请对外 URL（对应平台的 `request_preview` 工具），得到 `https://8000-xxxx.monkeycode-ai.online`。
4. 给用户的下载链接为：`https://8000-xxxx.monkeycode-ai.online/<文件名>`。
5. 校验：`curl -sI <下载链接>` 返回 `200` 即确认可下载。
6. 若文件带中文名等特殊字符，URL 需编码。

### 推荐脚本

仓库内 `scripts/serve_downloads.py` 提供更友好的下载服务器（自动带 `Content-Disposition: attachment`，浏览器直接触发下载），也适合需要把多个文件暴露成下载列表的场景：

```bash
python3 scripts/serve_downloads.py --port 8000 --files /path/a.md /path/b.pdf
# 或整个目录：
python3 scripts/serve_downloads.py --port 8000 --dir /path/to/dir
```

启动后同样通过平台预览能力把 8000 端口暴露成对外 URL，下载链接为 `https://<预览域名>/<文件名>`。

### 注意

- 文件必须位于静态服务器的 `--directory` 目录内，否则 404。
- 若平台预览能力不可用，或需要跨网络长期分享，回退到下方的公网上传方式。

## 备选方式：公网上传

当本地预览不可用时，用 `exec` 工具将文件上传到公网临时文件分享服务，拿到公开下载 URL。

已验证服务（实测于 2026-08）：

1. **tmpfiles.org**（无需登录，但部分网络区域可能被屏蔽）
   ```bash
   curl -sf -F"file=@/path/to/document.md" https://tmpfiles.org/api/v1/upload
   ```
   返回 JSON：`{"status":"success","data":{"url":"https://tmpfiles.org/xxx/document.md"}}`
   直接使用 `data.url` 作为下载链接。

2. **litterbox.catbox.moe**（catbox 临时版，可设有效期）
   ```bash
   curl -sf -F"reqtype=fileupload" -F"time=72h" -F"fileToUpload=@/path/to/document.md" https://litterbox.catbox.moe/resources/internals/api.php
   ```
   返回一行 URL，如 `https://litter.catbox.moe/xxx.md`。`time` 支持 `1h`/`12h`/`24h`/`72h`。

注意：`0x0.st`（当前关闭上传）、`catbox.moe` 主站（需 userhash）、`transfer.sh`（不可达）、`bashupload.com`（不可达）不可依赖。若首个服务失败，依次换下一个。

### 上传步骤

1. 确认文件存在：`ls -la <file>`。
2. 按上面命令上传（litterbox 上传可能较慢，给足超时）。
3. 解析返回 URL，回复用户时直接给完整可点击链接，并说明文件内容摘要和有效期。
4. 上传后校验：`curl -sI <url>` 返回 `200` 即确认可下载。

### 敏感信息提醒

- 只上传用户要求的非敏感文档。
- 临时分享链接有有效期（tmpfiles.org 通常 1 小时，litterbox 依 `time` 参数），回复时提醒用户尽快下载。

## 交付规范

1. 生成文档后，主动转换为可下载链接再回复。
2. 回复格式：
   - 文档内容简介（一两句）
   - 下载链接（完整 URL）
   - 有效期说明（如适用）
3. 多文件时逐个提供，逐行列出文件名 + 链接。
4. 下载链接失败时不要放弃：先校验本地服务器进程与目录路径，再依次尝试其他渠道，并告知用户。
5. 不要在回复中只写 `127.0.0.1` 或 `localhost` 地址（用户机器访问不到），除非确认用户与本机同一网络。
