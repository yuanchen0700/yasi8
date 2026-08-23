# 会话上下文摘要（脱敏版）

> 本文档记录一次云环境任务的上下文要点，所有敏感信息均已脱敏（以 `<xxx>` 占位符代替）。仅用于归档参考，勿将真实凭据提交到公开仓库。

## 任务概览

- 在云开发环境部署 nanobot AI agent，并接入 OpenRouter 免费模型、飞书消息通道、WebUI 与文档下载 skill。
- 将 nanobot 部署实战文档与本次会话上下文摘要归档到 gitee 仓库 `yasi` 的 `fun` 目录。

## 已完成的部署内容

- nanobot v0.3.0 安装（venv：`~/.nanobot/venv`）。
- OpenRouter 免费模型接入（模型标识：`openrouter/free`），实现零成本 LLM 调用。
- WebUI 启动于 3002 端口，secret 已配置。
- 修复 wss 握手问题：修改 `nanobot/webui/ws_http.py` 中 `_bootstrap_ws_url()`，强制非 localhost 场景使用 `wss://`。
- document-download skill 部署于 `~/.nanobot/workspace/skills/document-download/`，含本地预览脚本 `serve_downloads.py`，下载渠道排序为「本地预览域名 → 公网上传（备选）」。
- 部署文档站（HTML 版，含侧边目录、深色模式）。
- 飞书 channel 上线（websockets 依赖需 16.1.1 兼容）。

## 关键决策

- **零成本 LLM**：使用 OpenRouter 免费模型，避免支付费用。
- **wss 修复**：因预览环境走 wss 才能握手，修改后端源码强制非 localhost 使用 wss。
- **文档下载渠道排序**：本地预览域名优先，公网上传（tmpfiles.org / litterbox.catbox.moe）备选；0x0.st 等站点实测不可用。
- **git 身份**：推送 gitee 仓库时使用仓库作者身份（仅仓库级设置，不污染全局）。

## 环境与运行方式

- WebUI 与文档站均以后台终端长驻运行，禁止用 `pkill` 杀进程，使用后台终端管理工具停止。
- 日志文件位置：`/tmp/terminal_term_*.log`（以实际为准）。
- 运行命令示例：`~/.nanobot/venv/bin/python -m nanobot webui --port 3002 --no-open --yes`。

## 敏感信息（均已脱敏，请勿填写真实值）

| 项目 | 占位符 |
|------|--------|
| gitee 访问令牌 | `<GITEE_TOKEN>` |
| OpenRouter API Key | `<OPENROUTER_API_KEY>` |
| WebUI secret | `<WEBUI_SECRET>` |
| 预览/文档站域名 | `<PREVIEW_HOST>` |
| 飞书 appId | `<FEISHU_APP_ID>` |
| 飞书 owner open_id | `<FEISHU_OWNER_OPEN_ID>` |

## 后续待办

- 按需确认是否通过 `webuiAllowRemotePackageInstall` 安装其他可选功能。
- 定期查看飞书 channel 在线日志，确认服务正常运行。
