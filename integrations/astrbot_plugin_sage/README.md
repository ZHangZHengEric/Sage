# Sage Server · AstrBot 桥接插件

将 AstrBot 已接入机器人的消息交给 **Sage Server v2** 执行。插件独立运行在 AstrBot 中，不需要安装 Sage Python 包，不依赖 Desktop，也不修改 Server 原生飞书接入。

```text
聊天平台 → AstrBot → Sage Bridge → Sage Server /a2a/v1
         ←        ←             ← Agent 任务与文本回复
```

## 支持范围

- 同一 AstrBot 实例配置多个机器人；每个机器人 ID 绑定一个 Sage 用户/Agent 的 API Key。
- 私聊文本、图片；群聊通过 @机器人、唤醒词或 `/sage` 命令触发。
- 发送人白名单，以及可选的会话来源 UMO 白名单。
- 每个凭据、机器人、会话来源和发送人分别保存 Sage 会话，群成员不共享个人历史。
- 短任务等待结果；长任务通过 `/sage status` 查询，`/sage cancel` 取消。
- 会话映射通过 AstrBot 插件 KV 存储持久化；提交响应丢失时保留原请求，核对时复用同一个 A2A `messageId`。

首版接收文本和 PNG/JPEG/GIF/WebP 图片，返回纯文本。图片先通过 AstrBot 官方媒体解析接口转换为本地文件，再以 data URI 传递，Sage 不需要访问 AstrBot 本地路径。单条消息的图片总大小默认 4 MiB，文本最多 20000 字符；媒体下载还受 AstrBot 的媒体服务约束。语音、视频和通用文件会明确拒绝整条消息，不会丢弃附件后继续执行。

审批、补充输入在 Sage Web 当前会话中处理。插件不接受 IM 审批指令，也不请求 `a2a:approve`。AstrBot 内部 Agent 的工具、知识库和记忆不会自动迁移到 Sage。

## 安装

要求 Python 3.12+、AstrBot `>=4.29.1,<5`，以及已配置模型和 Agent 的 Sage Server v2。

将本目录完整复制为 AstrBot 的 `data/plugins/astrbot_plugin_sage/`：

```bash
# 在 Sage 仓库根目录执行，将 /path/to/AstrBot 改为实际位置。
cp -R integrations/astrbot_plugin_sage /path/to/AstrBot/data/plugins/
```

按 AstrBot 的插件依赖安装流程安装本目录 `requirements.txt`，然后在管理面板重载插件。也可以把目录打包为 ZIP，在 AstrBot 插件页上传安装。

这是 Sage 单仓库中的独立插件目录，**不能把 Sage 仓库 URL 当作 AstrBot 插件仓库 URL 安装**。`metadata.yaml` 的 `repo` 留空；升级时重新复制本目录或上传新 ZIP。会话数据在 AstrBot 的 `data` 下，不在插件代码目录中。

## 多租户配置

1. 每个租户登录 Sage Server，在 API Key 管理中为自己的目标 Agent 创建专用 Key，授予 `a2a:invoke` 和 `a2a:read`。
2. 在 **AstrBot 服务进程**中配置对应环境变量，例如 `SAGE_TEAM_A_KEY` 和 `SAGE_TEAM_B_KEY`。Docker 部署时将变量注入 AstrBot 容器，不是 Sage 容器；不要把真实 Key 写入插件源码或示例文件。
3. 在 AstrBot 插件配置中填写 Sage 根地址并添加机器人绑定。使用 AstrBot 机器人配置的唯一 ID，不是 `lark`、`telegram` 等平台类型，也不是群号。
4. 添加允许使用该 Agent 的平台原始发送人 ID。需要限制群范围时再填写完整 UMO。
5. 启用插件并重载。环境变量变更需要更新 AstrBot 进程环境；更换 Key 会开启新的会话作用域，避免沿用其他用户或 Agent 的历史。

示例配置（不包含密钥）：

```json
{
  "enabled": true,
  "server_url": "http://sage:8090",
  "request_timeout_seconds": 30,
  "wait_seconds": 15,
  "poll_interval_seconds": 1,
  "max_image_bytes": 4194304,
  "bindings": [
    {
      "__template_key": "sage",
      "platform_id": "lark-team-a",
      "api_key_env": "SAGE_TEAM_A_KEY",
      "allowed_sender_ids": ["ou_alice"],
      "allowed_origins": []
    },
    {
      "__template_key": "sage",
      "platform_id": "telegram-team-b",
      "api_key_env": "SAGE_TEAM_B_KEY",
      "allowed_sender_ids": ["123456789"],
      "allowed_origins": []
    }
  ]
}
```

