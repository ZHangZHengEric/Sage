# Sage Deploy

部署相关文件统一放在 `deploy/` 下：

- `deploy/images/`: Dockerfile、entrypoint、Jaeger 配置等共享镜像构建资源
- `deploy/dev/`: 开发环境 Docker Compose 与环境变量模板
- `deploy/prod/`: 生产环境 Docker Compose 与环境变量模板
- `deploy/test/`: 测试环境 Docker Compose 与环境变量模板
- `deploy/k8s/`: Kubernetes 共享资源模板和部署脚本

各环境的 nginx 配置放在对应环境目录内，例如 `deploy/dev/nginx/nginx.conf`、`deploy/prod/nginx/nginx.conf`、`deploy/test/nginx/nginx.conf`，不会放在共享镜像构建目录。

## Docker Compose

先按目标环境创建 `.env`：

```bash
cp deploy/dev/.env.example deploy/dev/.env
cp deploy/prod/.env.example deploy/prod/.env
cp deploy/test/.env.example deploy/test/.env
```

推荐通过环境入口部署：

```bash
deploy/compose.sh dev up -d
deploy/compose.sh prod up -d
deploy/compose.sh test up -d
```

`deploy/compose.sh` 默认优先读取 `deploy/<env>/.env`；如果该文件不存在，则回退读取仓库根目录 `.env`。也可以通过 `ENV_FILE=/path/to/.env` 显式指定配置文件。

也可以直接指定对应 compose 文件：

```bash
docker compose --env-file deploy/dev/.env -f deploy/dev/docker-compose.yml up -d
docker compose --env-file deploy/prod/.env -f deploy/prod/docker-compose.yml up -d
docker compose --env-file deploy/test/.env -f deploy/test/docker-compose.yml up -d
```

`dev`、`prod`、`test` 的 `.env.example` 已区分 `COMPOSE_PROJECT_NAME`、容器名前缀、宿主机端口、`SAGE_ENV`、命名空间和默认数据目录。需要并行启动多个环境时，保持这些值互不冲突即可。

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
