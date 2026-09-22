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
app = await SAgentBuilder().with_defaults(session_root="runtime").build(manifest)
```

`build()` 也接受 `ResolvedSageManifest`，或指向名为 `sage.yaml` 文件的路径。普通字符串按路径处理。`loads()` 不解析相对指令文件；应使用内联指令，或改用文件加载器。

## 执行与生命周期

1. 获取 `app.entrypoint()`。
2. 使用宿主认证后的 `ActorRef` 创建 `RequestContext`。
3. 通过 `run_stream(command, context)` 提交 `StartRun`。
4. 消费 `stream.events`；`await stream.wait()` 返回带 `.state` 的 `RunSnapshot`。
5. 在 `finally` 中关闭 `app`。

每个逻辑请求使用新的幂等键，仅重试同一请求时复用该键。生产适配器不能信任客户端传入的用户 ID。访问 Session 应使用带上下文的 `app.service("session.access")`，原始 SessionStore 是受信任的内部接口。

取消、steer、恢复和交互回复都使用明确命令；断开事件流只会 detach 当前观察者。返回的快照可能处于暂停状态，不一定是终态。

[完整可运行示例](../applications/GETTING_STARTED.md) · [Facade](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/sagent.py) · [命令](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/contracts/commands.py) · [Builder](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/builder.py)
