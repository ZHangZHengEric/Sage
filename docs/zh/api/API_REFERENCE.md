---
layout: default
title: Python 运行时 API
nav_order: 1
lang: zh
ref: v2-api-API_REFERENCE
parent: API
---

{% include lang_switcher.html %}

# Python 运行时 API

## 配置输入

```python
from sagents.v2 import SAgentBuilder
from sagents.v2.package.manifest import SageManifest, SageManifestLoader

# 直接解析 YAML 字符串，不创建文件。
manifest = SageManifestLoader().loads(yaml_text)
# 也可以校验 Python 字典：
# manifest = SageManifest.model_validate(config_dict)
app = await SAgentBuilder().build(runtime=manifest.runtime, models=model_config)
agent = await app.load_agent(manifest)
```

`load_agent()` 接受 manifest、`ResolvedSageManifest` 或指向 `sage.yaml` 的路径；`build()` 接受 runtime 和 models 配置。普通字符串按路径处理。`loads()` 不解析相对指令文件；应使用内联指令，或改用文件加载器。

## 执行与生命周期

1. 获取 `app.entrypoint()`。
2. 使用宿主认证后的 `ActorRef` 创建 `RequestContext`。
3. 通过 `run_stream(command, context, agent=agent)` 提交 `StartRun`。
4. 消费 `stream.events`；`await stream.wait()` 返回带 `.state` 的 `RunSnapshot`。
5. 在 `finally` 中关闭 `app`。

每个逻辑请求使用新的幂等键，仅重试同一请求时复用该键。生产适配器不能信任客户端传入的用户 ID。访问 Session 应使用带上下文的 `app.service("session.access")`，原始 SessionStore 是受信任的内部接口。

取消、steer、恢复和交互回复都使用明确命令；断开事件流只会 detach 当前观察者。返回的快照可能处于暂停状态，不一定是终态。

`SteerRun` 向当前 Run 的活跃 Turn 追加输入，不创建新 Run，也不重置进度或预算。提交时提供 `run_id`、`expected_turn_id`、`input` 和稳定的 `idempotency_key`；旧参数 `expected_revision` 仍可传入，但不参与入队校验或幂等判断。入队推进 Session revision 和事件序列，不推进执行用的 Run revision；执行器在下一个安全模型边界原子写入消息并消费输入，仍保留执行版本校验。模型会收到中英文运行时提示，按最新要求调整后续工作并保留原任务进度；提示不写入用户消息历史。

`steer.accepted` 只表示已持久化入队，`steer.applied` 表示已在安全边界纳入模型上下文。若 Turn 或 Run 在消费前结束，输入与结束提交一起标记为 `rejected` 并发出 `steer.rejected`，包含原因；不会转投下一轮。暂停保留待消费输入。HTTP 重试使用相同 `messageId`，会返回持久化的当前状态及拒绝原因。

[完整可运行示例](../applications/GETTING_STARTED.md) · [Facade](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/sagent.py) · [命令](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/contracts/commands.py) · [Builder](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/builder.py)
