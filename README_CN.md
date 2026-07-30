# Sage Server

本分支只保留 Sage Server 产品主体：

- `app/server`：FastAPI 服务与 Vue Web 控制台
- `common`：Server 领域服务、持久化与基础设施适配层
- `sagents`：Agent Runtime
- `app/skills`：Server 内置运行时技能
- `mcp_servers/anytool`、`mcp_servers/task_scheduler`：Server 必需的 MCP 能力
- `deploy`：只部署 `sage-server` 与 `sage-web`

Desktop、CLI/TUI、Terminal、浏览器扩展、Wiki 和独立可选 MCP 应用已从本分支移除。

## 本地运行

```bash
cp .env.example.minimal .env
python -m pip install -r requirements.txt
python -m app.server.main
```

另开一个终端启动 Web：

```bash
cd app/server/web
npm ci
npm run dev
```

## 部署

每个环境的 Compose 文件只定义 `sage-server` 和 `sage-web` 两个服务：

```bash
cp deploy/prod/.env.example deploy/prod/.env
deploy/compose.sh prod up -d --build
```

SQLite 是开箱即用的默认存储。MySQL、Elasticsearch、S3 兼容对象存储、OpenTelemetry 和远程沙箱仍可作为外部服务通过环境变量接入，但不再由本仓库部署。

## 验证

```bash
python -m pytest tests/app/server tests/common tests/sagents
cd app/server/web && npm test -- --run && npm run build
docker compose --env-file deploy/prod/.env.example -f deploy/prod/docker-compose.yml config
```

部署说明见 [deploy/README.md](deploy/README.md)。
