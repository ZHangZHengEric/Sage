---
layout: default
title: 故障排查
nav_order: 11
lang: zh
ref: v2-TROUBLESHOOTING
---

{% include lang_switcher.html %}

# 故障排查

| 现象 | 检查项 |
| --- | --- |
| v2 导入或 sidecar 因 Python 失败 | 使用 Python 3.12+，确认仓库 `.venv` 指向正确解释器。 |
| YAML 字符串被当成文件名 | 先调用 `SageManifestLoader().loads(text)`，再交给 `build()`。 |
| Manifest 校验失败 | 检查错误详情、schema 版本、Agent 必填名称、重复 YAML 键和插件配置。 |
| 没有配置模型 | Desktop 添加路由并分配给 Agent；嵌入式提供 manifest 声明的凭据；Server 配置该用户的模型 catalog。 |
| Server 启动失败 | 检查 MySQL 连通性和 `SAGE_SERVER_MYSQL_URL`，不需要 Redis。 |
| 第二个 Server worker 启动失败 | 内置 Session 存储使用独占 writer，保持单 worker。 |
| MCP 工具不可用 | 检查连接和发现错误，启用不等于发现成功。 |
| Run 一直等待 | 查看待处理交互，通过宿主批准、拒绝或提供输入。 |
| 工具结果不明 | 检查已记录副作用并核对后再决定重试，避免盲目重放。 |
| 上下文超限 | 配置实际模型窗口和预算，固定指令不能静默丢弃。 |

反馈时提供应用入口、Python/Flutter 版本、Run 或请求 ID、脱敏日志和复现步骤。不要公开 API Key 或原始凭据 catalog。

[配置](CONFIGURATION.md) · [服务端设置](ENV_VARS.md) · [运行时参考](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/README.md)
