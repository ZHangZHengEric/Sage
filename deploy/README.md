# Sage Server 部署

本目录维护 Server 与 Web 的独立部署。v2 配置详见 [服务指南](../app/v2/server/README.md)，仅支持单 worker。v1 的部署文件与说明位于 [app/v1/deploy](../app/v1/deploy/README.md)。

- `deploy/compose_v2.sh`：v2 部署入口
- `deploy/standalone/`：v2 Compose、nginx 和环境变量模板
- `deploy/images/`：v2 镜像及沙箱前端测试工具构建资源

## Docker Compose

`deploy/compose_v2.sh` 使用 `deploy/standalone/docker-compose.yml`，仅启动 `sage-server-v2`、`sage-web-v2`。后端通过 Python 3.12 执行 `python -m app.v2.server`；Web 构建自 `app/v2/server/web`，Nginx 代理 `/api`、`/a2a` 等 v2 路由并支持 SSE。

V2 后端镜像与源码安装统一使用根目录 `pyproject.toml` 的核心依赖及 `server,otel` extras。镜像先读取元数据安装依赖以保留缓存，再通过 `--no-deps` 安装源码。Desktop 使用 `desktop` extra；v1 独立使用 `app/v1/requirements.txt`。

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

V2 镜像自动创建 `sage-sandbox` 用户（UID/GID `10001:10001`），服务主进程继续以 root 运行，沙箱命令降权后执行。镜像默认设置 `SAGE_SERVER_LINUX_EXECUTION_UID/GID`，已有 `.env` 无需补充即可生效。服务仅调整各用户 `workspace` 及子 Agent 工作目录的属主，不递归修改挂载目录、已有文件、数据库或日志；拒绝通过符号链接调整目录。宿主机无需创建同名账号。如需匹配已有非 root 目录，可在 `.env` 同时覆盖这两个数字 ID；已有文件的读写权限仍需与该身份匹配。NFS root-squash 等禁止 root 修改属主的挂载需由宿主机管理员预先设置工作目录权限。

后端 Compose 的 `systempaths=unconfined` 允许内层 bubblewrap 在独立 PID/user namespace 中挂载 `/proc`，否则 Docker 默认遮蔽的 proc 子挂载会触发 `bwrap: Can't mount proc on /proc: Operation not permitted`。该设置取消外层容器的默认系统路径遮蔽/只读限制；内层沙箱仍保留非 root 身份、独立命名空间、能力清除和 seccomp，不使用 privileged 或宿主机 PID namespace。修改后需要 `deploy/compose_v2.sh up -d --force-recreate sage-server` 重建容器，仅 restart 不会应用新的权限设置。

脚本默认读取 `deploy/standalone/.env`，可用 `ENV_FILE=/path/to/.env` 指定其他配置。项目名默认为 `sage_standalone`，可用 `SAGE_COMPOSE_PROJECT_NAME` 覆盖。支持 `deploy/compose_v2.sh down`、`deploy/compose_v2.sh logs -f sage-server` 等 Compose 命令，可从任意工作目录调用。

Server 本地沙箱的预装前端测试环境、离线调用及隔离限制见
[前端测试环境说明](images/frontend-test/README.md)。
