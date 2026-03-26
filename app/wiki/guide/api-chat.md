# 通过 API 调用 Agent 对话

本文档介绍如何通过 HTTP API 调用 Sage Agent 进行对话。

## 前置条件

1. Sage 后端服务已启动
2. 已创建至少一个 Agent（或使用默认 Agent）
3. 已配置模型提供商（LLM Provider）

## 基础信息

### 端口号

后端服务端口通过环境变量 `SAGE_PORT` 获取。如果未设置，服务会自动选择可用端口（默认 51805）。

```bash
# 获取端口号
export SAGE_PORT=51805  # 或服务启动后查看实际端口
```

### 鉴权机制

Sage 使用 JWT Token 进行鉴权。

#### 1. 登录获取 Token

```bash
curl -X POST "http://localhost:$SAGE_PORT/api/user/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "admin"
  }'
```

响应示例：
```json
{
  "code": 200,
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "user_id": "admin"
  }
}
```

#### 2. 在后续请求中使用 Token

```bash
curl -X POST "http://localhost:$SAGE_PORT/api/chat" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

#### 默认管理员账号

| 字段 | 默认值 |
|------|--------|
| 用户名 | `admin` |
| 密码 | `admin` |

## 获取 Agent 列表

```bash
curl -X GET "http://localhost:$SAGE_PORT/api/agent/list" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

响应示例：
```json
{
  "code": 200,
  "data": [
    {
      "id": "default_agent",
      "name": "Sage Assistant",
      "description": "默认智能体",
      "is_default": true
    }
  ],
  "message": "成功获取 1 个Agent配置"
}
```

## 接口：POST /api/chat

流式对话接口。

### 请求参数

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `agent_id` | string | 是 | Agent 的唯一标识 |
| `messages` | array | 是 | 消息列表，至少包含一条用户消息 |
| `session_id` | string | 否 | 会话 ID，不传则自动创建新会话 |

### 消息格式

```json
{
  "role": "user",      // 角色：user/assistant/system
  "content": "你好"     // 消息内容
}
```

### 请求示例

#### 新会话对话

```bash
curl -X POST "http://localhost:$SAGE_PORT/api/chat" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -d '{
    "agent_id": "default_agent",
    "messages": [
      {
        "role": "user",
        "content": "你好，请介绍一下自己"
      }
    ]
  }'
```

#### 继续已有会话

```bash
curl -X POST "http://localhost:$SAGE_PORT/api/chat" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -d '{
    "agent_id": "default_agent",
    "session_id": "sess_xxx_xxx",
    "messages": [
      {
        "role": "user",
        "content": "刚才的问题能再详细说明吗？"
      }
    ]
  }'
```

### 流式响应格式

接口返回 `text/plain` 流式响应，每行是一个 JSON 对象：

```
{"type": "thinking", "content": "正在思考...", "session_id": "sess_xxx", "message_id": "msg_xxx", "timestamp": 1234567890}
{"type": "text", "content": "你好！", "session_id": "sess_xxx", "message_id": "msg_xxx", "timestamp": 1234567891}
{"type": "tool_call", "content": "...", "session_id": "sess_xxx", "message_id": "msg_xxx", "timestamp": 1234567892}
{"type": "tool_result", "content": "...", "session_id": "sess_xxx", "tool_call_id": "call_xxx", "timestamp": 1234567893}
{"type": "stream_end", "session_id": "sess_xxx", "timestamp": 1234567900, "resume_fallback": true}
```

### 消息类型说明

| type | 说明 |
|------|------|
| `thinking` | Agent 思考过程 |
| `text` | 文本回复内容 |
| `tool_call` | 工具调用请求 |
| `tool_result` | 工具执行结果 |
| `error` | 错误信息 |
| `stream_end` | 流结束标记 |

## Python 调用示例

```python
import requests
import json
import os

# 获取端口号
PORT = os.environ.get("SAGE_PORT", "51805")
BASE_URL = f"http://localhost:{PORT}"
ACCESS_TOKEN = "YOUR_ACCESS_TOKEN"  # 先调用登录接口获取


def login():
    """登录获取 Token"""
    response = requests.post(
        f"{BASE_URL}/api/user/login",
        json={"username": "admin", "password": "admin"}
    )
    data = response.json()
    return data["data"]["access_token"]


def chat_with_agent(agent_id: str, message: str, session_id: str = None):
    """与 Agent 对话"""
    global ACCESS_TOKEN
    if not ACCESS_TOKEN:
        ACCESS_TOKEN = login()

    url = f"{BASE_URL}/api/chat"

    payload = {
        "agent_id": agent_id,
        "messages": [{"role": "user", "content": message}]
    }

    if session_id:
        payload["session_id"] = session_id

    response = requests.post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
        stream=True
    )

    full_response = []
    current_session_id = None

    for line in response.iter_lines():
        if line:
            data = json.loads(line.decode('utf-8'))
            msg_type = data.get('type')

            if msg_type == 'text':
                content = data.get('content', '')
                full_response.append(content)
                print(content, end='', flush=True)
            elif msg_type == 'thinking':
                print(f"\n[思考] {data.get('content', '')}", flush=True)
            elif msg_type == 'tool_call':
                print(f"\n[工具调用] {data.get('content', '')}", flush=True)
            elif msg_type == 'tool_result':
                print(f"\n[工具结果] {data.get('content', '')}", flush=True)
            elif msg_type == 'error':
                print(f"\n[错误] {data.get('content')}")
            elif msg_type == 'stream_end':
                current_session_id = data.get('session_id')

    return ''.join(full_response), current_session_id


# 使用示例
if __name__ == "__main__":
    ACCESS_TOKEN = login()  # 先登录

    # 第一次对话（新会话）
    reply, session_id = chat_with_agent("default_agent", "你好，请介绍一下自己")
    print(f"\n会话ID: {session_id}")

    # 继续对话（使用相同的 session_id）
    reply, _ = chat_with_agent("default_agent", "能详细说说你的功能吗？", session_id)
```

## 错误处理

### 常见错误码

| HTTP 状态码 | 说明 | 处理建议 |
|-------------|------|----------|
| 401 | 未授权 | 检查 Token 是否有效，尝试重新登录 |
| 500 | 服务器内部错误 | 检查请求参数是否正确，查看服务器日志 |
| 503 | 模型客户端未配置 | 检查 LLM Provider 配置 |

### 错误响应示例

```json
{
  "type": "error",
  "content": "处理失败: Agent 不存在",
  "role": "assistant",
  "message_id": "msg_xxx",
  "session_id": "sess_xxx"
}
```

## Agent 触发自身 API

如果需要 Agent 能够触发自身的 API，可以将以下信息配置到 Agent 的系统提示词中：

```
后端服务端口: {SAGE_PORT}
登录接口: POST /api/user/login
认证方式: Bearer Token
默认账号: admin / admin
对话接口: POST /api/chat
```
