# 🧠 Sage Multi-Agent Web应用

现代化的多智能体协作Web应用，采用FastAPI后端 + React前端架构，提供智能体协作、深度思考等功能。

## ✨ 功能特性

- 🤖 **多智能体协作** - 支持分解、规划、执行、观察、总结等多智能体流程
- 🧠 **深度思考模式** - 智能体任务分析和思考过程可视化
- 🚀 **FastAPI后端** - 高性能异步API服务器，支持流式响应
- ⚛️ **React前端** - 现代化响应式用户界面，豆包风格设计
- 📡 **实时通信** - WebSocket + SSE双重支持
- 🎨 **美观界面** - Ant Design组件库，支持深度思考可折叠气泡
- 🔧 **工具管理** - 自动发现和管理工具
- 📱 **响应式设计** - 适配各种屏幕尺寸
- 📊 **数学公式支持** - 完整的LaTeX数学公式渲染，支持行内和块级公式
- 🔧 **TypeScript支持** - 完整的类型安全

## 🏗️ 项目结构

```
fastapi_react_demo/
├── backend/                    # FastAPI后端
│   ├── main.py                # 主服务器文件
│   ├── config_example.yaml    # 配置文件模板
│   ├── config_loader.py       # 配置加载器
│   └── logs/                  # 日志目录
├── frontend/                  # React前端
│   ├── src/
│   │   ├── components/        # React组件
│   │   ├── context/           # 状态管理
│   │   ├── hooks/             # 自定义Hook
│   │   └── main.tsx           # 应用入口
│   ├── package.json           # 前端依赖
│   ├── vite.config.ts         # Vite配置
│   └── tsconfig.json          # TypeScript配置
├── start_backend.py           # 后端启动脚本
└── README.md                  # 项目说明
```

## 🚀 快速开始

### 前置要求

- Python 3.8+ 
- Node.js 18+
- npm 或 yarn

### 1. 配置文件设置

**首先复制配置模板：**
```bash
cd examples/fastapi_react_demo/backend
cp config_example.yaml config.yaml
```

**编辑 `config.yaml` 文件，填入您的配置：**
```yaml
# 模型配置 (必填)
model:
  api_key: "sk-your-api-key-here"     # 您的API密钥
  model_name: "deepseek-chat"         # 模型名称
  base_url: "https://api.deepseek.com/v1"  # API地址
  max_tokens: 4096
  temperature: 0.7

# 服务器配置
server:
  host: "0.0.0.0"
  port: 8001      # 后端端口
  reload: true
  log_level: "info"
```

> **重要：** `config.yaml` 文件包含敏感信息，不会提交到git。请从 `config_example.yaml` 复制并修改。

### 2. 后端启动

**方法1: 使用启动脚本（推荐）**
```bash
cd examples/fastapi_react_demo
python start_backend.py
```

**方法2: 直接启动**
```bash
cd examples/fastapi_react_demo/backend
python main.py
```

后端服务将在 `http://localhost:8001` 启动。

### 3. 前端启动

```bash
# 进入前端目录
cd examples/fastapi_react_demo/frontend

# 安装依赖（首次运行）
npm install

# 如果需要数学公式支持，可运行更新脚本（可选）
# Linux/macOS: ../update_math_support.sh
# Windows: ..\update_math_support.bat

# 启动开发服务器
npm run dev
```

前端开发服务器将在 `http://localhost:8080` 启动。

### 4. 访问应用

打开浏览器访问：`http://localhost:8080`

如果未配置API密钥，可在**系统配置**页面进行配置。

## 🎯 使用指南

### 智能体对话功能

1. **深度思考模式** - 开启后显示任务分析过程
2. **多智能体协作** - 开启后展示完整的智能体协作流程
3. **实时流式响应** - 查看智能体实时思考和执行过程
4. **可折叠思考气泡** - 点击展开/收起查看详细思考过程

### 数学公式支持

支持完整的LaTeX格式数学公式：
- **行内公式**：`$E = mc^2$` 
- **块级公式**：`$$\int_0^\pi \sin(x)dx = 2$$`
- **复杂公式**：矩阵、分数、求和、积分等
- **主题适配**：自动适应消息气泡的颜色主题

详细用法参见：[MATH_SUPPORT.md](./MATH_SUPPORT.md)

### 界面功能

- **新对话** - 开始新的对话会话
- **对话历史** - 自动保存对话记录（localStorage）
- **工具管理** - 查看系统可用工具
- **系统配置** - 配置API密钥和模型参数

## 🔧 配置说明

### config.yaml 配置项

```yaml
# 模型配置
model:
  api_key: ""          # API密钥（必填）
  model_name: ""       # 模型名称，如：deepseek-chat, gpt-4等
  base_url: ""         # API基础URL
  max_tokens: 4096     # 最大Token数
  temperature: 0.7     # 温度参数(0.0-2.0)

# 服务器配置  
server:
  host: "0.0.0.0"     # 服务器地址
  port: 8001          # 服务器端口
  reload: true        # 开发模式热重载
  log_level: "info"   # 日志级别

# 工具配置
tools:
  auto_discover: true      # 自动发现工具
  enabled_tools: []        # 启用的工具列表

# 智能体配置
agents:
  enable_deep_thinking: true   # 启用深度思考
  enable_multi_agent: true     # 启用多智能体协作
  max_agents: 7               # 最大智能体数量
```

