#!/bin/bash
# nano-pro 一键安装脚本
# 在目标环境安装 nanobot 到 ~/.nanobot，并同步本仓库的源码与配置
set -euo pipefail

NANOBOT_DIR="${NANOBOT_DIR:-$HOME/.nanobot}"
PYTHON="${PYTHON:-python3}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> 安装到 $NANOBOT_DIR"

# 1. 创建虚拟环境
if [ ! -d "$NANOBOT_DIR/venv" ]; then
  echo "==> 创建虚拟环境"
  "$PYTHON" -m venv "$NANOBOT_DIR/venv"
fi

# 2. 安装依赖
echo "==> 安装依赖"
"$NANOBOT_DIR/venv/bin/python" -m pip install --upgrade pip
"$NANOBOT_DIR/venv/bin/python" -m pip install -r "$SCRIPT_DIR/requirements.txt"

# 3. 覆盖安装修改过的 nanobot 包源码
echo "==> 同步 nanobot 包源码"
cp -r "$SCRIPT_DIR/nanobot_pkg/." "$NANOBOT_DIR/venv/lib/python3.11/site-packages/nanobot/"

# 4. 初始化配置（若不存在）
if [ ! -f "$NANOBOT_DIR/config.json" ]; then
  echo "==> 创建配置（从 config.example.json，需要手动填入真实密钥）"
  cp "$SCRIPT_DIR/config.example.json" "$NANOBOT_DIR/config.json"
  echo "    !!! 请编辑 $NANOBOT_DIR/config.json 填入真实 API Key/密钥 !!!"
fi

# 5. 同步 workspace（不覆盖已有会话/记忆）
echo "==> 同步 workspace"
mkdir -p "$NANOBOT_DIR/workspace"
for item in AGENTS.md HEARTBEAT.md SOUL.md USER.md dragging.md prompts scripts skills triggers cron memory; do
  if [ -e "$SCRIPT_DIR/workspace/$item" ]; then
    cp -rn "$SCRIPT_DIR/workspace/$item" "$NANOBOT_DIR/workspace/"
  fi
done

echo "==> 完成。启动命令："
echo "    $NANOBOT_DIR/venv/bin/python -m nanobot webui --port 3002 --no-open --yes"
