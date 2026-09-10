#!/usr/bin/env bash
# =============================================================================
# brand9 (yasi-koiyu) - 服务器一键安装脚本
#
# 用法：
#   sudo ./install.sh                  # 默认配置安装（/opt/yasi-koiyu, user brand9, port 8996）
#   sudo ./install.sh --port 8648      # 指定端口
#   sudo ./install.sh --no-systemd     # 不注册 systemd，仅解压+建用户+npm
#
# 完成后：
#   systemctl start brand9
#   systemctl enable brand9
#   tail -f /var/log/brand9.log
# =============================================================================
set -euo pipefail

# ----------------------------------------------------------- 参数解析
PORT=8996
USE_SYSTEMD=1
APP_DIR=""
APP_USER="brand9"
NODE_PATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)      PORT="$2"; shift 2 ;;
    --user)      APP_USER="$2"; shift 2 ;;
    --node)      NODE_PATH="$2"; shift 2 ;;
    --no-systemd) USE_SYSTEMD=0; shift ;;
    --dir)       APP_DIR="$2"; shift 2 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-$SCRIPT_DIR}"

# ----------------------------------------------------------- 前置检查
echo "============================================================"
echo " brand9 (雅思口语) 安装"
echo " 应用目录 : $APP_DIR"
echo " 系统用户 : $APP_USER"
echo " 监听端口 : $PORT"
echo "============================================================"

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: 请使用 sudo 运行此脚本"
  exit 1
fi

# Node.js >= 22.5
if ! command -v node &>/dev/null; then
  echo "ERROR: node 未安装。请先安装 Node.js >= 22.5"
  echo "  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt-get install -y nodejs"
  exit 1
fi
NODE_VER=$(node -v | sed 's/v//' | cut -d. -f1)
if [[ "$NODE_VER" -lt 22 ]]; then
  echo "ERROR: 需要 Node.js >= 22.x，当前: $(node -v)"
  exit 1
fi
NODE_BIN="${NODE_PATH:-$(command -v node)}"
echo "Node.js: $(node -v)  ->  $NODE_BIN"

# ----------------------------------------------------------- 创建系统用户
if ! id "$APP_USER" &>/dev/null; then
  echo "[1/5] 创建系统用户 $APP_USER ..."
  useradd --system --no-create-home --shell /usr/sbin/nologin "$APP_USER"
else
  echo "[1/5] 用户 $APP_USER 已存在，跳过"
fi

# ----------------------------------------------------------- 权限
echo "[2/5] 设置目录权限 ..."
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 755 "$APP_DIR"
chmod 644 "$APP_DIR"/server.js "$APP_DIR"/index.html "$APP_DIR"/admin.html 2>/dev/null || true
chmod 755 "$APP_DIR"/voice "$APP_DIR"/voice/q "$APP_DIR"/voice/ans 2>/dev/null || true

# ----------------------------------------------------------- 环境文件
echo "[3/5] 检查 .env ..."
if [[ ! -f "$APP_DIR/.env" ]]; then
  echo "  警告: 未发现 .env 文件，已复制 .env.example 作为模板"
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo "  请在启动前编辑 $APP_DIR/.env，填写 RESEND_API_KEY 和邮件配置"
  echo "  （邮件功能可选；不填也可使用管理后台 SMTP 配置）"
fi

# ----------------------------------------------------------- 首次构建（无声）
echo "[4/5] 检查 voice/ 音频文件 ..."
MP3_COUNT=$(find "$APP_DIR/voice" -name "*.mp3" 2>/dev/null | wc -l)
if [[ "$MP3_COUNT" -eq 0 ]]; then
  echo "  警告: voice/ 目录下没有找到 mp3 文件，请确认语音包已包含在包中"
fi
echo "  找到 $MP3_COUNT 个音频文件"

echo "[5/5] 检查 database ..."
if [[ -f "$APP_DIR/brand9.db" ]]; then
  echo "  brand9.db 已存在 ($(( $(stat -c%s "$APP_DIR/brand9.db" ) / 1024 )) KB)"
else
  echo "  警告: brand9.db 不存在，首次启动将创建空库"
fi

# ----------------------------------------------------------- 注册 systemd 服务
if [[ "$USE_SYSTEMD" -eq 1 ]]; then
  echo ""
  echo "[systemd] 注册服务 ..."

  cat > /etc/systemd/system/brand9.service <<EOF
# brand9 - IELTS Speaking Practice Server
[Unit]
Description=brand9 IELTS Speaking Practice Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
Environment=PORT=$PORT
ExecStart=$NODE_BIN server.js
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=brand9

# 安全加固
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$APP_DIR
EOF

  systemctl daemon-reload
  echo "  服务已注册: brand9"
  echo ""
  echo "============================================================"
  echo " 安装完成！"
  echo "------------------------------------------------------------"
  echo " 启动服务："
  echo "   sudo systemctl start brand9"
  echo "   sudo systemctl enable brand9   # 开机自启"
  echo ""
  echo " 查看状态："
  echo "   sudo systemctl status brand9"
  echo "   journalctl -u brand9 -f"
  echo ""
  echo " 博客地址: http://<服务器IP>:$PORT/"
  echo " 管理后台: http://<服务器IP>:$PORT/admin"
  echo ""
  echo " 配置文件: $APP_DIR/.env"
  echo "------------------------------------------------------------"
  echo " 注意：请在启动前先编辑 $APP_DIR/.env 填写邮件配置（可选）"
  echo "============================================================"
else
  echo ""
  echo "============================================================"
  echo " 安装完成（--no-systemd 模式）"
  echo "------------------------------------------------------------"
  echo " 手动启动："
  echo "   cd $APP_DIR && BRAND9_PORT=$PORT $NODE_BIN server.js"
  echo ""
  echo " 或使用守护脚本："
  echo "   bash $APP_DIR/start_project.sh"
  echo "------------------------------------------------------------"
  echo " 博客地址: http://<服务器IP>:$PORT/"
  echo " 管理后台: http://<服务器IP>:$PORT/admin"
  echo "============================================================"
fi