`server_url` 可以带反向代理路径前缀，不包含 `/a2a/v1`。本机或容器私网可用 HTTP；跨主机传输凭据应使用 HTTPS。请求不跟随重定向，也不使用进程代理环境变量。

空 `bindings` 不接管任何机器人；绑定的 `allowed_sender_ids` 必须非空；空 `allowed_origins` 表示允许白名单发送人的所有会话。配置重复机器人 ID 时拒绝加载，不按顺序猜测租户。配置只允许平台运营方管理，不向租户暴露 AstrBot 的全局配置或插件代码安装权限。

**Sage API Key 是用户/Agent 权限的来源。** 平台消息不能传入租户 ID、替换 Key 或选择其他 Agent。白名单里的 IM 用户使用该 Key 所代表的执行权限，应只加入租户明确授权的成员。共享 AstrBot 实例仍是可信服务边界，不构成进程级租户隔离；需要独立插件或更强隔离时可以按租户部署实例。

## 使用

| 输入 | 行为 |
| --- | --- |
| 文本或图片 | 当前任务空闲时提交；群里需要 @机器人或唤醒词 |
| `/sage` | 查看帮助 |
| `/sage status` | 查询当前任务；有未确认提交时复用原请求核对 |
| `/sage cancel` | 取消当前发送人会话的任务 |
| `/sage new` | 上个任务结束后切换新会话；运行或等待审批时先处理旧任务 |

默认等待 15 秒，最长可配置 60 秒；超时后 Sage 任务继续运行，插件会提示查询。首版没有后台主动推送，请用 `/sage status` 领取长任务结果。发送任务失败或响应丢失不会自动改用 AstrBot 内置 Agent。

被绑定机器人由桥接插件接管，未授权或未唤醒消息也不会继续进入该机器人的默认 Agent 流程。未绑定机器人不受影响。此行为依赖插件启用且被该 AstrBot 配置文件加载；请在接入机器人所用配置中启用插件，并关闭其他插件对该机器人的独立自动 AI 回复。

任务在 Sage Server 中运行，AstrBot 重启不等于取消任务。插件持久化当前 Session、Task 和尚未确认的请求；收到受理确认后立即清除请求正文。每条已受理消息另存只含 Session/Task ID 的回执，跨后续消息和 `/sage new` 保留，不自动过期；清理插件数据也会移除相应去重保证。平台重新投递同一消息不会创建新的 Sage Run，但平台回复不提供 exactly-once 保证。

首次提交明确被拒绝时会清除待提交状态；超时、中断或不确定错误保留原请求供核对。曾出现不确定结果的提交，即使后续重试被拒绝，也继续保留，不能推断第一次没有受理。此时先恢复连接和权限，再用 `/sage status` 核对；核对前不切换新会话。

插件没有跨进程会话锁，同一组机器人配置只运行一个 AstrBot 进程。Sage Server 自身的部署并发边界仍以 Server 文档为准。

## 验证与接口依据

在 Sage 仓库已配置 Server 测试依赖的 Python 环境中执行：

```bash
python -m pytest tests/integrations -q
```

测试覆盖授权、会话隔离、提交丢失恢复、并发提交、输入限制和 AstrBot 消息入口，并使用真实 Sage A2A Router/Runtime 验证双租户、图片、会话续接、新会话与重复消息。模型和外部平台网络使用测试替身；真实平台凭据和消息权限需在部署后联调。

- [AstrBot 插件开发与依赖](https://docs.astrbot.app/dev/star/plugin-new.html)
- [事件优先级和传播控制](https://docs.astrbot.app/dev/star/guides/listen-message-event.html)
- [配置模板](https://docs.astrbot.app/dev/star/guides/plugin-config.html)
- [插件 KV 存储](https://docs.astrbot.app/dev/star/guides/storage.html)
- [Sage Server A2A](../../app/v2/server/README.md#a2a)

本插件沿用 Sage 仓库的 MIT License；AstrBot 本体遵循其自身开源许可。
