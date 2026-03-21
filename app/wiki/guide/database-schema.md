# 数据库结构

Sage 使用 SQLite 数据库存储应用数据，数据库文件位于 `~/.sage/sage.db`。

## 数据库文件位置

```
~/.sage/sage.db
```

## 技术栈

- **数据库引擎**: SQLite (通过 SQLAlchemy + aiosqlite 异步访问)
- **ORM**: SQLAlchemy 2.0
- **异步支持**: aiosqlite

## 数据表概览

| 表名 | 说明 | 主要用途 |
|------|------|---------|
| `agent_configs` | Agent 配置表 | 存储用户创建的 AI 智能体配置 |
| `conversations` | 会话表 | 存储聊天会话和消息历史 |
| `llm_providers` | LLM 提供商表 | 存储大语言模型提供商配置 |
| `mcp_servers` | MCP 服务器表 | 存储 MCP 工具服务器配置 |
| `recurring_tasks` | 循环任务表 | 存储定时循环任务配置 |
| `tasks` | 任务表 | 存储一次性任务和执行记录 |
| `task_history` | 任务历史表 | 存储任务执行历史记录 |
| `im_user_configs` | IM 渠道配置表 | 存储飞书、钉钉等 IM 配置 |
| `system_info` | 系统信息表 | 存储系统级别的键值对配置 |

## 表结构详情

### 1. agent_configs - Agent 配置表

存储用户创建的 AI 智能体配置。

| 字段 | 类型 | 说明 |
|------|------|------|
| `agent_id` | String(255) | 主键，Agent 唯一标识 |
| `name` | String(255) | Agent 名称 |
| `config` | JSON | Agent 完整配置（系统提示词、工具、技能等） |
| `is_default` | Boolean | 是否为默认 Agent |
| `created_at` | DateTime | 创建时间 |
| `updated_at` | DateTime | 更新时间 |

**config JSON 结构示例**:
```json
{
  "system_prompt": "你是一个有帮助的助手...",
  "tools": ["file_read", "web_search"],
  "skills": ["code_review"],
  "model_provider": "openai",
  "memory_type": "session",
  "deep_thinking": true,
  "max_loop_count": 10
}
```

### 2. conversations - 会话表

存储聊天会话和消息历史。

| 字段 | 类型 | 说明 |
|------|------|------|
| `session_id` | String(255) | 主键，会话唯一标识 |
| `agent_id` | String(255) | 关联的 Agent ID |
| `agent_name` | Text | Agent 名称（快照） |
| `title` | String(255) | 会话标题 |
| `messages` | JSON | 消息列表 |
| `created_at` | DateTime | 创建时间 |
| `updated_at` | DateTime | 更新时间 |

**messages JSON 结构示例**:
```json
[
  {
    "role": "user",
    "content": "你好",
    "timestamp": "2025-01-15T10:30:00"
  },
  {
    "role": "assistant",
    "content": "你好！有什么可以帮助你的？",
    "timestamp": "2025-01-15T10:30:05"
  }
]
```

### 3. llm_providers - LLM 提供商表

存储大语言模型提供商配置。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | String(255) | 主键，提供商唯一标识 |
| `name` | String(255) | 提供商名称 |
| `base_url` | String(255) | API 基础 URL |
| `api_keys` | JSON | API Key 列表（支持多 Key 轮询） |
| `model` | String(255) | 模型名称 |
| `max_tokens` | Integer | 最大 Token 数 |
| `temperature` | Float | 温度参数 |
| `top_p` | Float | Top P 参数 |
| `presence_penalty` | Float | 重复惩罚系数 |
| `max_model_len` | Integer | 最大模型长度 |
| `supports_multimodal` | Boolean | 是否支持多模态 |
| `is_default` | Boolean | 是否为默认提供商 |
| `created_at` | DateTime | 创建时间 |
| `updated_at` | DateTime | 更新时间 |

### 4. mcp_servers - MCP 服务器表

存储 MCP (Model Context Protocol) 工具服务器配置。

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | String(255) | 主键，服务器名称 |
| `config` | JSON | 服务器配置（协议类型、命令、参数等） |
| `created_at` | DateTime | 创建时间 |
| `updated_at` | DateTime | 更新时间 |

**config JSON 结构示例**:
```json
{
  "protocol": "stdio",
  "command": "python",
  "args": ["-m", "mcp_server_fetch"],
  "env": {
    "API_KEY": "xxx"
  },
  "description": "网页抓取服务器"
}
```

### 5. recurring_tasks - 循环任务表

