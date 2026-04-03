#!/bin/bash

# Sage 开发环境一键启动脚本
# 适用于：本地快速开发、新手入门

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 获取项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "================================"
echo "  Sage 开发环境启动脚本"
echo "================================"
echo ""

# 1. 检查 Python 版本
echo "🔍 检查 Python 版本..."
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ 未找到 Python3，请先安装（需要 >= 3.11）${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]); then
    echo -e "${RED}❌ Python 版本需要 >= 3.11，当前版本：$PYTHON_VERSION${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Python 版本：$PYTHON_VERSION${NC}"
echo ""

# 2. 检查 Node.js 版本
echo "🔍 检查 Node.js 版本..."
if ! command -v node &> /dev/null; then
    echo -e "${RED}❌ 未找到 Node.js，请先安装（需要 >= 18）${NC}"
    exit 1
fi

NODE_VERSION=$(node --version 2>&1 | sed 's/v//')
NODE_MAJOR=$(echo $NODE_VERSION | cut -d. -f1)

if [ "$NODE_MAJOR" -lt 18 ]; then
    echo -e "${RED}❌ Node.js 版本需要 >= 18，当前版本：$NODE_VERSION${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Node.js 版本：$NODE_VERSION${NC}"
echo ""

# 3. 检查后端配置文件
echo "🔍 检查后端配置文件..."
if [ ! -f .env ]; then
    echo -e "${YELLOW}❌ 未找到后端配置文件：.env${NC}"
    echo ""
    echo "📝 请选择后端配置模式："
    echo "  1) 精简模式（SQLite，推荐新手）"
    echo "     模板文件：.env.example.minimal"
    echo "     - 无需外部依赖"
    echo "     - 使用 SQLite 文件数据库"
    echo "     - 适合本地快速开发"
    echo ""
    echo "  2) 完整模式（MySQL + ES + RustFS）"
    echo "     模板文件：.env.example"
    echo "     - 需要额外配置 MySQL、Elasticsearch、RustFS"
    echo "     - 适合生产环境模拟"
    echo ""
    read -p "请选择 [1/2，默认 1]：" mode

    if [ "$mode" = "2" ]; then
        cp .env.example .env
        echo -e "${GREEN}✅ 已创建 .env（完整模式）${NC}"
    else
        cp .env.example.minimal .env
        echo -e "${GREEN}✅ 已创建 .env（精简模式）${NC}"
    fi

    echo ""
    echo -e "${YELLOW}⚠️  配置文件位置：${PROJECT_ROOT}/.env${NC}"
    echo -e "${YELLOW}💡 请编辑此文件，配置 LLM API Key 等必要信息${NC}"
    echo -e "${YELLOW}💡 配置完成后，请重新运行此脚本${NC}"
    echo ""
    exit 0
else
    echo -e "${GREEN}✅ 后端配置文件存在：.env${NC}"
fi
echo ""

# 4. 检查前端配置文件
echo "🔍 检查前端配置文件..."
FRONTEND_ENV="app/server/web/.env.development"
if [ ! -f "$FRONTEND_ENV" ]; then
    echo -e "${YELLOW}❌ 未找到前端配置文件：$FRONTEND_ENV${NC}"

    if [ -f "app/server/web/.env.example" ]; then
        cp app/server/web/.env.example "$FRONTEND_ENV"
        echo -e "${GREEN}✅ 已从前端模板创建配置文件${NC}"
    else
        # 创建默认前端配置
        cat > "$FRONTEND_ENV" << EOF
NODE_ENV=development

# 后端 API 地址
VITE_SAGE_API_BASE_URL=http://127.0.0.1:8080

# Web 基础路径
VITE_SAGE_WEB_BASE_PATH=/

# API 前缀
VITE_BACKEND_API_PREFIX=/api
EOF
        echo -e "${GREEN}✅ 已创建默认前端配置文件${NC}"
    fi

    echo ""
    echo -e "${YELLOW}⚠️  前端配置文件位置：${PROJECT_ROOT}/$FRONTEND_ENV${NC}"
    echo -e "${YELLOW}💡 如需修改前端配置，请编辑此文件${NC}"
else
    echo -e "${GREEN}✅ 前端配置文件存在：$FRONTEND_ENV${NC}"
fi
echo ""

# 5. 检查 Python 依赖
echo "🔍 检查 Python 依赖..."
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "📦 安装 Python 依赖..."
    pip install -r requirements.txt
    echo -e "${GREEN}✅ Python 依赖安装完成${NC}"
else
    echo -e "${GREEN}✅ Python 依赖已安装${NC}"
fi
echo ""

# 6. 检查前端依赖
echo "🔍 检查前端依赖..."
if [ ! -d "app/server/web/node_modules" ]; then
    echo "📦 安装前端依赖..."
    cd app/server/web
    npm install
    cd ../..
    echo -e "${GREEN}✅ 前端依赖安装完成${NC}"
else
    echo -e "${GREEN}✅ 前端依赖已安装${NC}"
fi
echo ""

# 7. 启动后端服务（后台运行）
echo "🚀 启动后端服务..."
python3 -m app.server.main > logs/server.log 2>&1 &
SERVER_PID=$!

# 等待后端进程启动
sleep 2

# 检查后端进程是否还在运行
if ! kill -0 $SERVER_PID 2>/dev/null; then
    echo -e "${RED}❌ 后端启动失败，请查看日志：logs/server.log${NC}"
    exit 1
fi

echo -e "${GREEN}✅ 后端服务已启动（PID: $SERVER_PID）${NC}"

# 8. 等待后端就绪
echo "⏳ 等待后端就绪..."
MAX_WAIT=30
WAIT_COUNT=0

while [ $WAIT_COUNT -lt $MAX_WAIT ]; do
    if curl -s http://127.0.0.1:8080/api/health > /dev/null 2>&1; then
        echo -e "${GREEN}✅ 后端已就绪${NC}"
        break
    fi
    WAIT_COUNT=$((WAIT_COUNT + 1))
    sleep 1
    echo -n "."
done

echo ""

if [ $WAIT_COUNT -eq $MAX_WAIT ]; then
    echo -e "${RED}❌ 后端启动超时，请查看日志：logs/server.log${NC}"
    kill $SERVER_PID 2>/dev/null
    exit 1
fi

# 9. 启动前端服务
echo ""
echo "================================"
echo "  🎉 服务启动成功！"
echo "================================"
echo ""
echo "后端服务："
echo "  - 地址：http://127.0.0.1:8080"
echo "  - 日志：logs/server.log"
echo "  - PID：$SERVER_PID"
echo ""
echo "正在启动前端服务..."
echo ""

# 设置 Ctrl+C 清理
trap "echo ''; echo '🛑 正在停止服务...'; kill $SERVER_PID 2>/dev/null; exit 0" INT TERM

cd app/server/web
npm run dev

# 如果 npm run dev 退出，也清理后端进程
kill $SERVER_PID 2>/dev/null
