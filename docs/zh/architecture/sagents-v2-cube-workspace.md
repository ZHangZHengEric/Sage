---
layout: default
title: Cube 外置工作区与执行
parent: 架构
nav_order: 16
lang: zh
ref: v2-cube-workspace
---

{% include lang_switcher.html %}

# Cube 外置工作区与执行

Server 可显式选择 `sage.sandbox.cube-volume`，由 Cube 保存工作区并执行工具命令。
默认仍使用本地沙箱。本模式面向单个 Sage Server；调度、JobRuntime、模型调用、
会话、记忆索引、Skill 源包及配置继续留在原有服务中，不支持多 Sage 实例接管。

## 启用

原生部署安装可选依赖：

```bash
python -m pip install '.[server,cube]'
```

在已有 Server 环境配置中添加：

```dotenv
SAGE_SERVER_SANDBOX_PLUGIN=sage.sandbox.cube-volume
SAGE_SERVER_CUBE_API_URL=http://cube-api:3000
SAGE_SERVER_CUBE_TEMPLATE_ID=your-linux-python-template
SAGE_SERVER_CUBE_PROXY_NODE_IP=cube-proxy
SAGE_SERVER_CUBE_API_KEY=
SAGE_SERVER_CUBE_VOLUME_DRIVER=your-persistent-volume-driver
```

Docker 部署另设 `SAGE_INSTALL_CUBE=true`，然后运行
`deploy/compose_v2.sh up -d --build`。这是镜像构建选项；默认镜像不安装 Cube SDK。
配置地址须能由 Sage 访问。模板需要 Linux、Python 3、Shell 和 Agent 使用的工具；
本地镜像中的 Node、浏览器、字体等不会自动出现在远程模板中。

SDK 要求 `cubesandbox>=0.7.3,<1`，Cube 平台须支持持久 Volume 及只读挂载。
Volume driver 决定底层持久化及文件一致性，需要实际部署可用的持久存储。
此版本要求默认 `sage.scheduler.ephemeral`，不能与分布式调度器组合。

## 文件与计算生命周期

每个租户、Agent 对应稳定的 Volume 身份，不绑定 Session。每个 Run 使用独立 VM，
结束时释放计算环境、保留 Volume。父子 Run 默认共享 Volume、分别拥有计算环境；
私有子工作区使用独立 Volume，只读策略使用只读挂载。

文件工具、Shell、网页文件树、下载、外部 API 导入与删除都访问同一 Volume。
没有活跃 Run 时，文件管理会临时创建 VM，用完释放。初始化只创建缺失的种子文件，
Skill 经沙箱文件接口物化。显式同步完整 Skill 时先暂存新目录，再替换目标；
原目录保留为远程 `skills/.sage-backup-*`。租户文件不复制回本地 tenants 目录，
临时下载缓冲和种子渲染除外。

Shell 沿用本地 JobRuntime，通过 `process.run` 在 Cube 执行。远程监督程序限制输出和
执行时长；取消时请求停止命令进程组，确认退出后清理临时状态。网络故障导致退出
无法确认时明确报错，远端执行时长限制仍生效。

## 当前边界

- 切换本地与 Cube 模式不自动迁移文件，远程失败也不会回退到本地。
- 已受理 Run 冻结后端、模板、工作区身份和策略；切换配置只用于新 Run。
- Sage 重启后的新 Run 可挂载原 Volume。旧的未完成 Run 绑定原进程实例，恢复时明确失败，
  不自动重放远程命令；需要提交新 Run。不接管重启前运行中的 Shell。
- 不提供 VM 内存快照、交互 stdio、沙箱内 stdio MCP 或工作区自配置工具。
- 文件工具单文件上限为 8 MiB；外部导入仍受原 4 MiB/文件、16 MiB/请求限制。
  二进制上传接口支持最大 64 MiB，分块暂存后发布并校验幂等重试；
  下载支持有界分块读取、目录 ZIP 及顶层目录排除。
- 支持 `none` / `unrestricted` 进程网络策略，不支持 allowlist、代理或私网过滤。
- CPU、内存和总磁盘硬额度依赖 Cube 模板与底层部署。插件不声称强制执行这些额度，
  显式要求硬限制或总工作区字节上限时拒绝。

## 验证

```bash
python -m pytest tests/sagents/v2/test_cube_volume_sandbox.py tests/sagents/v2/test_cube_process.py tests/sagents/v2/test_cube_execution_binding.py
python -m pytest tests/app/v2/server/test_cube_configuration.py tests/app/v2/server/test_cube_workspaces.py tests/app/v2/server/test_cube_execution.py
```

测试运行真实的文件桥接和命令监督脚本，并使用 Cube 模拟器验证 HTTP、租户隔离、
资源清理和重启后的文件持久性，不等同于真实 Cube 集群验收。
