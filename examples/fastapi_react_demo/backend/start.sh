#!/bin/bash

# 创建日志目录
mkdir -p /app/logs

# 生成日志文件名（使用启动时间，格式：年月日_时分秒）
LOG_FILE="/app/logs/backend_$(date +%Y年%m月%d日_%H时%M分%S秒).log"

# 启动Python应用并重定向输出到日志文件
echo "Starting backend at $(date)" | tee "$LOG_FILE"
python main.py 2>&1 | tee -a "$LOG_FILE" 