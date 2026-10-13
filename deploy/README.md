# Sage Deploy

`deploy/compose_v2.sh` 部署 Sage Server v2 及其 Web。原有 `deploy/compose.sh` 和 Kubernetes 模板仍属于 v1。v2 配置详见 [服务指南](../app/v2/server/README.md)，仅支持单 worker。

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

### Server v2：Web 和后端，连接外部 MySQL

`deploy/compose_v2.sh` 使用 `deploy/standalone/docker-compose.yml`，仅启动 `sage-server-v2`、`sage-web-v2`。后端通过 Python 3.12 执行 `python -m app.v2.server`；Web 构建自 `app/v2/server/web`，Nginx 代理 `/api`、`/a2a` 等 v2 路由并支持 SSE。

V2 后端镜像使用独立的 `deploy/images/requirements.server_v2.txt`，仅安装 V2 运行及构建依赖，保留 MySQL、MCP、A2A 和链路追踪能力。随后通过 `--no-deps` 安装项目，避免重新引入公共依赖。`pyproject.toml`、根目录 `requirements.txt` 及其他端的构建方式保持不变；源码执行 `pip install '.[server-v2,otel]'` 仍安装原有公共依赖。

该镜像不预装旧版抓取和文档处理工具包；在容器内执行需要这些包的 Skill 或自定义 MCP 子进程时，需在自定义镜像中按其要求安装依赖。修改业务源码仍可复用依赖层，修改 V2 专用依赖文件才会使该层重新安装（前置构建层不变时）。

在仓库根目录执行：

```bash
cp deploy/standalone/.env.example deploy/standalone/.env
# 编辑 .env，填写 MySQL URL、随机 JWT 密钥和管理员密码
# JWT 密钥可用 openssl rand -hex 32 生成
deploy/compose_v2.sh up -d --build
```

Web 地址为 `http://localhost:32001/`（Studio 为 `/studio`），后端为 `http://localhost:32000`。宿主机端口分别由 `SAGE_WEB_PORT`、`SAGE_SERVER_PUBLISHED_PORT` 控制；容器内部后端固定监听 `8090`。`SAGE_SERVER_PUBLIC_URL` 填浏览器/外部 Agent 实际可访问的 Web 地址。

v2 不读取旧版 MySQL 分项变量、`SAGE_JWT_KEY`、OpenSandbox 或 S3 配置。已有旧模板 `.env` 需要按新模板更新，必要配置为：

```dotenv
SAGE_SERVER_MYSQL_URL=mysql://sage:password@host.docker.internal:3306/sage_v2
SAGE_SERVER_JWT_SECRET=replace-with-a-random-secret-at-least-32-bytes
SAGE_SERVER_ADMIN_USERNAME=admin
SAGE_SERVER_ADMIN_PASSWORD=change_this_admin_password
```

MySQL 请准备独立的 `sage_v2` 数据库及账号权限，不与 v1 共用业务表。URL 中用户名和密码的特殊字符需要百分号编码，例如 `@` 写为 `%40`。同机 MySQL 使用 `host.docker.internal` 和宿主机映射端口；远程 MySQL 使用可访问的 IP 或域名。Compose 不启动 MySQL、Redis、RustFS 或观测服务，也不依赖外部共享网络。

数据与日志分别持久化到 `${SAGE_ROOT}/sage-server/data`、`${SAGE_ROOT}/sage-server/logs`；相对路径以 `deploy/standalone/` 为基准。只运行单个后端进程，并发额度通过 `SAGE_SERVER_MAX_CONCURRENT_RUNS` 等变量设置。

脚本默认读取 `deploy/standalone/.env`，可用 `ENV_FILE=/path/to/.env` 指定其他配置。项目名默认为 `sage_standalone`，可用 `SAGE_COMPOSE_PROJECT_NAME` 覆盖。支持 `deploy/compose_v2.sh down`、`deploy/compose_v2.sh logs -f sage-server` 等 Compose 命令，可从任意工作目录调用。

### 完整环境部署

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

