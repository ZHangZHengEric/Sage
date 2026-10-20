# Sage Server v1 部署

此目录集中维护 v1 的 Compose、Kubernetes、镜像构建和 nginx 配置，只部署 Server 与 Web，环境仅支持 `dev`、`prod`。基础服务由外部部署管理。

以下命令均以仓库根目录为当前目录，镜像构建上下文仍为仓库根目录。脚本也可从其他工作目录通过完整路径调用。

## Docker Compose

复制目标环境模板，并填写外部服务地址及密钥：

```bash
cp app/v1/deploy/dev/.env.example app/v1/deploy/dev/.env
cp app/v1/deploy/prod/.env.example app/v1/deploy/prod/.env
# 修改 SAGE_MYSQL_HOST、SAGE_MYSQL_PORT、账号密码和 SAGE_S3_ENDPOINT 等配置
app/v1/deploy/compose.sh dev up -d --build
app/v1/deploy/compose.sh prod up -d --build
```

`app/v1/deploy/compose.sh` 默认使用 `prod`，也可设置 `DEPLOY_ENV=dev`。脚本优先读取 `app/v1/deploy/<env>/.env`，不存在时回退到仓库根目录 `.env`；可通过 `ENV_FILE=/path/to/.env` 显式指定。Compose 项目名默认为 `sage_dev` 或 `sage_prod`，可用 `SAGE_COMPOSE_PROJECT_NAME` 覆盖。

每个环境只启动 Server 和 Web。MySQL 与 S3 地址必须指向容器可访问的外部服务，模板中的 `mysql.example.com`、`s3.example.com:9000` 需要替换。原有基础服务容器和持久化数据由其所属部署单独管理。

保留 `SAGE_SHARED_NETWORK`（默认 `sage_shared_default`）和 `LING_SHARED_NETWORK`（默认 `ling_shared_default`）的网络接入，以连接独立部署的基础服务及 Ling。脚本在 `up` 时创建缺失网络；外部容器需由其部署入口接入相同网络，或使用可路由的服务地址。`config`、`logs`、`down` 等命令只操作当前环境的应用 Compose。

默认端口：dev 后端 `30150`、Web `30151`；prod 后端 `30050`、Web `30051`。可用 `SAGE_SERVER_PORT`、`SAGE_WEB_PORT` 覆盖。

可指定服务或透传其他 Compose 命令；dev 环境会将 `sage-server`、`sage-web` 映射为 `sage-server-dev`、`sage-web-dev`：

```bash
app/v1/deploy/compose.sh dev up -d sage-server
app/v1/deploy/compose.sh dev logs -f sage-server
app/v1/deploy/compose.sh prod config --services
app/v1/deploy/compose.sh prod down
```

观测接入可通过 `SAGE_TRACE_JAEGER_URL`、`SAGE_TRACE_JAEGER_PUBLIC_URL` 和 Web 构建参数 `SAGE_GRAFANA_PUBLIC_URL` 指向独立部署的平台；默认留空。Web 不再代理本地 Jaeger。

脚本优先使用 `docker compose`，兼容 `docker-compose`，保留 Compose 原生输出。

## Kubernetes

Kubernetes 同样只部署 Server、Web，环境仅支持 `dev`、`prod`：

```bash
cp app/v1/deploy/dev/.env.example app/v1/deploy/dev/.env
cp app/v1/deploy/k8s/env/dev.env.example app/v1/deploy/k8s/env/dev.env
# 编辑应用配置，填写集群内可访问的外部 MySQL、S3 地址及密钥
DEPLOY_ENV=dev app/v1/deploy/k8s/scripts/deploy.sh
DEPLOY_ENV=dev app/v1/deploy/k8s/scripts/delete.sh
```

prod 使用对应的 `app/v1/deploy/prod/.env` 和 `app/v1/deploy/k8s/env/prod.env`。更多配置见 [Kubernetes 指南](k8s/README.md)。

迁移已有部署时，相对 `SAGE_ROOT` 以新的 Compose 文件目录为基准；请将其改为原数据目录的绝对路径后再启动，继续使用已有数据。
