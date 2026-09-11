#!/usr/bin/env bash
# =============================================================================
# brand9 (yasi-koiyu) - 发行打包脚本
#
# 用法：
#   bash deploy/pack.sh                # 打包到 release/
#   bash deploy/pack.sh --split 500M   # 分割成 ~500MB 的块
#
# 输出：
#   release/brand9-server-YYYYMMDD.tar.gz      （完整包）
#   release/brand9-server-YYYYMMDD.tar.gz.aa   （分割后第1块）
#   release/brand9-server-20260910.tar.gz.ab   （分割后第2块）
#   ...
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"
APP_NAME="brand9"
DATE=$(date +%Y%m%d)
RELEASE_DIR="$SCRIPT_DIR/release"
OUT_BASE="$RELEASE_DIR/${APP_NAME}-server-${DATE}"

SPLIT_SIZE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --split) SPLIT_SIZE="$2"; shift 2 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

mkdir -p "$RELEASE_DIR"

echo "[pack] 打包应用: $SCRIPT_DIR"
echo "[pack] 目标    : ${OUT_BASE}.tar.gz"

tar czf "${OUT_BASE}.tar.gz" \
  --exclude='deploy/pack.sh' \
  --exclude='release' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.venv' \
  --exclude='venv' \
  --exclude='node_modules' \
  --exclude='*.log' \
  --exclude='server.log' \
  --exclude='frp.log' \
  --exclude='monitor.log' \
  --exclude='*.db-journal' \
  --exclude='*.db-wal' \
  --exclude='*.db-shm' \
  --exclude='chrome_profile' \
  --exclude='.brand9.pids' \
  --exclude='*.exe' \
  --exclude='.git' \
  .

SIZE=$(du -sh "${OUT_BASE}.tar.gz" | cut -f1)
echo "[pack] 完成: ${OUT_BASE}.tar.gz  ($SIZE)"
echo "[pack] 解压后目录含: server.js, index.html, admin.html, voice/, brand9.db, deploy/"

# 分割
if [[ -n "$SPLIT_SIZE" ]]; then
  echo "[pack] 分割中 (chunk size: $SPLIT_SIZE) ..."
  split -b "$SPLIT_SIZE" "${OUT_BASE}.tar.gz" "${OUT_BASE}.tar.gz."
  ls -lh ${OUT_BASE}.tar.gz* | awk '{print "  " $NF "  " $5}'
fi
