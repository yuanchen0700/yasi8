# nano-pro

nanobot（HKUDS/nanobot v0.3.0）的本地化改造基线仓库。

基于线上 `~/.nanobot` 部署全量拷贝而来，用于后续升级改进，改动全部通过 git 追踪，可随时回退。

## 目录结构

```
nano-pro/
├── nanobot_pkg/          # nanobot 包源码（site-packages/nanobot 全量拷贝）
├── workspace/            # agent 工作区（人格文件、技能、记忆、cron）
├── config.example.json   # 配置模板（敏感项已脱敏为 <REDACTED>）
├── requirements.txt      # 完整依赖清单（pip freeze）
├── install.sh            # 一键安装到 ~/.nanobot/venv
└── README.md
```

## 部署

```bash
# 1. 在目标环境安装 Python 3.11 + venv
apt-get update && apt-get install -y python3-venv

# 2. 一键安装（自动创建 venv、安装依赖、写入 config、同步 workspace）
bash install.sh

# 3. 启动 WebUI（端口 3002）
~/.nanobot/venv/bin/python -m nanobot webui --port 3002 --no-open --yes
```

## 本项目已做的改动（相对上游 nanobot v0.3.0）

1. **HTTPS/WebSocket 修复**：`nanobot_pkg/webui/ws_http.py` 中 `_bootstrap_ws_url` 增加"非 localhost 域名强制 wss"逻辑，解决预览代理不传 `X-Forwarded-Proto` 导致 HTTPS 页面连不上 `ws://` 的问题。
2. **聊天界面消息时间戳**：`nanobot_pkg/web/dist/assets/index-BEnF9_Aa.js` 在用户消息气泡下方与 AI 回复操作区显示发送时间（复用前端 `wl()` 时间格式化函数）。
3. **WebUI 资源缓存刷新**：`nanobot_pkg/web/dist/index.html` 中 JS/CSS 引用追加 `?v=20260805` 版本参数。

## 改进流程

1. 直接修改本仓库文件（如 `nanobot_pkg/`）
2. `git add . && git commit`，push 到 gitee（post-commit hook 自动推送）
3. 回退：`git revert <commit>` 或 `git reset --hard <commit>` 后重新推送

## 敏感信息

- `config.example.json` 中所有密钥/令牌已脱敏为 `<REDACTED>`，部署时需手动填入真实值
- 真实的 `~/.nanobot/config.json`、venv、media 等不入库