存储定时循环任务配置（Cron 任务）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer | 主键，自增 |
| `name` | String(255) | 任务名称 |
| `description` | Text | 任务描述 |
| `session_id` | String(255) | 关联的会话 ID |
| `agent_id` | String(255) | 执行任务的 Agent ID |
| `cron_expression` | String(255) | Cron 表达式 |
| `enabled` | Boolean | 是否启用 |
| `created_at` | DateTime | 创建时间 |
| `updated_at` | DateTime | 更新时间 |
| `last_executed_at` | DateTime | 上次执行时间 |

### 6. tasks - 任务表

存储一次性任务和执行记录。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer | 主键，自增 |
| `name` | String(255) | 任务名称 |
| `description` | Text | 任务描述 |
| `agent_id` | String(255) | 执行任务的 Agent ID |
| `session_id` | String(255) | 关联的会话 ID |
| `execute_at` | DateTime | 计划执行时间 |
| `status` | String(50) | 状态: pending/processing/completed/failed |
| `created_at` | DateTime | 创建时间 |
| `updated_at` | DateTime | 更新时间 |
| `completed_at` | DateTime | 完成时间 |
| `retry_count` | Integer | 重试次数 |
| `max_retries` | Integer | 最大重试次数 |
| `recurring_task_id` | Integer | 关联的循环任务 ID |

### 7. task_history - 任务历史表

存储任务执行历史记录。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer | 主键，自增 |
| `task_id` | Integer | 关联的任务 ID |
| `executed_at` | DateTime | 执行时间 |
| `status` | String(50) | 执行状态 |
| `response` | Text | 执行响应结果 |
| `error_message` | Text | 错误信息 |

### 8. im_user_configs - IM 渠道配置表

存储飞书、钉钉、企业微信等 IM 渠道配置。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer | 主键，自增 |
| `sage_user_id` | String(64) | Sage 用户 ID |
| `provider` | String(36) | 提供商: feishu/dingtalk/wechat_work/imessage |
| `config` | JSON | 配置详情（App ID、Secret 等） |
| `enabled` | Boolean | 是否启用 |
| `created_at` | DateTime | 创建时间 |
| `updated_at` | DateTime | 更新时间 |

**config JSON 结构示例** (飞书):
```json
{
  "app_id": "cli_xxx",
  "app_secret": "xxx",
  "encrypt_key": "xxx",
  "verification_token": "xxx"
}
```

### 9. system_info - 系统信息表

存储系统级别的键值对配置。

| 字段 | 类型 | 说明 |
|------|------|------|
| `key` | String(64) | 主键，配置键 |
| `value` | String(255) | 配置值 |

**常见配置项**:
- `allow_registration`: 是否允许注册
- `version`: 系统版本

## 数据库访问

### 使用 DAO 模式

Sage 使用 DAO (Data Access Object) 模式封装数据库操作：

```python
from app.desktop.core.models.agent import AgentConfigDao
from app.desktop.core.models.conversation import ConversationDao

# 获取 Agent 配置
dao = AgentConfigDao()
agent = await dao.get_by_id("agent_123")

# 获取会话列表
conv_dao = ConversationDao()
conversations, total = await conv_dao.get_conversations_paginated(
    page=1, page_size=10
)
```

### 直接使用 SQLAlchemy Session

```python
from app.desktop.core.core.client.db import get_global_db
from sqlalchemy import select

db = await get_global_db()
async with db.get_session() as session:
    result = await session.execute(select(Agent))
    agents = result.scalars().all()
```

## 备份与恢复

### 备份数据库

```bash
# 复制数据库文件
cp ~/.sage/sage.db ~/.sage/sage.db.backup.$(date +%Y%m%d)

# 或使用 SQLite 命令行备份
sqlite3 ~/.sage/sage.db ".backup ~/.sage/sage_backup.db"
```

### 恢复数据库

```bash
# 停止 Sage 应用
# 恢复数据库文件
cp ~/.sage/sage_backup.db ~/.sage/sage.db
# 重启 Sage 应用
```

## 开发者说明

### 添加新表

1. 在 `app/desktop/core/models/` 目录下创建新的模型文件
2. 继承 `Base` 类并定义表结构
3. 创建对应的 DAO 类继承 `BaseDao`
4. 数据库表会在应用启动时自动创建

### 模型定义示例

```python
from sqlalchemy import String, Integer
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, BaseDao

class MyModel(Base):
    __tablename__ = "my_table"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))

class MyModelDao(BaseDao):
    async def get_by_id(self, id: int):
        return await BaseDao.get_by_id(self, MyModel, id)
```

### 数据库迁移

目前 Sage 使用 SQLAlchemy 的 `create_all()` 自动创建表结构。如需进行复杂迁移，建议：

1. 备份现有数据库
2. 使用 SQLite 命令行或脚本执行迁移
3. 测试迁移后的数据库
