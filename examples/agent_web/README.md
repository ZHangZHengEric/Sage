# Agent Web Platform

一个现代化的AI Agent管理平台前端，具有科技感和简约风格的用户界面。基于 **Vite** 构建，提供快速的开发体验。

## 🚀 快速开始

### 前置要求

- Node.js (推荐 v16 或更高版本)
- npm 或 yarn
- 后端服务运行在 `http://localhost:8001`

### 安装依赖

```bash
cd /Users/zhangzheng/rcrai/workspace/reagent/demo/agent_web
npm install
```

### 启动开发服务器

```bash
npm run dev
```

默认情况下，前端将在 `http://localhost:3000` 启动。

## ⚙️ 配置说明

### 端口配置

项目使用 **Vite** 构建工具，可以通过以下方式配置端口：

#### 方法1：修改 vite.config.js 文件（推荐）

在 `vite.config.js` 文件中的 `server` 配置中修改：

```javascript
export default defineConfig({
  server: {
    port: 3001, // 修改为你想要的端口
    // ...
  }
})
```

#### 方法2：命令行参数

```bash
# 指定端口启动
npm run dev -- --port 3001
```

### 后端API配置

#### Vite 代理配置（推荐）

在 `vite.config.js` 中已配置代理：

```javascript
export default defineConfig({
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
        secure: false
      }
    }
  }
})
```

这样前端的API请求会自动代理到后端服务器，避免跨域问题。

#### 修改后端地址

##### 方法1：使用环境变量（推荐）

复制 `.env.example` 文件为 `.env`：

```bash
cp .env.example .env
```

然后修改 `.env` 文件中的 `VITE_API_TARGET`：

```bash
# 本地开发
VITE_API_TARGET=http://localhost:23232

# 使用域名部署
VITE_API_TARGET=http://your-domain.com:23232
# 或者如果后端使用标准端口
VITE_API_TARGET=http://your-domain.com
VITE_API_TARGET=https://your-domain.com
```

##### 方法2：直接修改配置文件

如果后端运行在不同的端口或地址，修改 `vite.config.js` 中的 `proxy` 配置：

```javascript
export default defineConfig({
  server: {
    proxy: {
      '/api': {
        target: 'http://your-domain.com:23232',  // 修改为实际的后端地址
        changeOrigin: true,
        secure: false
      }
    }
  }
})
```

## 🔧 开发配置

### Vite 配置特性

- 快速热模块替换 (HMR)
- 支持 JSX 语法在 `.js` 文件中
- 自动代理 API 请求
- 快速冷启动
- ESLint 集成

### 生产环境构建

```bash
# 构建生产版本
npm run build

# 构建后的文件在 dist/ 目录

# 预览生产构建
npm run preview
```

### 部署配置

#### 域名部署配置

当使用域名访问时，需要正确配置后端API地址：

1. **修改环境变量**（推荐方式）：
   ```bash
   # 编辑 .env 文件
   VITE_API_TARGET=http://your-domain.com:23232
   # 或者如果后端使用标准端口
   VITE_API_TARGET=https://your-domain.com
   ```

2. **重新构建项目**：
   ```bash
   npm run build
   ```

3. **部署注意事项**：
   - 确保后端服务在指定域名和端口上可访问
   - 如果使用HTTPS，确保SSL证书配置正确
   - 检查防火墙设置，确保端口23232开放

#### 生产环境构建

生产环境部署时，需要配置正确的后端API地址，然后构建项目。

## 📁 项目结构

```
src/
├── components/          # 公共组件
│   ├── Sidebar.js      # 侧边栏组件
│   └── Sidebar.css
├── pages/              # 页面组件
│   ├── ChatPage.js     # 聊天页面
│   ├── AgentConfigPage.js  # Agent配置页面
│   ├── ToolsPage.js    # 工具集页面
│   └── HistoryPage.js  # 历史记录页面
├── services/           # 服务层
│   └── StorageService.js   # 本地存储服务
├── App.js              # 主应用组件
├── App.css             # 全局样式
└── index.js            # 应用入口
```

## 🌐 API接口

前端与以下后端接口交互：

- `GET /api/tools` - 获取工具列表
- `POST /api/stream` - 发送消息并接收流式响应

## 🎨 功能特性

- 🎯 **现代化UI**: 科技感深色主题，渐变效果
- 📱 **响应式设计**: 支持桌面和移动端
- 💬 **实时聊天**: 支持流式响应的AI对话
- ⚙️ **Agent管理**: 完整的Agent配置和管理
- 🔧 **工具集成**: 可视化工具浏览和管理
- 📚 **历史记录**: 对话历史的存储和管理
- 💾 **本地存储**: 所有配置自动保存到浏览器

## 🐛 常见问题

### 端口被占用

```bash
# 查看端口占用
lsof -i :3000

# 杀死占用进程
kill -9 <PID>

# 或者使用不同端口
PORT=3001 npm start
```

### 跨域问题

确保 `package.json` 中的 `proxy` 配置正确，或者在后端启用CORS。

### 后端连接失败

1. 确认后端服务正在运行
2. 检查后端地址和端口是否正确
3. 查看浏览器控制台的网络请求错误

## 📝 开发说明

本项目使用 **Vite** 构建工具，具有以下特性：

- 使用 `vite` 进行快速开发和构建
- 支持热模块替换 (HMR)
- 支持代理配置来解决开发环境的跨域问题
- 快速冷启动和构建速度
- 支持 JSX 语法在 `.js` 文件中