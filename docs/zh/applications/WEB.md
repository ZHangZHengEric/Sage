---
layout: default
title: Server v2
nav_order: 3
lang: zh
ref: v2-applications-WEB
parent: 应用入口
---

{% include lang_switcher.html %}

# Server v2

## 环境要求

Python 3.12+、MySQL 和 Node.js 22.12+。先完成[源码环境安装](GETTING_STARTED.md)。**Redis 已不是 Server v2 的启动依赖。**

## 启动

在仓库根目录、已激活 Python 环境的终端中运行：

```bash
python -m pip install -e '.[server-v2]'
cp app/server_v2/.env.example app/server_v2/.env
```

在 `app/server_v2/.env` 中配置 `SAGE_SERVER_MYSQL_URL`、自己的 `SAGE_SERVER_JWT_SECRET`（至少 32 字节），以及初始管理员账号。

```bash
cd app/server_v2/web
npm install
npm run build
cd ../../..
python -m app.server_v2
```

打开 [http://127.0.0.1:8090](http://127.0.0.1:8090)，登录后配置模型和 Agent。`/studio` 管理 Agent 包，`/docs` 提供当前服务的 OpenAPI。

开发前端时，在 `app/server_v2/web` 中运行 `npm run dev`，Vite 代理到 8090 端口。进程环境变量优先于组件 `.env` 文件。

## 存储与部署边界

- MySQL 保存用户、catalog、thread 索引、Agent 包库存和运行时 Session。
- AG-UI 回放直接读取 Sage Session 的权威 RuntimeEvent，不依赖另一份 Redis 事件日志。
- 工作区文件保存在配置的数据根目录下，按租户分隔。
- 使用**单 worker**。内置 SessionStore 拒绝第二个 writer；Scheduler 和 JobRuntime 不提供多宿主持久运行保证。

[`deploy/`](https://github.com/ZHangZHengEric/Sage/blob/main/deploy/README.md) 包含多套部署配置，使用前应核对具体环境的镜像和启动模块，不能将所有 Compose 环境都视作 Server v2。

[环境变量](../ENV_VARS.md) · [HTTP API](../api/HTTP_API_REFERENCE.md) · [组件参考](https://github.com/ZHangZHengEric/Sage/blob/main/app/server_v2/README.md)
