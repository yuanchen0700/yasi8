#!/bin/bash
# 每6小时检查并启动静态文件服务器
# 如果服务器已运行则不做任何操作

OUTPUT_DIR="/root/.nanobot/workspace/output"
PORT=8001
STATIC_CMD="python3 -m http.server $PORT --bind 0.0.0.0 --directory $OUTPUT_DIR"
PID_FILE="/root/.nanobot/workspace/server.pid"

# 确保输出目录存在
mkdir -p "$OUTPUT_DIR"

# 检查PID文件是否存在且进程正在运行
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "[$(date)] 服务器已运行 (PID: $PID)，跳过启动"
        exit 0
    else
        echo "[$(date)] 发现过期的PID文件，清理后重新启动"
        rm -f "$PID_FILE"
    fi
fi

# 启动静态文件服务器
echo "[$(date)] 启动静态文件服务器..."
$STATIC_CMD > /root/.nanobot/workspace/server.log 2>&1 &
SERVER_PID=$!
echo $SERVER_PID > "$PID_FILE"
echo "[$(date)] 服务器已启动 (PID: $SERVER_PID)，监听端口 $PORT"
echo "[$(date)] 下载目录: $OUTPUT_DIR"