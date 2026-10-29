---
layout: default
title: 内置模型提供方验收标准
nav_order: 18
lang: zh
ref: v2-model-provider-acceptance
permalink: /zh/model-provider-acceptance/
---

{% include lang_switcher.html %}

# 内置模型提供方验收标准

本文是后续内置模型提供方预设及插件的验收标准。实现前先在 issue 中讨论是否纳入。提供方预设、新通信协议适配器、可选外部示例的范围不同，必须明确本次范围及支持的宿主。

## 证据边界与术语

下述当前实现来自对 `5e66cbc8cc931155802c84e29d1cfd32d68a2c30`（2026-10-29）的源码追踪，不是 Desktop 交互测试、在线服务认证，也不表示所有验收要求已有自动强制执行。请按 PR 基线重新检查路径。“验收要求”描述未来 PR 必须提供的证据；本文不会悄然实现现存缺口。

| 标识 | 含义 |
| --- | --- |
| 协议 / 提供方别名 | `ModelRoute.provider` 选择通信协议或支持的别名，例如 `orcarouter` 解析为 `openai-chat-completions`。 |
| 插件 ID | 稳定的实现身份，例如 `sage.model.openai-chat-completions`，不同于商业提供方名称。 |
| 上游模型 | `ModelRoute.model` 是服务端点接受的模型标识，不是目录记录 ID。 |
| 宿主记录 / 绑定 | Server 模型 `id` 与 Desktop 提供方记录 `id` 标识已保存配置；Agent 主模型/快速模型绑定选择这些记录。 |
| 凭据引用 | SDK 路由引用凭据声明，不内嵌密钥；宿主将存储的密钥解析为凭据材料。 |

## 当前实现：SDK 与请求发送

源码位置（相对仓库根目录）：

- `sagents/v2/package/manifest/models.py`：`ModelRoute`、请求默认参数、限制和能力声明。
- `sagents/v2/model/protocols.py`：描述符、别名解析、默认端点及 `create_registered_model_provider`。
- `sagents/v2/model/registry.py` 与 `registrations.py`：`model.provider` 注册表与实际插件注册；元数据本身不构成实现。
- `sagents/v2/model/plugins/`：OpenAI Chat Completions、Responses、Anthropic Messages 与 Gemini GenerateContent 适配器。兼容网关预设应复用合适的适配器，而不是复制通信实现。
- `sagents/v2/model/capability_contracts.py` 与 `capability_probe.py`：能力证据和探测契约；`protocols.py` 检查能力配置的协议、插件归属与版本。

在 Chat Completions 路径中，`create_registered_model_provider` 用路由模型、端点、请求选项和解析后的凭据构建适配器。`plugins/openai_compatible.py` 将配置的密钥和 base URL 传给 `AsyncOpenAI`，以流式方式调用 `chat.completions.create`，规范化文本与工具调用分片、关闭上游流、分类错误并拒绝不完整流。有限的协议参数协商不意味着可以任意重试已输出部分内容的请求或切换提供方。协议名称和声明能力不能证明某个网关/模型支持全部功能。

## 当前实现：Server

1. `app/v2/server/web/src/views/Models.vue` 负责表单及默认端点映射；`model-presentation.js` 负责协议选项与提供方展示；`api.js` 请求 `/api/models`。这里的品牌选项与 Desktop 独立。
2. `app/v2/server/routers/models.py` 提供列表、POST upsert、详情、删除和 `/probe`；`routers/schemas/catalog.py` 定义请求/响应结构。`catalog/service.py`、`records.py::apply_upsert` 和 `repository.py` 校验并持久化用户模型记录。在 `ModelRecord.route()` 规范化协议前先解析别名默认端点。
3. 新记录需要模型与密钥；更新时空密钥保留已有值。省略或为空的端点使用协议/别名默认值，显式提供的自定义端点保留。网页切换协议时会替换空端点或已知默认端点，不任意覆盖自定义端点。应测试这些语义，不能假定 POST upsert 等同于 PATCH。
4. `catalog/model_config.py::app_models` 将记录发布为 SDK 模型绑定及宿主凭据引用，并提供默认绑定；`catalog/packages.py` 映射 Agent 主模型/快速模型。`runtime/models.py` 构建提供方，`runtime/model_pool.py` 管理客户端复用与清理。表单保存成功不证明 Agent 选中了该记录或发送了预期上游请求。

