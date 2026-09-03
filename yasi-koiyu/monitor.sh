#!/usr/bin/env bash
# yasi-koiyu 守护/监控脚本
# 周期探测 8996 端口健康状态；一旦进程死亡或僵死：
#   1. 向 monitor.log 写入死亡时间（时刻）与原因
#   2. 调用 health-check.sh --service yasi-koiyu 自动拉起
#   3. 记录恢复/重启结果
#
# 用法:
#   bash monitor.sh           前台运行（建议放到后台终端跑）
#   bash monitor.sh once      只执行一轮探测（便于手工排查）

LOG=/workspace/yasi8/yasi-koiyu/monitor.log
PORT=8996
INTERVAL=15
HEALTH=/workspace/health-check.sh

now(){ date '+%F %T'; }

http_ok() {
  local code
  code=$(curl -k -s -o /dev/null -w "%{http_code}" --max-time 5 "http://127.0.0.1:$PORT/" 2>/dev/null)
  [ -n "$code" ] && [ "$code" != "000" ]
}

port_listening(){ ss -tln 2>/dev/null | grep -q ":$PORT "; }

log(){ echo "[$(now)] $*" >> "$LOG"; }

check_once() {
  if http_ok; then
    echo "OK  $(now) yasi-koiyu 健康"
    return 0
  fi
  if port_listening; then
    echo "STUCK $(now) yasi-koiyu 端口 $PORT 在监听但无 HTTP 响应（僵死）"
    log "❌ 死亡检测：yasi-koiyu 僵死（端口 $PORT 在监听但无 HTTP 响应）"
    log "   -> 触发自动重启 ..."
    bash "$HEALTH" --service yasi-koiyu >>"$LOG" 2>&1
    sleep 6
    if http_ok; then log "✅ 已恢复：yasi-koiyu 重启成功"; else log "⚠️ 恢复失败：yasi-koiyu 重启后仍无响应"; fi
    return 1
  fi
  echo "DEAD $(now) yasi-koiyu 端口 $PORT 未监听（进程退出）"
  log "❌ 死亡检测：yasi-koiyu 进程退出（端口 $PORT 未监听）"
  log "   -> 触发自动拉起 ..."
  bash "$HEALTH" --service yasi-koiyu >>"$LOG" 2>&1
  sleep 6
  if http_ok; then log "✅ 已恢复：yasi-koiyu 拉起成功"; else log "⚠️ 恢复失败：yasi-koiyu 拉起后仍无响应"; fi
  return 1
}

if [ "$1" = "once" ]; then
  check_once
  exit $?
fi

echo "[$(now)] monitor.sh 启动，每 ${INTERVAL}s 探测一次 yasi-koiyu (端口 $PORT)，日志写入 $LOG"
log "🟢 监控已启动，开始守护 yasi-koiyu（端口 $PORT）"

dead_since=""
while true; do
  if http_ok; then
    if [ -n "$dead_since" ]; then
      log "✅ 已恢复：yasi-koiyu 恢复正常（宕机始于 $dead_since）"
      dead_since=""
    fi
  else
    [ -z "$dead_since" ] && dead_since="$(now)"
    if port_listening; then
      log "❌ 死亡检测：yasi-koiyu 僵死（端口 $PORT 在监听但无 HTTP 响应）于 $dead_since"
    else
      log "❌ 死亡检测：yasi-koiyu 进程退出（端口 $PORT 未监听）于 $dead_since"
    fi
    log "   -> 触发自动重启 ..."
    bash "$HEALTH" --service yasi-koiyu >>"$LOG" 2>&1
    sleep 6
    if http_ok; then log "✅ 已恢复：yasi-koiyu 重启成功"; dead_since=""; else log "⚠️ 重启后仍无响应，${INTERVAL}s 后重试"; fi
  fi
  sleep "$INTERVAL"
done