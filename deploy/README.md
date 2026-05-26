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

`up` 部署流程保留 Docker Compose 原生 build/start 输出。

`wiki`、`rustfs`、`redis` 使用共享 compose 文件 `deploy/docker-compose.shared.yml`，不再在 `dev`、`prod`、`test` 的 compose 文件中重复定义。`prometheus`、`grafana`、`cadvisor`、`loki`、`alloy`、`jaeger` 单独放在 `deploy/docker-compose.observability.yml`。

执行 `deploy/compose.sh <env> up -d` 时，脚本会先确认 `sage_shared_default` Docker 网络存在；不存在则创建。随后脚本会用 `sage_shared` compose project 启动 shared 服务，再启动当前环境服务。Shared、环境服务和观测服务都会通过 `SAGE_SHARED_NETWORK=sage_shared_default` 接入同一个网络。Shared 和观测服务固定使用 `sage-*` 容器名。

观测服务默认不启动。需要 Prometheus、cAdvisor、Loki、Alloy、Jaeger 时，显式加 `--observability`，脚本会在 shared 网络可用后单独启动 `deploy/docker-compose.observability.yml`。Grafana 不随默认观测栈启动，需要在展示机器上显式指定 `sage-grafana`：

```bash
deploy/compose.sh --observability up -d
deploy/compose.sh dev --observability up -d
deploy/compose.sh --observability up -d sage-jaeger
deploy/compose.sh prod --observability up -d sage-grafana
```

Prometheus 默认使用 Git 中的 `deploy/monitoring/prometheus.yml`。需要本机额外抓取目标时，复制 `deploy/monitoring/prometheus.local.yml.example` 为 `deploy/monitoring/prometheus.local.yml`，在本地文件里追加 `scrape_configs` 下的 job 条目即可；该文件不会进 Git。通过 `deploy/compose.sh --observability ...` 启动时，脚本会生成 `deploy/monitoring/prometheus.generated.yml` 并让 Prometheus 挂载这个合并后的配置。

`deploy/docker-compose.observability.yml` 中的 `sage-cadvisor` 当前默认使用 `ghcr.io/google/cadvisor:v0.57.0`，兼容 Docker Engine API `v1.40+`（按 Docker 官方 API version matrix，对应 Docker 19.03 及以上）。为避免 Docker overlayfs 文件数较多时 `/metrics` 超时，cAdvisor 默认关闭 `disk` 类 filesystem usage/inode 指标；CPU、内存、网络和 diskIO 指标仍会采集。

也可以直接指定对应 compose 文件：

```bash
docker network inspect sage_shared_default >/dev/null 2>&1 || docker network create sage_shared_default
SAGE_REPO_ROOT=$PWD SAGE_DEPLOY_DIR=$PWD/deploy SAGE_SHARED_NETWORK=sage_shared_default docker compose --env-file deploy/dev/.env -f deploy/docker-compose.shared.yml -p sage_shared up -d
SAGE_COMPOSE_ENV_FILE=$PWD/deploy/dev/.env SAGE_SHARED_NETWORK=sage_shared_default docker compose --env-file deploy/dev/.env -f deploy/dev/docker-compose.yml up -d
SAGE_DEPLOY_DIR=$PWD/deploy SAGE_SHARED_NETWORK=sage_shared_default docker compose --env-file deploy/dev/.env -p sage_shared -f deploy/docker-compose.observability.yml up -d
```

需要单独启动 shared 服务时，直接指定 shared service 名即可，脚本会把它路由到 `deploy/docker-compose.shared.yml`：

```bash
deploy/compose.sh up -d sage-redis
deploy/compose.sh up -d sage-rustfs
```