## 当前实现：Desktop

1. `app/v2/desktop/lib/src/ui/settings_screen.dart` 实现模型设置。协议选择器包含四种协议，而非 Server 的商业别名列表。模型记录包含显示名称、协议、base URL、上游模型、密钥及限制。增加 SDK 别名或 Server 选项**不会**自动增加 Desktop 品牌预设。
2. `lib/src/state/workspace_controller.dart` 与 `lib/src/api/v2_api.dart` 向 `/api/v2/model-providers` 发出列表、创建、PATCH、删除及能力验证请求；`backend/app.py`、`schemas.py`、`catalog_service.py` 处理请求。Desktop 请求结构与 `catalog.py::DesktopModelProviderRecord` 都将协议限制为四种值。
3. 表单仅在输入非空替换密钥时发送 `api_keys`。后端最多接受一把密钥；PATCH 省略该字段保留原值，显式空列表则清除。配置变化必须先完成能力检测，界面保存路径才继续；仅改显示名称可不检测。这项 UI 门槛不能证明所有直接 API 客户端均已探测。
4. `backend/catalog.py::JsonDesktopCatalogStore` 将记录保存到 runtime root 下的 `desktop-catalog.json`，使用原子替换和 0600 权限。重载记录生成模型列表；模型设置可指定默认项；Agent 设置以记录 ID（`llm_provider_id`、`fast_llm_provider_id`）选择主模型/快速模型，而非使用上游模型名称。
5. `backend/run_composition.py::_provider` 先解析 Agent 的记录，必要时回退到默认/第一条记录，并拒绝缺少可用密钥或端点的配置。`backend/model_providers.py::DesktopModelProviders.route/get` 将记录转换为 SDK 路由和凭据，保留请求设置/能力配置，并按配置及密钥敏感的缓存键复用提供方。路由最终到达上述协议适配器。快速模型在 `run_composition.py` 中有独立绑定路径。

**验收要求：** 声称内置 Desktop 选项的 PR 必须证明发现、选择、保存、重启/重载、Agent 绑定及最终请求。如果仅支持手动配置，要明确说明并提供准确的协议/base URL/模型操作步骤。新品牌预设可以映射到现有协议，不得将不受支持的别名直接写入 Desktop 协议字段。Server/Desktop 有意不同的地方必须明确范围决定与缺口。

## 凭据、兼容性与失败边界

当前存储不构成加密保证。Desktop 将密钥以字符串保存到受权限保护的 JSON 目录。Server 的 `ModelRecord` 使用 `SecretStr`，但 `catalog/records.py::catalog_payload` 会取出原始密钥，通过 `catalog/repository.py` 持久化；Python 值脱敏不等于静态加密。部署存储保护仍属于宿主责任。

普通 Server 列表/upsert 响应省略密钥；获授权的详情读取会返回密钥，并设置 `Cache-Control: no-store`。Desktop 列表只提供 `api_key_configured`，另有标记 `no-store` 的密钥显示端点。不能把任一 API 描述为严格只写。改变此边界时必须检查授权、租户/用户隔离以及实际存储后端。

验收要求：

