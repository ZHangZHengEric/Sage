#!/bin/bash

# Sage FastAPI + React Demo 服务启动脚本
# 同时启动API服务器和FTP服务器

set -e

echo "🚀 启动 Sage FastAPI + React Demo 服务"
echo "=================================="

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到Python3，请先安装Python"
    exit 1
fi

# 检查是否在正确的目录
if [ ! -f "backend/main.py" ]; then
    echo "❌ 请在fastapi_react_demo目录下运行此脚本"
    exit 1
fi

# 创建必要的目录
echo "📁 创建工作目录..."
mkdir -p workspace logs ftp-config

# 安装依赖
echo "📦 检查并安装依赖..."
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt > /dev/null 2>&1 || echo "⚠️  依赖安装可能有问题"
fi

# 设置环境变量
export WORKSPACE_ROOT="$(pwd)/workspace"
export PYTHONPATH="$(pwd)/../../:$PYTHONPATH"

echo "🔧 配置信息:"
echo "  工作空间: $WORKSPACE_ROOT"
echo "  配置文件: $(pwd)/backend/config.yaml"

# 启动API服务器
echo "🌐 启动API服务器..."
cd backend
python main.py &
API_PID=$!
cd ..

echo "✅ 服务已启动:"
echo "  🌐 API服务: http://localhost:8000"
echo "  📚 API文档: http://localhost:8000/docs" 
echo "  📂 FTP服务: ftp://sage:sage123@localhost:2121"
echo "  📁 工作空间: $WORKSPACE_ROOT"
echo ""
echo "按 Ctrl+C 停止所有服务"

# 等待中断信号
wait_for_interrupt() {
    while true; do
        sleep 1
    done
}

# 清理函数
cleanup() {
    echo ""
    echo "🛑 正在停止服务..."
    
    # 停止API服务器
    if [ ! -z "$API_PID" ]; then
        kill $API_PID 2>/dev/null || true
        echo "✅ API服务器已停止"
    fi
    
    echo "👋 所有服务已停止"
    exit 0
}

# 设置中断信号处理
trap cleanup SIGINT SIGTERM

# 等待中断
wait_for_interrupt 