`dev`、`prod`、`test` 的 `.env.example` 只保留应用启动通常必须改的值，例如 `SAGE_ROOT`、`SAGE_ENV`、密钥和外部服务地址。Docker Compose 项目名由 `deploy/compose.sh` 按环境自动设置为 `sage_dev`、`sage_prod` 或 `sage_test`，不再放进业务环境模板；确需覆盖时可在 shell 中设置 `SAGE_COMPOSE_PROJECT_NAME`。Kubernetes 专属配置不放在这些环境模板里，统一放在 `deploy/k8s/env/*.env.example`。共享服务默认端口为 Wiki `30057`、RustFS `30054` / `30055`、Redis `30056`、Jaeger OTLP `4317` / `4318`、Prometheus `30090`、Loki `30091`、Alloy `30092`、Grafana `30093`；需要覆盖时仍可在 `.env` 中显式设置 `SAGE_SERVER_PORT`、`SAGE_WEB_PORT`、`SAGE_MYSQL_PUBLISHED_PORT`、`SAGE_ELASTICSEARCH_PUBLISHED_PORT`、`SAGE_WIKI_PORT`、`SAGE_RUSTFS_API_PORT`、`SAGE_RUSTFS_CONSOLE_PORT`、`SAGE_REDIS_PORT`、`SAGE_REDIS_PASSWORD`、`SAGE_JAEGER_OTLP_GRPC_PORT`、`SAGE_JAEGER_OTLP_HTTP_PORT`、`SAGE_PROMETHEUS_PORT`、`SAGE_LOKI_PORT`、`SAGE_ALLOY_PORT`、`SAGE_GRAFANA_PORT`、`SAGE_GRAFANA_PUBLIC_URL`。

Prometheus 会通过 Docker discovery 动态抓取当前运行的 `sage-server*` 容器 `/api/observability/metrics`，并抓取 `sage-cadvisor:8080` 的容器指标。服务容器会写入 Docker labels，Prometheus 和 Alloy 会统一转成 `environment` 观测标签：

```env
SAGE_ENV=development
```

同一台机器同时运行多个环境时，每个环境的 `.env` 要使用自己的 `SAGE_ENV`。观测标签默认跟随 `SAGE_ENV`；如果部署现场确实需要覆盖观测标签，可以额外设置 `SAGE_OBSERVABILITY_ENV`。机器 A 和机器 B 各自保留本机 Prometheus、Loki、Alloy、Jaeger，Grafana 只部署在展示机器上，并通过数据源切换机器。

Grafana 默认管理员账号可通过 `SAGE_GRAFANA_ADMIN_USER` / `SAGE_GRAFANA_ADMIN_PASSWORD` 覆盖。仓库不再提交默认 datasource provisioning；Prometheus、Loki、Jaeger 数据源属于部署现场配置，请在展示机器的 Grafana UI 或本机未提交的 provisioning 文件中配置机器 A / 机器 B 的数据源。Dashboard 通过 datasource 变量选择要查看的机器，并通过 `environment` 变量区分 dev/prod/test。

Elasticsearch 默认不随 `deploy/compose.sh prod up -d` 启动。需要内置 ES 时，使用 `deploy/compose.sh prod --profile es up -d`，或显式指定 `deploy/compose.sh prod up -d sage-es`。

## Kubernetes

Kubernetes 使用同一套资源模板，按 `DEPLOY_ENV` 读取对应环境变量：

```bash
cp deploy/prod/.env.example deploy/prod/.env
cp deploy/k8s/env/prod.env.example deploy/k8s/env/prod.env
DEPLOY_ENV=prod deploy/k8s/scripts/deploy.sh

cp deploy/dev/.env.example deploy/dev/.env
cp deploy/k8s/env/dev.env.example deploy/k8s/env/dev.env
DEPLOY_ENV=dev deploy/k8s/scripts/deploy.sh

cp deploy/test/.env.example deploy/test/.env
cp deploy/k8s/env/test.env.example deploy/k8s/env/test.env
DEPLOY_ENV=test deploy/k8s/scripts/deploy.sh
```

删除资源：

```bash
DEPLOY_ENV=dev deploy/k8s/scripts/delete.sh
```

更多 Kubernetes 参数见 `deploy/k8s/README.md`。
