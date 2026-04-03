# 统一开发启动方案设计文档

**日期：** 2026-04-03
**优先级：** P0
**状态：** 已批准

## 背景

当前 Sage 项目存在多个开发入口（server、desktop、web），配置文件分散，新开发者难以快速上手。根据开源优先级清单 P0 要求，需要统一"怎么跑起来"的体验。

## 目标

- 外部开发者在首次 clone 后，能按单一路径跑起 server 和 web
- 新用户不需要读源码，只看 Quick Start 就能本地跑通登录页
- 不需要先启动 MySQL / ES / RustFS 就能进入主界面

## 设计方案

### 文件结构

```
Sage/
├── scripts/
│   └── dev-up.sh                 # 全自动开发启动脚本
├── .env                          # 后端配置（用户创建）
├── .env.example                  # 后端完整配置模板（保持不变）
├── .env.example.minimal          # 后端精简配置模板（新增）
├── app/server/web/
│   ├── .env.development          # 前端开发配置（用户创建）
│   └── .env.example              # 前端配置模板（新增）
├── README.md                     # 根目录快速启动指引
└── docs/
    ├── zh/GETTING_STARTED.md     # 更新快速开始
    └── en/GETTING_STARTED.md     # 同步更新
```

### 配置分离原则

**后端配置：**
- 位置：根目录 `.env`
- 模板：`.env.example`（完整）、`.env.example.minimal`（精简）
- 用于：Python 服务
- 读取：`common/core/env.py` 已有逻辑

**前端配置：**
- 位置：`app/server/web/.env.development`
- 模板：`app/server/web/.env.example`
- 用于：Vite 构建和开发
- 读取：Vite 自动加载

**关键原则：**
- 前后端配置完全分离，各管各的
- 用户修改配置时，明确知道在改哪个文件
- 脚本中明确提示配置文件位置和模板位置

### dev-up.sh 脚本设计

**核心流程：**

1. **环境检查**
   - 检查 Python 版本（>= 3.11）
   - 检查 Node.js 版本（>= 18）
   - 版本不符时给出明确错误提示

2. **配置文件检查与创建**
   - 检查后端 `.env`，不存在则提示选择模式：
     - 精简模式：复制 `.env.example.minimal`
     - 完整模式：复制 `.env.example`
   - 明确告知配置文件位置和模板位置
   - 检查前端 `.env.development`，不存在则从模板创建
   - 明确告知前端配置文件位置

3. **依赖安装**
   - 检查 Python 依赖是否已安装
   - 检查前端 node_modules 是否存在
   - 按需安装，避免重复安装

4. **服务启动**
   - 串行启动：先启动后端，等待健康检查通过
   - 后台运行后端服务
   - 健康检查：轮询 `/api/health` 端点
   - 前端就绪后启动前端（npm run dev）
   - 设置 Ctrl+C 清理后台进程

5. **用户体验**
   - 每个步骤都有清晰的 emoji 图标提示
   - 错误信息友好且可操作
   - 成功启动后显示访问地址

### 精简配置模板 (.env.example.minimal)

**关键配置项：**

```bash
# 数据库：使用 SQLite
SAGE_DB_TYPE=sqlite
SAGE_SQLITE_PATH=./data/sage.db

# 认证：native 模式（最简单）
SAGE_AUTH_MODE=native

# 可选服务（注释掉，不阻塞启动）
# SAGE_ELASTICSEARCH_URL=
# SAGE_S3_ENDPOINT=

# 默认端口
SAGE_PORT=8080

# Web 基础路径
SAGE_WEB_BASE_PATH=/

# LLM 配置（用户必须提供）
SAGE_DEFAULT_LLM_API_KEY=
SAGE_DEFAULT_LLM_API_BASE_URL=
SAGE_DEFAULT_LLM_MODEL_NAME=
```

**与完整配置的区别：**
- 数据库：MySQL → SQLite
- 去掉 Elasticsearch、RustFS 的强依赖
- 认证模式：默认 native 而非 trusted_proxy
- 所有外部服务都改为可选

### 前端配置模板 (app/server/web/.env.example)

```bash
# 前端开发环境配置
# 复制为 .env.development 使用

NODE_ENV=development

# 后端 API 地址
VITE_SAGE_API_BASE_URL=http://127.0.0.1:8080

# Web 基础路径
VITE_SAGE_WEB_BASE_PATH=/

# API 前缀
VITE_BACKEND_API_PREFIX=/api
```

### 文档更新

**根目录 README.md：**
- 简短介绍 Sage
- 快速启动三步：
  1. 配置 LLM API Key
  2. 运行 `./scripts/dev-up.sh`
  3. 打开浏览器访问
- 指向详细文档

**docs/zh/GETTING_STARTED.md：**
- 第一部分改为"快速开始"（使用 dev-up.sh）
- 原有内容改为"手动启动"（进阶选项）
- 添加配置文件说明章节
- 添加故障排查链接

**docs/en/GETTING_STARTED.md：**
- 同步中文版的更新

## 验收标准

- [ ] 新用户 clone 后可以直接运行 `./scripts/dev-up.sh`
- [ ] 脚本能检测 Python 和 Node.js 版本
- [ ] 脚本自动创建缺失的配置文件并提示位置
- [ ] 选择精简模式后，不需要 MySQL/ES/RustFS 能启动
- [ ] 后端启动成功后，前端自动启动
- [ ] 浏览器能访问到登录页面
- [ ] 文档中有清晰的快速开始指引

## 实施计划

1. 创建 scripts 目录和 dev-up.sh 脚本
2. 创建 .env.example.minimal
3. 创建 app/server/web/.env.example
4. 更新 README.md
5. 更新 GETTING_STARTED.md（中英文）
6. 测试完整流程

## 注意事项

- 保持 .env.example 不变，不影响现有用户
- 前后端配置完全分离，脚本中明确提示
- 错误信息友好，指导用户下一步操作
- 串行启动确保前端不会因为后端未就绪而失败
