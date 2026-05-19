# Sage Deploy

部署相关文件统一放在 `deploy/` 下：

- `deploy/images/`: Dockerfile、entrypoint、Jaeger 配置等共享镜像构建资源
- `deploy/monitoring/`: Prometheus、Loki、Alloy 等共享监控配置
- `deploy/nginx/`: 不区分环境的 nginx 配置，例如 Wiki
- `deploy/dev/`: 开发环境 Docker Compose 与环境变量模板
- `deploy/prod/`: 生产环境 Docker Compose 与环境变量模板
- `deploy/test/`: 测试环境 Docker Compose 与环境变量模板
- `deploy/k8s/`: Kubernetes 共享资源模板和部署脚本

各环境的 Web nginx 配置放在对应环境目录内，例如 `deploy/dev/nginx/nginx.conf`、`deploy/prod/nginx/nginx.conf`、`deploy/test/nginx/nginx.conf`。Wiki nginx 配置不区分环境，统一使用 `deploy/nginx/nginx_wiki.conf`。

## Docker Compose

先按目标环境创建 `.env`：

```bash
cp deploy/dev/.env.example deploy/dev/.env
cp deploy/prod/.env.example deploy/prod/.env
cp deploy/test/.env.example deploy/test/.env
```

推荐通过环境入口部署：

```bash
deploy/compose.sh up -d
deploy/compose.sh dev up -d
deploy/compose.sh prod up -d
deploy/compose.sh test up -d
```

`deploy/compose.sh` 默认使用 `prod` 环境；也可以通过第一个参数指定 `dev`、`prod` 或 `test`。脚本默认优先读取 `deploy/<env>/.env`；如果该文件不存在，则回退读取仓库根目录 `.env`。也可以通过 `ENV_FILE=/path/to/.env` 显式指定配置文件。

`wiki`、`rustfs`、`redis`、`jaeger`、`prometheus`、`grafana`、`cadvisor`、`loki`、`alloy` 使用共享 compose 文件 `deploy/docker-compose.shared.yml`，不再在 `dev`、`prod`、`test` 的 compose 文件中重复定义。

也可以直接指定对应 compose 文件：

```bash
SAGE_REPO_ROOT=$PWD SAGE_DEPLOY_DIR=$PWD/deploy docker compose --env-file deploy/dev/.env -f deploy/dev/docker-compose.yml -f deploy/docker-compose.shared.yml up -d
SAGE_REPO_ROOT=$PWD SAGE_DEPLOY_DIR=$PWD/deploy docker compose --env-file deploy/prod/.env -f deploy/prod/docker-compose.yml -f deploy/docker-compose.shared.yml up -d
SAGE_REPO_ROOT=$PWD SAGE_DEPLOY_DIR=$PWD/deploy docker compose --env-file deploy/test/.env -f deploy/test/docker-compose.yml -f deploy/docker-compose.shared.yml up -d
```

`dev`、`prod`、`test` 的 `.env.example` 已区分 `COMPOSE_PROJECT_NAME`、容器名前缀、server/web/mysql/es 宿主机端口、`SAGE_ENV`、命名空间和默认数据目录。共享服务默认端口为 Wiki `30057`、RustFS `30054` / `30055`、Redis `30056`、Jaeger OTLP `4317` / `4318`、Prometheus `30090`、Loki `30091`、Alloy `30092`、Grafana `30093`；需要覆盖时仍可在 `.env` 中显式设置 `SAGE_WIKI_PORT`、`SAGE_RUSTFS_API_PORT`、`SAGE_RUSTFS_CONSOLE_PORT`、`SAGE_REDIS_PORT`、`SAGE_REDIS_PASSWORD`、`SAGE_JAEGER_OTLP_GRPC_PORT`、`SAGE_JAEGER_OTLP_HTTP_PORT`、`SAGE_PROMETHEUS_PORT`、`SAGE_LOKI_PORT`、`SAGE_ALLOY_PORT`、`SAGE_GRAFANA_PORT`。

Prometheus 会抓取 `sage-server:8080/api/observability/metrics` 和 `sage-cadvisor:8080`；dev/test 的 server 服务通过 compose network alias 暴露为统一的 `sage-server`。
Grafana 默认管理员账号变量为 `SAGE_GRAFANA_ADMIN_USER` / `SAGE_GRAFANA_ADMIN_PASSWORD`，并预置 Prometheus 与 Loki 数据源。

Elasticsearch 默认不随 `deploy/compose.sh prod up -d` 启动。需要内置 ES 时，使用 `deploy/compose.sh prod --profile es up -d`，或显式指定 `deploy/compose.sh prod up -d sage-es`。

## Kubernetes

Kubernetes 使用同一套资源模板，按 `DEPLOY_ENV` 读取对应环境变量：

```bash
cp deploy/prod/.env.example deploy/prod/.env
DEPLOY_ENV=prod deploy/k8s/scripts/deploy.sh

cp deploy/dev/.env.example deploy/dev/.env
DEPLOY_ENV=dev deploy/k8s/scripts/deploy.sh

cp deploy/test/.env.example deploy/test/.env
DEPLOY_ENV=test deploy/k8s/scripts/deploy.sh
```

删除资源：

```bash
DEPLOY_ENV=dev deploy/k8s/scripts/delete.sh
```

更多 Kubernetes 参数见 `deploy/k8s/README.md`。
