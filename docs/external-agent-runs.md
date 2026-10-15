# 外部 Agent Run 与工作区接口

本契约用于可信业务服务调用 Sage V2，不包含作品、网站或问卷等业务概念。接口注册在现有 Sage V2 HTTP 服务上。

## 身份与边界

- 现有外部会话由租户 ID、Agent ID 和 `threadId` 三者确定，工作区按租户与 Agent 隔离。三元组用于定位会话，AG-UI `runId` 用于定位该会话中的准确运行。
- 内部 Run 读取与控制同时核对持久化的 Agent、租户、会话 ID 和 `runId`；不能用“会话的最新运行”代替指定的 `runId`。Sage 原生运行主键只在内部使用。
- 这些标识本身不是凭据。接口无应用层密钥校验，任何能访问 Sage HTTP 服务的调用方均可使用这些路由。

## HTTP 资源

| 方法与路径 | 输入 | 返回与约束 |
| --- | --- | --- |
| `PUT /api/agents/{agent_id}/workspace/files` | `{directory, files}`；`files` 为相对文件名到 base64 内容的映射 | 仅创建缺失文件；同内容重试成功，冲突返回 409；最多 256 个文件、单文件 4 MiB、总计 16 MiB。 |
| `POST /api/agents/{agent_id}/runs?workspace_path=...` | AG-UI Run 请求；可带 `runtimeContext` 对象 | SSE；工作目录是当前租户、Agent 工作区下经过校验的相对路径。`runtimeContext` 由可信业务调用方提供，作为当前运行的 `system_context`，不写入 Agent 的共享配置。 |
| `GET /api/agents/{agent_id}/runs/{thread_id}/{run_id}` | 无 | 返回 `threadId`、`runId`、状态、最终条目和当前交互及其预期修订号。`run_id` 是提交时的 AG-UI `runId`。 |
| `POST /api/agents/{agent_id}/runs/{thread_id}/{run_id}/reply` | `{interaction_id, decision, payload, expected}` | 仅在交互 ID 和修订号仍匹配时恢复。 |
| `POST /api/agents/{agent_id}/runs/{thread_id}/{run_id}/cancel` | 无 | 仅取消该运行；已终止运行不再改变。 |
| `GET /api/agents/{agent_id}/runs/{thread_id}/{run_id}/files` | 无 | 下载该运行绑定的工作目录，最多 32 MiB、512 项；旧运行在同会话出现新运行后返回 409，避免把新文件误标为旧运行产物。 |

工作区是 Agent 可以修改的运行目录；执行中的文件下载只是读取时的快照，不能视作稳定构建。调用方必须检查自身的产物清单与 `runId`，并持久化通过校验的构建。Sage 不执行项目构建，也不解释业务清单。
