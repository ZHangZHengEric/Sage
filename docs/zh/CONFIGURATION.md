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
| 嵌入式 SAgents | `SageManifest`：YAML 字符串、校验后的 Python 字典或 `sage.yaml`。 |
| Desktop | 应用持久化设置和 catalog，在界面配置模型与 Agent。 |
| Server | `SAGE_SERVER_*` 环境变量，加上各用户的模型、Agent、Skill 与 MCP catalog。 |

## 加载 manifest

```python
from sagents.v2.package.manifest import SageManifest, SageManifestLoader

manifest = SageManifestLoader().loads(yaml_text)
# 也可以：manifest = SageManifest.model_validate(config_dict)
# 然后：application = await builder.build(runtime=manifest.runtime, models=model_config)
```

`loads()` 校验 YAML 并拒绝重复键。`load("path/to/sage.yaml")` 还会解析包目录内的指令文件。直接给 `build()` 传普通字符串会走文件加载。内存配置使用内联指令。

`credentials` 声明密钥解析来源；`models` 引用凭据，不携带密钥明文。`agents` 选择指令和模型路由，`entrypoint` 指定入口 Agent。

## OrcaRouter 模型

`orcarouter` 是可选的 provider 预设，复用现有 OpenAI-compatible Chat Completions
实现。在 Server 模型表单中选择 `orcarouter`，填写模型 ID 和 API Key。
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

## 模型流空闲超时

在 `openai-chat-completions`、`openai-responses`、`anthropic-messages` 或
`gemini-generate-content` 路由中，将
`models.<binding>.request.extra.stream_idle_timeout_seconds` 设为正数（秒）。
省略或设为 `null` 时关闭空闲检查。Python 调用方也可以直接在对应适配器的
配置对象上设置同名字段。

响应流建立后，Sage 只累计等待上游事件的时间，处理和转发事件的时间不计入。
新增正文、推理和工具调用分片会重置预算，心跳、空增量和仅含用量的帧不会。
空闲超时使用 `model.stream_idle_timeout`，
并进入现有重试预算。诊断字段 `stream_idle_phase` 在首次有效分片前为
`first_chunk`，已有进展后为 `mid_stream`。连接和 Run 时限仍然生效。

## Gemini GenerateContent 请求体大小

原生 `gemini-generate-content` 路由默认将序列化请求体限制为 20,000,000 字节。
可通过 `models.<binding>.request.extra.max_request_bytes` 按端点调整。
适配器先应用 `max_inline_videos` 限制，再按从早到晚的顺序把内联视频和音频替换成
文字引用，直到请求体低于或等于上限。`analyze_audio`/`analyze_video` 单个文件最大
12 MiB，保证默认上限下单个附件能完整发送。处理后仍超限时，Sage 会在发送前返回
`model.request_too_large`。文字、工具和所有媒体都计入请求体预算。

## 音频与视频输入

`analyze_audio` 和 `analyze_video` 只对能接收对应输入的模型可见。可在
`models.<binding>.capabilities` 中用 `audio_input`、`video_input` 显式声明：

- `gemini-generate-content`：省略时跟随 `multimodal`。
- `openai-chat-completions`：省略时为 `false`。后端模型支持时（如 Qwen-Omni、
  部分 OpenRouter 模型）设为 `true`，音频以 `input_audio`、视频以 `video_url` 发送。
- `openai-responses`、`anthropic-messages`：始终不支持，声明会被忽略。

切换到不支持的模型后，历史中的音视频会替换为一行省略说明，不会发送原始数据，
也不会因此导致请求失败。

### Chat Completions 视频 URL

对于通过 `image_url.url` 读取 MP4 的兼容网关（例如 85），在
`models.<binding>` 中配置：

```yaml
capabilities:
  video_input: true
request:
  extra:
    video_url_format: image_url
    video_storage:
      bucket: private-video-bucket
      region: ap-southeast-1
      prefix: sage/model-video
      url_ttl_seconds: 900
```

已有可直读的 HTTPS 视频 URL 时，只需设置 `video_url_format`。工作区视频使用对象存储
时需安装 `sage[s3-video]`，并通过 AWS SDK 的凭据链提供所选前缀的
`s3:PutObject` 和 `s3:GetObject` 权限。S3 兼容存储可设置 HTTPS `endpoint_url`。
Sage 将文件存入私有桶，在每轮请求时签发临时读取 URL。会话保留原始附件引用，所选桶可
通过生命周期规则清理副本。工作区工具的单文件上限仍为 12 MiB。

Chat Completions 同样先按 `max_inline_videos`（默认 10）把较早的视频替换为文字引用，
再在请求体超过 `max_request_bytes` 时，按从早到晚的顺序把内联音频和视频替换为文字
引用。网关转发到 Gemini 时，建议把 `max_request_bytes` 设为 `20000000`。
`input_audio` 只接受 base64 数据，远程音频 URL 会替换为一行省略说明。

### Gemini 视频存储

`gemini-generate-content` 路由使用相同的 `request.extra.video_storage` 配置，
无需设置 `video_url_format`。Sage 上传每个内联视频，并以 `fileData.fileUri`
发送签名 URL。已上传的视频不计入 `max_request_bytes`。已有的远程视频 URL 原样
发送。诊断记录和错误信息会隐去 URL 签名。

两种协议都只在当前轮（最近一次模型回复之后）的视频上传失败时返回
`model.video_storage_failed`。更早的视频上传失败时替换为一行省略说明，请求照常发送，
并记录诊断事件 `video_storage_omitted`。

## 通过 OpenAI 兼容接口调用 Gemini 工具

Gemini 模型使用 `openai-chat-completions` 时，Sage 会将文档定义的
`extra_content.google.thought_signature` 保留在对应的工具调用上，覆盖流式响应、
会话历史以及 Session 保存和恢复，无需额外配置。签名按不透明字符串原样保留，
不保存其他扩展字段。格式不合法的签名状态会被拒绝，并沿用现有 provider-state
的 8 MiB 上限。此处理针对工具调用签名；原生 `gemini-generate-content` 路由
使用自身的续接状态处理。
历史记忆清理会保留带有 provider 续接状态的完整工具调用组及其结果，避免删除调用后
留下失配的签名。不带 provider 状态的普通记忆调用仍按原逻辑清理。

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
