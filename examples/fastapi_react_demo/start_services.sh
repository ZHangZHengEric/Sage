#!/bin/bash

# Sage FastAPI + React Demo 服务启动脚本
# 同时启动API服务器和MinIO对象存储服务

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
mkdir -p workspace logs minio-data

# 由于新的配置让MinIO直接使用workspace目录，
# 我们可以清理旧的minio-data目录（如果需要的话）
if [ -d "minio-data" ] && [ -z "$(ls -A minio-data 2>/dev/null)" ]; then
    echo "  清理空的minio-data目录..."
    rmdir minio-data 2>/dev/null || true
fi

# 安装依赖
echo "📦 检查并安装依赖..."
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt > /dev/null 2>&1 || echo "⚠️  依赖安装可能有问题"
fi

# 设置环境变量
export WORKSPACE_ROOT="$(pwd)/workspace"
export PYTHONPATH="$(pwd)/../../:$PYTHONPATH"
export MINIO_ENDPOINT="localhost:20044"
export MINIO_ACCESS_KEY="sage"
export MINIO_SECRET_KEY="sage123456"
export MINIO_BUCKET="workspace"

echo "🔧 配置信息:"
echo "  工作空间: $WORKSPACE_ROOT"
echo "  配置文件: $(pwd)/backend/config.yaml"
echo "  MinIO端点: $MINIO_ENDPOINT"

# 启动API服务器
echo "🌐 启动API服务器..."
cd backend
python main.py &
API_PID=$!
cd ..

echo "✅ 服务已启动:"
echo "  🌐 API服务: http://localhost:8000"
echo "  📚 API文档: http://localhost:8000/docs" 
echo "  🗄️  MinIO API: http://localhost:20044"
echo "  🎛️  MinIO控制台: http://localhost:20045"
echo "  📁 工作空间: $WORKSPACE_ROOT"
echo ""
echo "MinIO访问凭据:"
echo "  用户名: sage"
echo "  密码: sage123456"
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