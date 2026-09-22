# Sage Server v2

多用户 AG-UI 宿主。代码直接在 `app/server_v2/`，前端在 `web/`。

```text
api/            HTTP 路由与鉴权
schemas/        OpenAPI / 请求响应 DTO
services/       跨聚合用例（现为 Sage runtime + AG-UI）
domain/         领域记录与规则，不碰 SQL
repositories/   MySQL 仓储（实现 domain 端口）
db/             表元数据
storage/        工作区 / session 目录
agui/           AG-UI 映射与回放
core/           基础设施
```

新业务按 `domain/<name>.py` + `repositories/<name>.py` 加；有跨表/跨系统编排再加 `services/<name>.py`。

生产启动只强制 MySQL：`SAGE_SERVER_MYSQL_URL`。AG-UI 回放直接读取 Sage Session 的 canonical RuntimeEvent，Redis 不再是聊天事件事实源或启动依赖。

单进程并发可用 `SAGE_SERVER_MAX_CONCURRENT_RUNS`（默认 8）、`SAGE_SERVER_MAX_CONCURRENT_RUNS_PER_USER`（默认 2）和 `SAGE_SERVER_MAX_PENDING_RUNS`（默认 1024）配置。参数必须为正数，分别约束总执行、每用户执行及等待队列，见[单机并发说明](../../docs/zh/architecture/sagents-v2-single-host-concurrency.md)。

配 MySQL 只让 Session 状态跨重启存活，**不等于可以横向扩容**：SessionStore 拒绝第二个 writer（`multi_process_writes: False`），订阅者留在进程内，Scheduler 与 JobRuntime 仍是内存实现。因此 Server 目前只支持单 worker；第二个进程会在 SessionStore 获取独占 writer 锁时直接启动失败。manifest 的 `required_guarantees` 会在装配阶段校验 SessionStore 的事务性、持久性与 actor 授权能力。

```bash
cd app/server_v2/web && npm install && npm run build
cd ../../..
python -m app.server_v2 --data-root /tmp/sage-server-v2
```

开发也可开 Vite：`app/server_v2/web` 的 `npm run dev` 代理到 `8090`。

读 `app/server_v2/.env`（进程环境变量优先）。生产必须设置 `SAGE_SERVER_JWT_SECRET`（至少 32 字节）。默认管理员：`admin` / `admin12345`。OpenAPI 在 `/docs`。

成功/失败 JSON 都带 `request_id`，并回写 `X-Request-ID`。可传入该请求头以透传。

## 数据

| 数据 | 生产 | 测试 |
|---|---|---|
| 用户 / catalog / 会话索引 | MySQL `users` / `catalogs` / `threads` | Memory mock |
| Sage Session | `sage.session.mysql`（无表前缀） | filesystem（`data_root/runtime/sessions`） |
| AG-UI 回放 | Sage Session `run_events` | Sage Session `run_events` |
| 工作区 | `{data_root}/tenants/{user_id}/workspace/` | 同左 |
| Skill catalog | MySQL `skills` / `skill_versions` / `agent_skill_selections`；artifact 相对路径 `{data_root}/skills/...` | Memory mock + 同左磁盘 |
| Agent / MCP | `catalogs` JSON：`agents[]`（提示词、model_id、tools、skills）+ `mcp_servers[]` | 同左 |

对话：首次 run 把 `agent_id` 钉在会话上（之后忽略下拉/`forwardedProps`）；读 catalog Agent → Official 文件/沙箱工具 + MCP + skill 组成 Composite，再 `materialize_agent` 加载 sagents/v2 loop。进程 Application 只 build 一次。

`/health` 的 `backends` 按实际装配报告（`mysql` / `memory` / `filesystem` / `session-store` / `stdout`）。sagents 结构化日志由 host 固定接到 `sage.logging.stdout`，默认输出 `sage.log/v1` JSONL；`SAGE_SERVER_LOG_LEVEL` 控制最低级别，`SAGE_SERVER_LOG_FORMAT` 可显式切到本地阅读用的 `text`。stdout 的持久化由容器日志驱动或 Alloy/Loki 负责，不写审计业务表。

模型客户端池使用 `SAGE_SERVER_MAX_MODEL_CLIENTS`（默认 64）限制容量。同一用户的相同配置跨 Run 复用连接，凭据变化使用新客户端；池满且所有客户端占用时返回可重试的限流错误。详见[模型池与增量持久化](../../docs/zh/architecture/sagents-v2-model-pool-and-persistence.md)。

## 完整 Agent 包平台与 Studio

`/studio` 提供完整包定义编辑、普通 Agent 导入、不可变版本、复制/切换版本、运行、事件、任务历史、反馈、人工审批和同 Session 续接。对应 HTTP 入口为 `/api/agent-packages`。普通 Agent 可选择 `agent_package_*` 工具，通过同一管理服务创建并调用其他 Agent。

生产库存使用 MySQL `managed_agent_records`；managed Session 使用独立 MySQL 前缀，验证用临时文件存储。旧聊天与包任务共享运行/用户额度、模型额度和 JobRuntime。可通过 `SAGE_SERVER_MAX_MANAGED_APPLICATIONS`（默认 32）和 `SAGE_SERVER_MAX_MANAGED_BUILDS`（默认 4）控制实例与装配容量。

包模型使用 `provider=server`，`model` 指向本人模型 ID 或 `default`，不携带凭据和地址。源码插件默认关闭，只有宿主注册与明确授权后才能加载，且属于可信宿主代码。能力、API、部署成本和验证边界见 [Server V2 Agent 平台](../../docs/zh/architecture/SERVER_V2_AGENT_PLATFORM.md)。