脚本优先使用 Docker Compose v2 的 `docker compose`；如果当前机器没有 v2 插件，但安装了旧版 `docker-compose` 二进制，会自动回退到 `docker-compose`。

`up` 部署流程保留 Docker Compose 原生 build/start 输出。

`wiki`、`rustfs`、`redis` 使用共享 compose 文件 `deploy/docker-compose.shared.yml`，不再在 `dev`、`prod`、`test` 的 compose 文件中重复定义。`prometheus`、`grafana`、`cadvisor`、`loki`、`alloy`、`jaeger` 单独放在 `deploy/docker-compose.observability.yml`。

执行 `deploy/compose.sh <env> up -d` 时，脚本会先确认 `sage_shared_default` Docker 网络存在；不存在则创建。未指定 service 时，脚本会用 `sage_shared` compose project 启动 shared 服务，再启动当前环境服务；显式指定 service 时，脚本会自动使用 `--no-deps` 只启动指定服务，不重建其他 shared、环境或观测服务。Shared、环境服务和观测服务都会通过 `SAGE_SHARED_NETWORK=sage_shared_default` 接入同一个网络。Shared 和观测服务固定使用 `sage-*` 容器名。

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

`dev`、`prod`、`test` 的 `.env.example` 只保留应用启动通常必须改的值，例如 `SAGE_ROOT`、`SAGE_ENV`、密钥和外部服务地址。Docker Compose 项目名由 `deploy/compose.sh` 按环境自动设置为 `sage_dev`、`sage_prod` 或 `sage_test`，不再放进业务环境模板；确需覆盖时可在 shell 中设置 `SAGE_COMPOSE_PROJECT_NAME`。Kubernetes 专属配置不放在这些环境模板里，统一放在 `deploy/k8s/env/*.env.example`。共享服务默认端口为 Wiki `30057`、RustFS `30054` / `30055`、Redis `30056`、Jaeger OTLP `4317` / `4318`、Prometheus `30090`、Loki `30091`、Alloy `30092`、Grafana `30093`；需要覆盖时仍可在 `.env` 中显式设置 `SAGE_SERVER_PORT`、`SAGE_WEB_PORT`、`SAGE_MYSQL_PUBLISHED_PORT`、`SAGE_WIKI_PORT`、`SAGE_RUSTFS_API_PORT`、`SAGE_RUSTFS_CONSOLE_PORT`、`SAGE_REDIS_PORT`、`SAGE_REDIS_PASSWORD`、`SAGE_JAEGER_OTLP_GRPC_PORT`、`SAGE_JAEGER_OTLP_HTTP_PORT`、`SAGE_PROMETHEUS_PORT`、`SAGE_LOKI_PORT`、`SAGE_ALLOY_PORT`、`SAGE_GRAFANA_PORT`、`SAGE_GRAFANA_PUBLIC_URL`。

Prometheus 会通过 Docker discovery 动态抓取当前运行的 `sage-server*` 容器 `/api/observability/metrics`，并抓取 `sage-cadvisor:8080` 的容器指标。服务容器会写入 Docker labels，Prometheus 和 Alloy 会统一转成 `environment` 观测标签：

```env
SAGE_ENV=development
```

同一台机器同时运行多个环境时，每个环境的 `.env` 要使用自己的 `SAGE_ENV`。观测标签默认跟随 `SAGE_ENV`；如果部署现场确实需要覆盖观测标签，可以额外设置 `SAGE_OBSERVABILITY_ENV`。机器 A 和机器 B 各自保留本机 Prometheus、Loki、Alloy、Jaeger，Grafana 只部署在展示机器上，并通过数据源切换机器。

Grafana 默认管理员账号可通过 `SAGE_GRAFANA_ADMIN_USER` / `SAGE_GRAFANA_ADMIN_PASSWORD` 覆盖。仓库不再提交默认 datasource provisioning；Prometheus、Loki、Jaeger 数据源属于部署现场配置，请在展示机器的 Grafana UI 或本机未提交的 provisioning 文件中配置机器 A / 机器 B 的数据源。Dashboard 通过 datasource 变量选择要查看的机器，并通过 `environment` 变量区分 dev/prod/test。

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
