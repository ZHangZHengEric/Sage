---
layout: default
title: 配置
nav_order: 5
lang: zh
ref: v2-CONFIGURATION
---

{% include lang_switcher.html %}

# 配置

## 三种配置归属

| 宿主 | 配置来源 |
| --- | --- |
| 嵌入式 SAgents v2 | `SageManifest`：YAML 字符串、校验后的 Python 字典或 `sage.yaml`。 |
| Desktop v2 | 应用持久化设置和 catalog，在界面配置模型与 Agent。 |
| Server v2 | `SAGE_SERVER_*` 环境变量，加上各用户的模型、Agent、Skill 与 MCP catalog。 |

## 加载 manifest

```python
from sagents.v2.package.manifest import SageManifest, SageManifestLoader

manifest = SageManifestLoader().loads(yaml_text)
# 也可以：manifest = SageManifest.model_validate(config_dict)
# 然后：application = await builder.build(manifest)
```

`loads()` 校验 YAML 并拒绝重复键。`load("path/to/sage.yaml")` 还会解析包目录内的指令文件。直接给 `build()` 传普通字符串会走文件加载。内存配置使用内联指令。

`credentials` 声明密钥解析来源；`models` 引用凭据，不携带密钥明文。`agents` 选择指令和模型路由，`entrypoint` 指定入口 Agent。

## OrcaRouter 模型

`orcarouter` 是可选的 provider 预设，复用现有 OpenAI-compatible Chat Completions
实现。在 Server v2 模型表单中选择 `orcarouter`，填写模型 ID 和 API Key。
默认地址为 `https://api.orcarouter.ai/v1`，手动设置的自定义 Base URL 会保留。

嵌入式 manifest 可添加以下模型路由，并在完整 manifest 中配置引用的凭据：

```yaml
models:
  primary:
    provider: orcarouter
    model: your-model
    credential: orcarouter_key
```

省略 `base_url` 时，路由使用同一 OrcaRouter 地址。该预设支持现有聊天协议，
不新增图像或视频生成 API。

## 选择运行组件

通过 `runtime.capabilities` 绑定实现。例如，为延迟加载 Skill 的组件设置 token 预算：

```yaml
runtime:
  capabilities:
    skill.loading:
      plugin: sage.skill.loading.lazy
      config:
        max_active_tokens: 6000
```

以上片段需加入完整 manifest。插件配置经过 schema 校验；能力取决于实际注册的实现，只有元数据声明不代表组件可运行。

[插件扩展](architecture/PLUGINS.md) · [环境变量](ENV_VARS.md) · [完整集成手册](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/使用手册.md)

## Desktop 交互式 UI 默认值

桌面设置通过布尔字段 `default_interactive_ui` 持久化，初始为 `false`，可在“设置 → 通用”修改。它用于初始化新建普通聊天，不覆盖已有聊天的偏好。聊天保存 `prefer_interactive_ui`；请求传入 `ui_preference: "interactive"` 或 `"auto"`。开启时宿主在上下文中预加载内置 OpenUI Skill 正文。此设置属于 Desktop，不改变嵌入式 SAgents 或 Server 的行为。

参见 [Desktop 使用说明](applications/DESKTOP.md)。
