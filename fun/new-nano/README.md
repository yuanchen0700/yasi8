# new-nano - 全新 nanobot 独立实例

基于官方源码（HKUDS/nanobot）在仓库内独立安装的 nanobot 实例，与既有 `~/.nanobot` 实例完全隔离。

## 目录结构

- `nanobot/` - GitHub 克隆的 nanobot 源码（未入库，可随时 `git clone --depth 1 https://github.com/HKUDS/nanobot.git nanobot` 重新获取）
- `.venv/` - 独立 Python 虚拟环境（未入库）
- `config.json` - 实例配置（含 API key，未入库）
- `workspace/` - 实例运行数据与记忆（未入库）

## 安装

```bash
git clone --depth 1 https://github.com/HKUDS/nanobot.git nanobot
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e nanobot
```

## 启动

```bash
.venv/bin/nanobot webui \
  --config ./config.json \
  --workspace ./workspace \
  --port 3005 \
  --gateway-port 18793 \
  --no-open --yes
```

- WebUI: http://127.0.0.1:3005
- Gateway 健康检查: http://127.0.0.1:18793/health
- 仅启用 WebUI 渠道，未接飞书/其他 IM

## 服务登记页

实例与同机其他服务的访问地址、密钥统一登记在 `fun/monkey-html/index.html`（含 Bootstrap 密钥与 API Token 获取方式）。

预览地址: https://8020-66dec030646bda22.monkeycode-ai.online
本机地址: http://127.0.0.1:8020

> 注意：`fun/monkey-html/index.html` 含访问密钥，已加入 `.gitignore`，不入库。

## 配置要点

- 基于旧实例 `~/.nanobot/config.json` 复制生成，保留 openrouter/free 模型与 provider 凭据
- websocket 绑定 `0.0.0.0:3005`，`tokenIssueSecret` 为随机生成，用于 WebUI 首次连接认证
- `public_ws_url` 固定为 `wss://3005-<host>/`：当 WebUI 经 HTTPS 反向代理访问时，代理不会透传 `X-Forwarded-Proto`，bootstrap 默认返回 `ws://` 会导致浏览器报 "insecure WebSocket"；设置该项后 bootstrap 直接返回 wss 地址，经代理升级后可达（实测 wss 握手 + token 认证均正常）
- gateway `0.0.0.0:18793`，飞书等 IM 渠道全部禁用