### 端口配置

**后端端口配置：**
在 `backend/config.yaml` 中修改：
```yaml
server:
  port: 8001  # 修改为您想要的端口
```

**前端端口配置：**
在 `frontend/vite.config.ts` 中修改：
```typescript
export default defineConfig({
  plugins: [react()],
  server: {
    port: 8080,  // 修改前端端口
    proxy: {
      '/api': 'http://localhost:8001',  // 确保指向正确的后端端口
      '/ws': {
        target: 'ws://localhost:8001',  // WebSocket代理地址
        ws: true,
      }
    }
  }
})
```

> **重要：** 如果修改了后端端口，需要同时更新前端的代理配置中的端口号，确保前后端通信正常。

**端口配置示例：**
- 后端使用 9000 端口：
  - `config.yaml`: `port: 9000`
  - `vite.config.ts`: 代理地址改为 `http://localhost:9000`
- 前端使用 3000 端口：
  - `vite.config.ts`: `port: 3000`

### API端点

- `GET /` - 主页面（如果配置了静态文件）
- `GET /api/status` - 系统状态
- `POST /api/configure` - 动态配置系统
- `GET /api/tools` - 获取工具列表
- `POST /api/chat-stream` - 流式聊天API
- `GET /docs` - FastAPI自动文档

## 🛠️ 开发说明

### 前端开发

**添加新组件：**
1. 在 `frontend/src/components/` 创建组件
2. 在 `App.tsx` 中添加路由
3. 在 `Sidebar.tsx` 中添加菜单项

**自定义样式：**
- 全局样式：`src/App.css`
- Ant Design主题：`App.tsx` 中的 `themeConfig`

**状态管理：**
- 使用React Context: `src/context/SystemContext.tsx`
- 自定义Hook: `src/hooks/`

### 后端扩展

**添加API端点：**
在 `main.py` 中添加新的路由函数

**工具集成：**
工具会自动从 `agents/tool/` 目录发现

## 🐛 故障排除

### 常见问题

1. **配置文件未找到**
   ```
   ⚠️ 未找到配置文件，使用默认配置
   ```
   - 确保已从 `config_example.yaml` 复制为 `config.yaml`

2. **API密钥未配置**
   ```
   ⚠️ 未配置API密钥，需要通过Web界面配置
   ```
   - 在 `config.yaml` 中填入API密钥，或通过Web界面配置

3. **端口被占用**
   ```
   Address already in use
   ```
   - 修改 `config.yaml` 中的端口号，或关闭占用端口的进程
   - 检查端口占用：`lsof -i :8001` (macOS/Linux) 或 `netstat -ano | findstr :8001` (Windows)
   - 如果修改后端端口，记得同步更新前端的 `vite.config.ts` 中的代理设置

4. **前端依赖安装失败**
   - 删除 `node_modules` 重新安装：`rm -rf node_modules && npm install`
   - 检查Node.js版本：`node --version`（推荐18+）

5. **WebSocket连接失败**
   - 检查后端是否正常运行
   - 确认防火墙设置
   - 查看浏览器控制台错误

### 调试技巧

- **后端日志**：查看终端输出，或 `logs/` 目录下的日志文件
- **前端调试**：打开浏览器开发者工具(F12)，查看控制台和网络请求
- **API文档**：访问 `http://localhost:8001/docs` 查看交互式API文档

## 📦 生产部署

### 构建前端

```bash
cd frontend
npm run build
```

构建文件将输出到 `backend/static/` 目录。

### 生产配置

修改 `config.yaml`:
```yaml
server:
  reload: false      # 关闭热重载
  log_level: "warning"  # 降低日志级别
```

### Docker部署（可选）

```dockerfile
# Dockerfile示例
FROM node:18 AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.9
WORKDIR /app
COPY backend/ ./backend/
COPY --from=frontend-build /app/frontend/dist ./backend/static/
COPY config_example.yaml ./backend/config.yaml
RUN pip install fastapi uvicorn
EXPOSE 8001
CMD ["python", "backend/main.py"]
```

## 🔒 安全注意事项

- **API密钥安全**：生产环境使用环境变量或密钥管理服务
- **CORS配置**：生产环境限制允许的域名
- **HTTPS**：生产环境使用HTTPS协议
- **输入验证**：所有用户输入都应进行验证和清理

## 📈 性能优化

- **前端优化**：组件懒加载、虚拟滚动、React.memo
- **后端优化**：异步处理、连接池、缓存策略
- **网络优化**：gzip压缩、CDN加速

## 📄 许可证

本项目采用 MIT 许可证。详见项目根目录 LICENSE 文件。

## 🆘 获取帮助

如遇问题，请：
1. 查看本README的故障排除部分
2. 检查项目Issues
3. 查看Sage框架主文档 