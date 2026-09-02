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

生产启动强制 MySQL + Redis：`SAGE_SERVER_MYSQL_URL`、`SAGE_SERVER_REDIS_URL`。单测注入 Memory store / 内存回放，不写本地 JSON。

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
| AG-UI 回放 | Redis Stream | 进程内存 |
| 工作区 | `{data_root}/tenants/{user_id}/workspace/` | 同左 |

`/health` 的 `backends` 按实际装配报告（`mysql` / `memory` / `redis` / `filesystem` / `stdout`）。sagents 结构化日志由 host 固定接到 `sage.logging.stdout`，默认输出 `sage.log/v1` JSONL；`SAGE_SERVER_LOG_LEVEL` 控制最低级别，`SAGE_SERVER_LOG_FORMAT` 可显式切到本地阅读用的 `text`。stdout 的持久化由容器日志驱动或 Alloy/Loki 负责，不写审计业务表。
