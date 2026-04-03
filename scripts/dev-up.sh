#!/bin/bash

# Sage Development Environment Startup Script
# For: Local quick development, beginner onboarding

set -e

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "================================"
echo "  Sage Dev Environment Startup"
echo "================================"
echo ""

# 1. Check Python version
echo "🔍 Checking Python version..."
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python3 not found, please install (requires >= 3.11)${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]); then
    echo -e "${RED}❌ Python version must be >= 3.11, current: $PYTHON_VERSION${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Python version: $PYTHON_VERSION${NC}"
echo ""

# 2. Check Node.js version
echo "🔍 Checking Node.js version..."
if ! command -v node &> /dev/null; then
    echo -e "${RED}❌ Node.js not found, please install (requires >= 18)${NC}"
    exit 1
fi

NODE_VERSION=$(node --version 2>&1 | sed 's/v//')
NODE_MAJOR=$(echo $NODE_VERSION | cut -d. -f1)

if [ "$NODE_MAJOR" -lt 18 ]; then
    echo -e "${RED}❌ Node.js version must be >= 18, current: $NODE_VERSION${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Node.js version: $NODE_VERSION${NC}"
echo ""

# 3. Check backend configuration file
echo "🔍 Checking backend configuration..."
if [ ! -f .env ]; then
    echo -e "${YELLOW}❌ Backend config not found: .env${NC}"
    echo ""
    echo "📝 Choose backend configuration mode:"
    echo "  1) Minimal (SQLite, recommended for beginners)"
    echo "     Template: .env.example.minimal"
    echo "     - No external dependencies"
    echo "     - Uses SQLite file database"
    echo "     - Best for local quick development"
    echo ""
    echo "  2) Full (MySQL + ES + RustFS)"
    echo "     Template: .env.example"
    echo "     - Requires MySQL, Elasticsearch, RustFS"
    echo "     - Best for production-like environment"
    echo ""
    read -p "Choose [1/2, default 1]: " mode

    if [ "$mode" = "2" ]; then
        cp .env.example .env
        echo -e "${GREEN}✅ Created .env (full mode)${NC}"
    else
        cp .env.example.minimal .env
        echo -e "${GREEN}✅ Created .env (minimal mode)${NC}"
    fi

    echo ""
    echo -e "${YELLOW}⚠️  Config file location: ${PROJECT_ROOT}/.env${NC}"
    echo -e "${YELLOW}💡 Edit this file to configure LLM API Key and other settings${NC}"
    echo -e "${YELLOW}💡 Run this script again after configuration${NC}"
    echo ""
    exit 0
else
    echo -e "${GREEN}✅ Backend config exists: .env${NC}"
fi
echo ""

# 4. Check frontend configuration file
echo "🔍 Checking frontend configuration..."
FRONTEND_ENV="app/server/web/.env.development"
if [ ! -f "$FRONTEND_ENV" ]; then
    echo -e "${YELLOW}❌ Frontend config not found: $FRONTEND_ENV${NC}"

    if [ -f "app/server/web/.env.example" ]; then
        cp app/server/web/.env.example "$FRONTEND_ENV"
        echo -e "${GREEN}✅ Created frontend config from template${NC}"
    else
        # Create default frontend config
        cat > "$FRONTEND_ENV" << EOF
NODE_ENV=development

# Backend API URL
VITE_SAGE_API_BASE_URL=http://127.0.0.1:8080

# Web base path
VITE_SAGE_WEB_BASE_PATH=/

# API prefix
VITE_BACKEND_API_PREFIX=/api
EOF
        echo -e "${GREEN}✅ Created default frontend config${NC}"
    fi

    echo ""
    echo -e "${YELLOW}⚠️  Frontend config location: ${PROJECT_ROOT}/$FRONTEND_ENV${NC}"
    echo -e "${YELLOW}💡 Edit this file to modify frontend settings${NC}"
else
    echo -e "${GREEN}✅ Frontend config exists: $FRONTEND_ENV${NC}"
fi
echo ""

# 5. Check Python dependencies
echo "🔍 Checking Python dependencies..."
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "📦 Installing Python dependencies..."
    pip install -r requirements.txt
    echo -e "${GREEN}✅ Python dependencies installed${NC}"
else
    echo -e "${GREEN}✅ Python dependencies already installed${NC}"
fi
echo ""

# 6. Check frontend dependencies
echo "🔍 Checking frontend dependencies..."
if [ ! -d "app/server/web/node_modules" ]; then
    echo "📦 Installing frontend dependencies..."
    cd app/server/web
    npm install
    cd ../..
    echo -e "${GREEN}✅ Frontend dependencies installed${NC}"
else
    echo -e "${GREEN}✅ Frontend dependencies already installed${NC}"
fi
echo ""

# 7. Start backend service (background)
echo "🚀 Starting backend service..."
python3 -m app.server.main > logs/server.log 2>&1 &
SERVER_PID=$!

# Wait for backend process to start
sleep 2

# Check if backend process is still running
if ! kill -0 $SERVER_PID 2>/dev/null; then
    echo -e "${RED}❌ Backend startup failed, check logs: logs/server.log${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Backend service started (PID: $SERVER_PID)${NC}"

# 8. Wait for backend to be ready
echo "⏳ Waiting for backend to be ready..."
MAX_WAIT=30
WAIT_COUNT=0

while [ $WAIT_COUNT -lt $MAX_WAIT ]; do
    if curl -s http://127.0.0.1:8080/api/health > /dev/null 2>&1; then
        echo -e "${GREEN}✅ Backend is ready${NC}"
        break
    fi
    WAIT_COUNT=$((WAIT_COUNT + 1))
    sleep 1
    echo -n "."
done

echo ""

if [ $WAIT_COUNT -eq $MAX_WAIT ]; then
    echo -e "${RED}❌ Backend startup timeout, check logs: logs/server.log${NC}"
    kill $SERVER_PID 2>/dev/null
    exit 1
fi

# 9. Start frontend service
echo ""
echo "================================"
echo "  🎉 Services Started Successfully!"
echo "================================"
echo ""
echo "Backend service:"
echo "  - URL: http://127.0.0.1:8080"
echo "  - Logs: logs/server.log"
echo "  - PID: $SERVER_PID"
echo ""
echo "Starting frontend service..."
echo ""

# Set up Ctrl+C cleanup
trap "echo ''; echo '🛑 Stopping services...'; kill $SERVER_PID 2>/dev/null; exit 0" INT TERM

cd app/server/web
npm run dev

# Cleanup backend process when npm run dev exits
kill $SERVER_PID 2>/dev/null
