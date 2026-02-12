# Sage Backend HTTP API Reference

This document provides a comprehensive reference for the Sage backend HTTP API endpoints.

## Base URL
All API endpoints are relative to the server base URL (e.g., `http://localhost:8000`).

## Response Format
Standard response format:
```json
{
  "code": 0,          // 0 for success, non-zero for error
  "message": "...",   // Status message
  "data": { ... }     // Response payload
}
```

---

## 1. User & Authentication (`/api/user`)

### Register
- **URL**: `/api/user/register`
- **Method**: `POST`
- **Body**:
  ```json
  {
    "username": "string",
    "password": "string",
    "email": "string",
    "phonenum": "string"
  }
  ```

### Login
- **URL**: `/api/user/login`
- **Method**: `POST`
- **Body**:
  ```json
  {
    "username_or_email": "string",
    "password": "string"
  }
  ```
- **Response**: Returns `access_token`, `refresh_token`, `expires_in`.

### Check Login Status
- **URL**: `/api/user/check_login`
- **Method**: `GET`
- **Headers**: `Authorization: Bearer <token>`
- **Response**: Returns user claims/info.

### Change Password
- **URL**: `/api/user/change-password`
- **Method**: `POST`
- **Body**:
  ```json
  {
    "old_password": "string",
    "new_password": "string"
  }
  ```

### User Management (Admin Only)
- **List Users**: `GET /api/user/list?page=1&page_size=20`
- **Add User**: `POST /api/user/add`
- **Delete User**: `POST /api/user/delete`

---

## 2. Chat & Streaming (`/api/chat`, `/api/stream`)

### Standard Chat Stream
- **URL**: `/api/chat`
- **Method**: `POST`
- **Body**:
  ```json
  {
    "messages": [{"role": "user", "content": "..."}],
    "session_id": "optional-uuid",
    "agent_id": "target-agent-id",
    "user_id": "optional",
    "system_context": {}
  }
  ```
- **Response**: Server-Sent Events (SSE) stream.

### Universal Stream (No Agent ID required)
- **URL**: `/api/stream`
- **Method**: `POST`
- **Body**: Same as `/api/chat` but `agent_id` is optional (uses default/configured agent).

### Web Stream
- **URL**: `/api/web-stream`
- **Method**: `POST`
- **Description**: Similar to `/api/stream`, optimized for web clients.

### Submit Async Task
- **URL**: `/api/stream/submit_task`
- **Method**: `POST`
- **Response**: Returns `session_id` for polling status.

---

## 3. Agent Management (`/api/agent`)

### List Agents
- **URL**: `/api/agent/list`
- **Method**: `GET`
- **Response**: List of agent configurations.

### Get Agent Details
- **URL**: `/api/agent/{agent_id}`
- **Method**: `GET`

### Create Agent
- **URL**: `/api/agent/create`
- **Method**: `POST`
- **Body**: `AgentConfigDTO` (name, systemPrefix, tools, etc.)

### Update Agent
- **URL**: `/api/agent/{agent_id}`
- **Method**: `PUT`
- **Body**: `AgentConfigDTO`

### Delete Agent
- **URL**: `/api/agent/{agent_id}`
- **Method**: `DELETE`

### Auto-Generate Agent
- **URL**: `/api/agent/auto-generate`
- **Method**: `POST`
- **Body**:
  ```json
  {
    "agent_description": "string",
    "available_tools": ["tool_name"]
  }
  ```

### Optimize System Prompt
- **URL**: `/api/agent/system-prompt/optimize`
- **Method**: `POST`
- **Body**:
  ```json
  {
    "original_prompt": "string",
    "optimization_goal": "optional string"
  }
  ```

---

## 4. Knowledge Base (KDB) (`/api/knowledge-base`)

### Management
- **List KDBs**: `GET /api/knowledge-base/list`
- **Create KDB**: `POST /api/knowledge-base/add`
- **Update KDB**: `POST /api/knowledge-base/update`
- **Delete KDB**: `DELETE /api/knowledge-base/delete/{kdb_id}`
- **Get Info**: `GET /api/knowledge-base/info?kdb_id=...`
- **Clear KDB**: `POST /api/knowledge-base/clear`
- **Redo All Tasks**: `POST /api/knowledge-base/redo_all`

### Document Management
- **List Docs**: `GET /api/knowledge-base/doc/list?kdb_id=...`
- **Upload Files**: `POST /api/knowledge-base/doc/add_by_files` (Multipart form-data)
- **Delete Doc**: `DELETE /api/knowledge-base/doc/delete/{doc_id}`
- **Redo Doc**: `PUT /api/knowledge-base/doc/redo/{doc_id}`
- **Task Process Status**: `GET /api/knowledge-base/doc/task_process`

### Search/Retrieve
- **URL**: `/api/knowledge-base/retrieve`
- **Method**: `POST`
- **Body**:
  ```json
  {
    "kdb_id": "string",
    "query": "string",
    "top_k": 5
  }
  ```

---

## 5. Conversation History (`/api/conversations`)

### List Conversations
- **URL**: `/api/conversations`
- **Method**: `GET`
- **Params**: `page`, `page_size`, `search`, `agent_id`, `sort_by`

### Get Messages
- **URL**: `/api/conversations/{conversation_id}/messages`
- **Method**: `GET`

### Delete Conversation
- **URL**: `/api/conversations/{conversation_id}`
- **Method**: `DELETE`

### Interrupt Session
- **URL**: `/api/sessions/{session_id}/interrupt`
- **Method**: `POST`

### Session Tasks Status
- **URL**: `/api/sessions/{session_id}/tasks_status`
- **Method**: `POST`

### Session File Workspace
- **Get Files**: `POST /api/sessions/{session_id}/file_workspace`
- **Download File**: `GET /api/sessions/{session_id}/file_workspace/download?file_path=...`

---

## 6. Tools & Skills (`/api/tools`, `/api/skills`)

### Tools
- **List Tools**: `GET /api/tools?type=...`
- **Execute Tool**: `POST /api/tools/exec`
  - Body: `{"tool_name": "...", "tool_params": {...}}`

### Skills
- **List Skills**: `GET /api/skills`
- **Import from URL**: `POST /api/skills/import-url`
- **Upload Skill (ZIP)**: `POST /api/skills/upload`
- **Delete Skill**: `DELETE /api/skills?name=...`
- **Get Content**: `GET /api/skills/content?name=...`
- **Update Content**: `PUT /api/skills/content`

---

## 7. MCP (Model Context Protocol) (`/api/mcp`)

- **List Servers**: `GET /api/mcp/list`
- **Add Server**: `POST /api/mcp/add`
- **Remove Server**: `DELETE /api/mcp/{server_name}`
- **Refresh Server**: `POST /api/mcp/{server_name}/refresh`

---

## 8. System & Utility

### System Info
- **URL**: `/api/system/info`
- **Method**: `GET`
- **Response**: e.g., `{"allow_registration": true}`

### Update Settings (Admin)
- **URL**: `/api/system/update_settings`
- **Method**: `POST`

### Health Check
- **URL**: `/api/health`
- **Method**: `GET`

### OSS Upload
- **URL**: `/api/oss/upload`
- **Method**: `POST`
- **Body**: Multipart file upload
- **Response**: `{"url": "..."}`

### Trace
- **URL**: `/api/trace/{session_id}`
- **Method**: `GET`
- **Response**: List of execution traces/spans for the session.
