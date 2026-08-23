#!/bin/bash
# 将仓库 nanobot_pkg 部署覆盖到本机 venv 运行环境（仓库为代码源头）
# 用法：./deploy.sh   # 之后需重启 nanobot 服务生效
set -euo pipefail

NANOBOT_DIR="${NANOBOT_DIR:-$HOME/.nanobot}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG="$SCRIPT_DIR/nanobot_pkg"
SITE="$NANOBOT_DIR/venv/lib/python3.11/site-packages/nanobot"

if [ ! -d "$PKG" ] || [ ! -d "$SITE" ]; then
  echo "错误：PKG=$PKG 或 SITE=$SITE 不存在" >&2
  exit 1
fi

echo "==> 清理旧 __pycache__"
find "$SITE" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true

echo "==> 从仓库覆盖 nanobot 包源码"
cp -r "$PKG/." "$SITE/"

echo "==> 完成。重启服务生效："
echo "    $NANOBOT_DIR/venv/bin/python -m nanobot webui --port 3002 --no-open --yes"