- 不提交真实密钥，不把密钥放入模型 ID 或 URL，不在诊断、测试数据、截图及 PR 日志中泄露。保留列表脱敏与显式显示授权；准确描述存储，重设计需要单独安全审查。
- 保留自定义 base URL、密钥保留/轮换及默认选择行为，不悄然将现有用户迁移到新提供方。测试冷/热客户端，以及端点、密钥、模型、能力配置变化时的失效行为。
- 为指定端点和代表性模型提供协议兼容证据。测试文本流、工具调用参数/结果，以及声称支持时的多个或分片调用、取消、用量及完成标记。推理、结构化输出、图像、token 限制须分别验证，不能从“OpenAI-compatible”推定。
- 测试无效密钥（401/403）、配额/限流、错误模型/端点、超时、畸形响应、中断流及不支持的参数。错误应可操作且脱敏，重试有界，取消/清理正确。不得静默替换请求能力，或将部分交付的工具调用重试成全新的成功运行。
- 在线能力检查可能发送数据并产生费用。报告脱敏后的探测范围、端点/模型、日期、能力配置版本及限制。Mock 成功不证明在线兼容；未经许可不得使用他人凭据执行在线测试。

## 中转提供方纳入原则

中转提供方申请作为内置模型选项或插件时，必须**在其网站及其 Agent 中推荐 Sage Harness**。要求提交两处推荐的公开证据，并披露提交人与提供方的关系。如“通过其 Agent”含义不明确，应与维护者澄清拟提供的证据；本文不自创展示位置或技术实现要求。

这是考虑纳入的必要条件，不是充分批准。兼容性、安全性、用户价值及持续维护仍需分别判断。不承诺接受、默认使用、背书、付款或独家合作，不要求 star。不自动适用于无关社区资源、评测报告或搜索服务提交；现有资源提交规则保持不变。对已合入集成进行追溯变更需要另行决定范围。

## PR 证据与维护者清单

参考[测试指南](TESTING.md)、[配置](CONFIGURATION.md)及[贡献指南](https://github.com/ZHangZHengEric/Sage/blob/main/CONTRIBUTING.md)。这是审查要求，不是新增 CI 门槛或自动批准机制。

- [ ] 说明预设或新适配器/插件、支持的 SDK/Server/Desktop 范围、base/head SHA、关联关系及维护负责人。适用的中转服务须附两处推荐证据。
- [ ] 追踪实际文件：界面/选项、API/结构、持久化、Agent 绑定、注册表/适配器、发出请求。解释有意不支持的界面，审阅完整 diff，而不只看新别名。
- [ ] 验证端点默认值与覆盖、上游模型与记录 ID、密钥处理、已有记录迁移行为、默认项保留及用户隔离。
- [ ] 提供聚焦回归结果、命令/环境及失败/跳过项。现有起点：`tests/sagents/v2/test_builtin_model_protocols_matrix.py`、`test_openai_compatible_model_matrix.py`、`test_model_plugin_capability_contract_matrix.py`；`tests/app/v2/server/test_models.py`、`test_model_pool.py`；`app/v2/server/web/tests/model-presentation.test.js`；`tests/app/v2/desktop/test_model_probe.py`；`app/v2/desktop/test/v2_api_test.dart` 与 `widget_test.dart`。选择受影响用例，不为填清单重跑无关已完成 CI。
- [ ] 使用合适的 widget/后端测试，以及条件允许时脱敏的手动证据，展示 Desktop 可见性及保存/重载/选择，包括失败、重试、取消。分别标记源码阅读、Mock 测试、交互 UI 验证和在线提供方测试；缺少证据仍是审查缺口。
- [ ] 展示代表性的流式文本与工具往返，断言实际请求中的模型/端点/选项，覆盖不支持的能力及安全失败。如果现有覆盖不足，增加适配器专用测试。
- [ ] 更新中英文用户说明与贡献者引用，验证文档链接，记录剩余缺口与跟进负责人；不填充 README 活动记录。
- [ ] 最终动作前复核当前 head、已有回复与并行评审。推荐证据不能替代审查；批准和合并仍由维护者明确决定。

## 检查版本中的已知缺口

Desktop 与 Server 没有共享商业预设列表；除非后续 PR 实现预设，否则须手动配置协议、端点和模型。上述存储路径不能证明静态加密。能力声明和 Mock 测试不能认证所有上游模型。本文不改变这些运行行为，也不记录任何 Desktop 交互或在线提供方测试结果。
