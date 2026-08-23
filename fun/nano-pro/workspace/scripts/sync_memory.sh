#!/bin/bash
# 同步线上 nanobot 聊天记忆到 gitee 基线仓库，由 post-commit hook 自动推送。
# 手动执行：/root/.nanobot/workspace/scripts/sync_memory.sh
set -euo pipefail

SRC="$HOME/.nanobot/workspace/memory"
DEST="/workspace/yasi/fun/nano-pro/workspace/memory"
LOG="/tmp/nanobot-memory-sync.log"

if [ ! -d "$SRC" ] || [ ! -d "$DEST" ]; then
  echo "[sync_memory] missing dir: SRC=$SRC DEST=$DEST at $(date)" >> "$LOG"
  exit 1
fi

if diff -r "$SRC" "$DEST" >/dev/null 2>&1; then
  echo "[sync_memory] no changes at $(date)" >> "$LOG"
  exit 0
fi

cp -a "$SRC"/. "$DEST"/
cd /workspace/yasi || exit 1
git add fun/nano-pro/workspace/memory
if git diff --cached --quiet; then
  echo "[sync_memory] copied but no git diff at $(date)" >> "$LOG"
  exit 0
fi

if git commit -m "sync(nano-pro): update chat memory" >/dev/null 2>&1; then
  echo "[sync_memory] committed at $(date)" >> "$LOG"
else
  echo "[sync_memory] commit FAILED at $(date)" >> "$LOG"
  exit 1
fi
