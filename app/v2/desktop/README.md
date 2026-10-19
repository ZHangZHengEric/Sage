# Sage Desktop v2

[v2 code reading guide](../../../docs/en/architecture/code-reading-guide.md) · [中文阅读指南](../../../docs/zh/architecture/code-reading-guide.md)


Sage Desktop 2.0 是使用 `sagents/v2` 的独立 Flutter 客户端。旧 `app/v1/desktop` 保留为历史实现。

## 目录

```text
app/v2/desktop/
├── backend/       # 独立 FastAPI sidecar：Desktop adapter 与 v2 runtime 组合
├── lib/
│   └── src/
│       ├── api/   # HTTP/NDJSON 客户端与 sidecar 生命周期
│       ├── state/ # 多会话、cursor、暂停/恢复/steer/interaction 状态
│       └── ui/    # Flutter 三栏工作台
├── macos/
├── windows/
├── linux/
└── test/
```

## 开发运行

**环境要求：Python 3.12+。** Desktop v2 sidecar 与 `sagents.v2` 共用这一下限；
Sage 2.0 发布包统一要求 Python 3.12+；旧发布版的 Python 要求以其版本说明为准。低于 3.12 时 Flutter 不会启动 sidecar。

从仓库根目录启动：

```bash
cd app/v2/desktop
flutter pub get
flutter run -d macos
```

Flutter 默认启动随应用托管的本机 Python sidecar，并与 Yiii 一样使用 `--port 0` 让操作系统分配临时端口。Python 通过 stdout readiness envelope 把实际地址和每次启动随机生成的 capability token 交给 Flutter；注册文件通过权限为 `0600` 的随机临时文件原子发布，客户端对包括健康检查在内的每个请求发送 bearer token。端口同时只绑定 `127.0.0.1`，用户无需配置。多个 Desktop 实例复用同一 sidecar 时各自持有带心跳的客户端租约，最后一个实例退出或崩溃租约过期后 sidecar 才会优雅关闭；若宿主在首次挂接前崩溃，未认领的 sidecar 也会在租约窗口后自清理。构建升级只会请求空闲 sidecar 退出，不会中断仍有活跃客户端的旧构建。也可从命令行直接启动开发服务：

```bash
.venv/bin/python -m app.v2.desktop.backend.main
```

Agent、模型、运行组件、Memory 和完成判定都从 Desktop 自己的持久化设置读取，
不使用环境变量覆盖。Sidecar 的数据目录固定为 `~/sage`；源码调试若需独立目录，
可显式传入 `--data-root /absolute/path`。

Desktop v2 只创建自己的数据布局：`~/sage/runtime/sessions` 为每个 Session
保存一个独立、原子更新且带校验的 `state.json`，并按标准接口生成可读的
`session.json`、`events.jsonl`、`runs/<run_id>/`、`commits/` 和 `sub_sessions/`；SessionStore 的锁、幂等索引和
事务恢复数据收纳在 `~/sage/runtime/.session-store`。`~/sage/runtime/session-index.json` 是 Desktop 自己的
全局会话索引，`diagnostics/` 保存非权威模型诊断；Desktop catalog 与设置也位于
`~/sage/runtime`。`~/sage/skills` 保存导入的 Skills，
`~/sage/agent_workspace` 是共享工作区。Desktop v2 不读取或导入 Desktop v1
的数据、设置与工作区内容，模型 route、MCP 连接和 Agent Workspace 均从 v2
自己的数据根目录独立初始化。

默认 `sage.session.filesystem` 插件由扩展工厂装配。第一次使用紧凑存储格式启动
时，它只迁移当前 Desktop v2 早期版本写入的 `runtime/session-store`：从每个带
校验 journal 读取最后一次完整状态，写入并校验新的 `runtime/sessions/<id>/state.json`，
全部成功后再移除旧目录以回收重复快照占用的空间；这不是 Desktop v1 数据导入。
目录表达参考了早期文件存储的可读性，但不读取其文件或数据。子 Session 递归保存在
父目录的 `sub_sessions/<child_id>/` 中，并保留自己的 `session.json` 和 Fork Run 的
`fork-base-events.jsonl`；删除父 Session 会级联删除整个子树。内部 `locations/` 仅用于
按子 Session ID 直接定位，可随时从目录结构重建。

## OpenUI

当前源码使用 [OpenUI](https://github.com/thesysdev/openui) 的官方 `@openuidev/lang-core` 1.0.0 流式解析器，并通过 Sage 自己的 Flutter 原生 Glass 渲染器显示组件，支持浅色和深色模式。它不是 WebView 页面，也不需要调用 UI 发布工具。普通聊天可在输入框加号菜单打开“优先交互 UI”，按聊天保存；打开时宿主在首轮模型上下文中预加载完整 `sage-openui` Skill，无需模型调用加载工具。关闭时按自然需求自动选择 UI 或文字，不要求用户说 OpenUI。“设置 → 通用 → 默认开启交互式 UI”控制新聊天默认值；初始关闭，已有聊天不被修改，可从加号菜单单独覆盖，分支聊天继承原聊天的选择。交互 UI 默认承载全部内容，省略开场白和重复说明；仅在必要时保留一句结论、异常或下一步。

Assistant 在普通 Markdown 消息中输出 `openui` fenced code block。每个消息增量都会更新官方流式解析器的累计源码，部分组件树通过同一 NDJSON 连接发送给 Desktop；源码保留在消息历史中，界面隐藏协议代码并逐步显示组件。文本、工具执行、审批和暂停恢复继续使用已有路径。

当前注册 31 类原生组件：演示 `Deck`、`Slide`；布局 `Stack`、`Row`、`Card`、`Tabs`、`Tab`、`Accordion`、`Section`；展示 `Text`、`Heading`、`Table`、`Badge`、`Metric`、`Divider`、`Image`、`Progress`、`Alert`、`Chart`、`Timeline`、`Diagram`、`Computed`；输入 `Input`、`Select`、`Toggle`、`Button`、`NumberInput`、`Slider`、`DateInput`、`CheckboxGroup`、`RadioGroup`。这是 Sage 注册的声明式组件库，不支持上游全部组件、表达式、Query、Mutation、HTML 或 JavaScript。可在聊天正文查看界面，也可展开到右侧 OpenUI 面板。计算结果可级联引用并绑定到图表，随输入即时更新，无需调用模型；纯本地交互不需要提交按钮，只有任务要求将参数交回助手时才提供提交操作；只支持明确列出的运算、复利和贷款月供规则，不执行任意表达式。图片只允许匿名读取公开 HTTPS 地址，并检查重定向、解析地址和大小。表单草稿随桌面会话保存；完成的界面可以从后端持久化记录和原始消息重建。

最终校验失败时保留已生成的只读预览并标记未完成。生成过程中字段与按钮不可操作；完整源码校验通过且所属 Run 完成后，按钮才能提交。本地和后端均校验表单，提交绑定 Agent、Session、界面版本与动作，重复提交复用已接受的 Run。旧轮次界面、被替换界面和其他会话的界面不可提交。动作仅作为同一 Session 的下一轮用户输入，后续工具操作仍受 Sage 审批策略约束。Studio 和子会话中的界面目前只读。提交已登记但 Run 未确认的情况会停止并等待核对，不自动重复执行。

完成前统一由 SAgents output self-check 调度校验，Desktop 不再单独执行一套完成门禁。只有检测到最后一条 assistant 正文中的 `openui` 代码块才调用官方解析器、组件/依赖规则和本地数值探测；self-check 不调用模型。独立校验器并发执行，多代码块以有界并发检查；共享解析器的 IPC 保持串行以防响应错配。解析完成后才执行依赖树的检查，默认值和输入边界的计算结果检查不会阻塞流式事件循环。具体错误汇总后作为运行时反馈进入原模型的下一轮生成请求；同一用户回合达到三版仍未通过校验时终止修复，并受 Run 总预算约束。有效的修订稿不会仅因“没有工具调用”被当作无进展文字循环，但仍需通过正常完成判定。同轮被替换的旧稿折叠为 Process Panel 中的一行，可在侧栏查看详情，正文只保留最新稿。`Computed` 本身就是动态结果卡片，应直接放入布局；`Metric` 接收固定文本，不接收组件引用。容器允许的子组件类型由官方 `.ref` 契约生成到签名中，并在原生树校验时再次检查。

内置 [sage-openui Skill](../../skills/sage-openui/SKILL.md) 指导 Agent 选择使用场景与编写协议；运行时直接注入由真实组件库生成的语法与签名，Agent 无需先调用工具。可以直接要求 Agent：“把结果显示成对比表”或“用表单收集目的地和交通方式”。模型需支持流式输出；具体增量粒度取决于模型服务，渲染不等待整条消息完成。

源码运行需要 **Node.js 22+**。官方解析器已打包为本地 `worker.cjs`，运行时不下载脚本或依赖 CDN。重新构建解析器及其组件契约：

```bash
cd app/v2/desktop/backend/openui_runtime
npm ci --ignore-scripts --no-audit --no-fund
npm run build
npm test
```

发布流水线将 Node 可执行文件、官方解析器和第三方许可证放入安装包；2.1.0 安装包包含这些功能，2.0.0 安装包不包含。OpenUI 使用 MIT 许可证，版权及许可文本保留在 `backend/openui_runtime/THIRD_PARTY_NOTICES.txt` 中。

Current source uses the official [OpenUI](https://github.com/thesysdev/openui) streaming parser with Sage's own native Flutter Glass renderer. Assistant `openui` fenced blocks update progressively as model output arrives, with light/dark themes, cards, tables, and input forms. No UI publishing tool is required. Ordinary chats have a “Prefer interactive UI” switch in the composer plus menu, persisted per chat. When enabled, the host preloads the full sage-openui Skill into the first model context without a tool call. When disabled, presentation is chosen automatically from natural requests; users do not need to mention OpenUI. Settings → General → Interactive UI on by default controls new chats (initially off), without changing existing chat choices. The plus menu overrides a chat, and branches inherit their source chat preference. Interactive UI normally carries the whole answer without introductory or repeated prose; only a necessary conclusion, exception, or next step gets one short sentence. The current library has 31 native component types listed above, including line/bar/pie charts, metrics, tabs, accordions, timelines, diagrams, images, and richer inputs. Computed results and numeric chart bindings update locally without a model round-trip. Input fields do not require a submit button; only task-required handoffs to the assistant should add one. Native computations use a bounded allowlist of arithmetic, compound growth, and loan payment operations, not arbitrary expressions. Images use anonymous HTTPS reads with public-address validation, size limits, and redirect checks; Studio and child-session surfaces are read-only. Form submissions are validated and routed as the next user turn in the same Session, with durable duplicate protection and existing tool approvals. Source mode requires Node.js 22+; release packaging embeds Node and the parser. Previously published binaries do not include this source change.

## 打包默认配置与对话验收

安装包和源码使用同一份 `backend/package.py` 运行组件默认值，不复制开发者的
`~/sage/runtime/settings.json`、模型密钥或 Agent 私人配置。同一用户升级继续读取
已有 `~/sage`；全新安装使用代码默认值。默认本地沙箱现在使用真实工作区路径，
显式配置的虚拟路径仍然生效。旧 Run 快照未声明路径模式时按原来的虚拟路径恢复，
新 Run 会记录实际采用的路径模式。本机专用的 `command_path` 不写入安装包。

从 `app/v2/desktop` 执行 `flutter test` 验证界面、对话和流式状态。
仓库根目录已有 `.venv` 和 Python 后端依赖时，以下测试还会启动独立临时数据目录的
真实 Desktop HTTP sidecar，通过 Flutter API 客户端向 Agent 连续提问两轮，验证回复、
完成状态和第二轮持久化历史；只替换模型响应，不替换装配和会话实现：

```bash
flutter test test/unified_sidecar_test.dart
```

没有仓库 Python 虚拟环境时这项跨语言测试明确跳过，普通 Flutter 测试不受影响。
这是确定性对话验收，不代表已验证真实模型供应商或安装包中所有外部命令。

## 契约边界

- 客户端直接消费 `sage.runtime/v2` NDJSON 事件，并按 `run_sequence` 续订。
- 关闭界面或切换会话只 detach observer，不发送 Cancel。
- 暂停、恢复、取消、steer、审批和用户输入使用独立 v2 Command。
- `DesktopRunRequest` 可声明 `serial`、`snapshot_isolated` 或 `fork`；Session API
  可读取 commit proposal，Run/Proposal API 提供 propose、publish 和 reject。
- 侧栏顶部“新对话”创建 Agent Workspace 会话；项目区只显示注册 Project。Agent Workspace 是 Desktop 的默认共享工作区，不作为 Project 节点展示。
- 所有 Agent Workspace 会话和所有 Agent 共享同一个目录；切换 Agent 只改变模型、Tools、Skills 与上下文组合，不改变文件根目录。注册 Project 仍各自使用自己的项目目录。
- Desktop v2 不使用 `~/.sage` 隐藏目录。默认将共享文件放在 `~/sage/agent_workspace`，将数据库、设置和会话状态放在 `~/sage/runtime`；二者均可在 Finder 中直接看到。
- 应用启动时通过可替换的 `workspace.initializer` 插件初始化当前 Agent Workspace；默认的 Claw Mode 会按 `desktop-v1.1.8` 发布版模板非破坏性地预置 `AGENT.md`、`IDENTITY.md`、`SOUL.md`、`USER.md`、`MEMORY.md`，以及 `memory`、`data`、`projects`、`temp`、`logs` 目录，但不读取或导入任何 V1 数据。也可切换为空白工作区，未来可继续注册其他初始化插件。默认路径是 `~/sage/agent_workspace`。设置中心的“工作区”页面可以修改路径，路径字段自动保存并立即初始化目标目录；修改后 Agent Workspace 会话的新文件操作使用新目录，已绑定 Project 不受影响。
- 非项目对话始终展示当前 Agent Workspace 的完整文件树；Agent 完成工具调用或 Run 后，界面会自动刷新文件树。初始化器只补充缺失项，不覆盖用户或 Agent 已有文件。
- 共享 Agent Workspace 与注册 Project 都执行文件根目录约束。传给 sagents 的 `sandbox_agent_workspace` 始终是共享 Agent Workspace；Project Session 只通过运行变量（兼容字段 `system_context`）中的 `working_directory` 和额外允许路径告知当前项目目录。Agent 身份文件、公共运行目录、Skill 副本和沙箱运行数据继续保留在 Agent Workspace，不进入项目文件树。
- Agent Workspace 与 Project 都使用“文件阅读器 + 右侧文件树”的主从布局：初始阅读器为空，点击文件后在阅读器中打开，顶部显示路径面包屑；文件树可筛选、展开和收起。Project 文件树的数据源只包含当前项目，不混入共享 Agent Workspace。Markdown、HTML、源码和纯文本的有效选区都支持从系统菜单直接局部引用。
- 右侧区域由 `WorkspacePanelPlugin` 注册表、实例控制器和通用 Dock 承载。插件声明标题、图标、尺寸、是否单例与支持条件；Dock 负责标签、懒加载、状态保留、关闭和多实例，因此新增展示类型无需在三栏 Shell 中增加布局分支。运行时适配器可通过 `WorkspacePanelIntent` 聚焦已有实例或创建新实例。
- 内置文件区和终端都是该 Dock 的真实插件。终端插件首次激活时才创建 PTY，支持多个独立标签、键盘输入、ANSI/交互程序、窗口尺寸同步、断流续订和重启；关闭标签会关闭对应 shell，sidecar 退出时会回收全部终端。终端是用户直接操作的本机 shell，不复用 Agent 工具调用或其审批协议；当前 PTY 后端支持 macOS 与 Linux。
- 选择 Skill 只传递偏好；只有 Agent 显式调用 `load_skill` 才会把 Skill 原子复制到当前 Workspace。
- Tool 使用原生 v2 workspace、planning、`load_skill` 和 AgentPackage catalog/executor；文件和 argv 进程调用必须在资源边界重新验证签名 grant。
- 内置工具通过 v2 Tool catalog/executor 统一管理；外部工具作为独立 MCP 连接挂载，不承担内置工具注册。
- 运行组件 inventory 来自 SAgents 的真实 ExtensionRegistration；只注册元数据但不能创建实例的组件不会展示。插件选择按组件声明立即生效、在下一次装配生效或在重启后生效。
- 模型页可为每条 route 选择 `openai-chat-completions`、`openai-responses` 或 `anthropic-messages`，route 配置校验成功后保存；下一次 Run 根据这项配置创建对应 Provider。
- 启用的 MCP 连接会在 Tool catalog 和每个 Run 的组合阶段真实发现工具，并以 `mcp_<server>_<tool>` 命名；发现失败会明确报错，不会显示为已启用却静默缺席。
- Desktop 是固定本机单用户模型，HTTP adapter 始终使用 `default_user`，不接受客户端伪造身份；catalog 仍保留 `(user_id, id)` 键结构，以复用 sagents v2 的通用存储契约，但 Desktop 不对外提供多用户语义。
- Desktop 的 persistent-summary 使用当前模型 route 生成结构化摘要，原始 Session Event 不被改写；摘要保存在所选 SessionStore 的 derived namespace，不存在第二个 summary 数据库。
- 所有设置使用字段级自动保存；选择和开关即时提交，文本字段防抖提交，不提供全局保存按钮。模型密钥保存在权限收紧的 Desktop catalog 文件中，不进入 manifest 或组件 inventory。

## 验证

```bash
cd app/v2/desktop
flutter analyze
flutter test

cd ../../..
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/app/v2/desktop -q
```

## 品牌图标

Desktop v2 复制并沿用旧 Desktop 的 Sage 标识，独立源文件是 `assets/brand/sage_logo.png`。修改后运行 `python scripts/generate_icons.py`，同步生成 macOS AppIcon 与 Windows ICO；旧 Desktop 的图标资源不会被修改。macOS 输出使用与 Yiii 相同的原生图标外形比例，平台遮罩独立保存在 `assets/brand/macos_icon_mask.png`；黑色主体约占画布 89%，四角透明，S 标识位于中央安全区。macOS 版本的 S 使用肉眼不可见的冷白色差，避免 macOS 26 把纯黑白扁平图标误判为单色前景并添加浅色系统底板。

## 设置写入协议

sidecar revision 6 新增 `PATCH /api/v2/settings`，请求体只包含需要更新的顶层字段；嵌套对象作为该字段整体替换。Flutter 串行提交变更字段，后端在同一服务实例内将读取、合并、校验与落盘串行化，项目增删及组件选择共享事务锁。`PUT /api/v2/settings` 保留完整替换语义。此机制不提供多个独立后端进程之间的 CAS。

关闭设置页会等待保存并提交剩余防抖输入；验证或保存失败时保留页面并显示错误。Agent 乐观编辑以服务端确认快照回滚，并防止旧读取覆盖新修改。

Desktop V2 正常运行路径的主模型、成员与辅助模型共用宿主模型调用额度，默认 8；可通过 `DesktopV2Service(max_concurrent_model_calls=...)` 配置。此额度不代表工具进程、内存或全局队列预算。

模型调用等待队列默认最多 128 项、最长等待 60 秒，宿主可用 `max_waiting_model_calls` 与 `model_queue_timeout_seconds` 配置。排队满或超时保留具体错误码；直接 API 返回 HTTP 429，运行中的 Agent 通过错误恢复交互暂停，名额恢复后可重试同一任务。等待超时不会作为模型执行时限。

## Agent 复制与创建配置（sidecar revision 7）

`POST /api/v2/agents` 支持 `source_agent_id` 和可选 `settings`（现有完整 AgentSettingsPatch）。复制只读取当前用户可见的 Agent，创建独立 ID，保留配置后应用覆盖字段；校验完成才保存。创建、更新与删除在单服务实例内串行执行，避免读取旧配置后互相覆盖。此锁不提供多进程 CAS。

Agent 编辑页的“复制”会先提交待保存内容，再打开副本的编辑器。运行时 max_loop_count 与接口统一支持 1–10000，不再静默截为 200。本页面仍是普通 Agent 配置编辑，尚非完整 package/版本/Flow Studio；源码插件加载由 SAgents 宿主显式开启和授权。

## Studio 消息投递

所有公开消息对用户和 Studio 成员可见；`@成员名`、`@成员ID` 与显式收件人用于投递，不控制可见性。消息保留完整原文和提及位置，多人各自处理分配给自己的内容。代码、引用、邮件地址及转义的 `\@` 不触发投递；重名时使用稳定成员 ID。系统上下文包含成员名单和 `user`（用户）。

`studio_send_message` 在消息和收件队列持久化后返回，不等待对方执行或回复。被 @ 的 Agent 自动唤醒，忙碌或等待审批的成员按顺序排队；@用户只发布消息。接收者可以不回复，也可以通过该工具公开回复而不 @ 回去。Agent 发起的消息所触发的 Run，其普通最终输出不会自动发布；无收件人的公开消息不触发新 Run。用户未指定成员时仍由协调成员接收。

投递记录和 Run 绑定用于重启恢复与去重；启动回执不明时先查询已接受的 Run，不盲目重放。用户触发的最终结果由后端补入公开历史，前端不重复上传。自动投递最多同时占用 8 个执行任务，每个用户轮次最多 64 次自动投递、最多 8 层转发。本机制用于单宿主，不提供多宿主调度保证。

## 2.0 发布包

安装包由 `.github/workflows/release-v2.yml` 在 GitHub Actions 构建，包含 Flutter 客户端、独立 CPython、v2 后端和内置 skills；安装后无需源码目录或系统 Python。macOS 提供 arm64 / x86_64 DMG，Windows 提供 x86_64 安装程序，Linux 提供 arm64 / x86_64 DEB 与便携 tar.gz。Linux 仍需要 GTK 等系统动态库与 bubblewrap。

每个平台在发布前将整个应用移动到另一个包含空格的路径，从仓库外启动内置 Python，验证 v2 导入、skills、带认证的 health 与客户端 lease 关闭。全部平台成功后才创建 `v2.1.0` tag 和 GitHub Release。手动验证运行不发布；选择 `publish` 才发布。

macOS 包使用 ad-hoc 签名，未使用 Apple Developer ID 签名或公证；Windows 包未做代码签名。旧 Tauri 发布流水线已移出 GitHub Actions，不再构建 v1 应用；历史 updater feed 不向 v1 自动推送 Flutter v2。

## RSI 与 Agent 版本

Agent 配置中的 RSI 按钮在设置框架内打开优化页面，保留侧栏和统一的字段布局；“版本历史”是 Agent 配置层级的独立入口，展示人工保存和确认应用的配置版本，无需启动 RSI。RSI 页面只展示运行历史与各轮候选，未应用的候选不会混入 Agent 版本历史。用户可设置 1–100 轮、内部 Agent 模型和优化范围（指令、Skill、原生工具启用列表、步数预算），也可导入符合 OptimizationSuite 的 JSON 测试集；未提供时由测试设计 Agent 生成。独立最终测试集在基线前封存；测试集与授权目标的一致性由独立 Session 的审查 Agent 先行检查。有阻断问题时不执行目标 Agent 或调优 Agent，页面显示问题与修正建议；覆盖不足等建议保留供查看。候选修改另由独立 Session 的语义审查 Agent 检查。

运行设置可收起，优化范围使用 Glass 控件并适配深浅色。RSI 在 sidecar 的后台任务中执行，页面增量读取过程；离开页面或关闭最后一个窗口不会终止正在执行的 RSI。重新打开页面可读取历次任务、每轮版本、测试回答、评测和审查结果。sidecar 退出/崩溃时任务保留为 interrupted，不会自动重放未知结果的模型或工具调用。

记录保存在 Desktop 数据目录的 runtime/rsi.sqlite3 与 runtime/rsi/<run-id>/。普通配置保存、Skill 删除和 shell 授权变更也保存版本；进入 RSI 时为已有 Agent 建立快照。各版本包含当时的配置、完整文本 package 和独立归档的二进制 Skill 资源。激活 Skill 使用按内容寻址的 Agent 局部覆盖目录，避免修改其他 Agent 的共享 Skill。

版本快照的工具与 Skill 启用列表遵循正常运行的名称过滤和默认选择规则；旧配置中的内部操作名不作为可调用工具写入 package，原始配置仍完整保存在版本记录中。未设置工具列表与显式空列表分别保留默认选择和禁用工具的语义，外部工具仍需 RSI 测试绑定。

人工保存版本在列表中标为“配置保存”，详情可展开查看名称、描述、模型、运行变量和权限，另有指令、工具、Skills、预算及文件内容。配置从 A 改为 B 再改回 A 会保留三个历史节点；重复读取不会新增节点。功能启用前尚未归档的旧编辑无法恢复，只能从现有配置建立初始快照。

优化完成不修改当前 Agent。用户点击“使用此版本”，再确认替换，才调用独立的应用接口；接口要求 confirmed=true 和当前配置指纹。确认期间配置改变则拒绝覆盖。语义审查拒绝的候选保留用于查看，不能激活；未完成评测的候选不能激活。页面标出各版本是否接受了独立最终测试，用户可明确选择其他完成评测的迭代。完整报告与版本可分别导出。

第一版支持 simple Agent 和原生工具；原有运行变量被固定带入测试，每次测试使用新 Application/Session 和临时工作区。临时工作区不包含真实项目文件，进程执行禁用，网络使用默认沙箱限制；Shell 尚需测试绑定，MCP 与非 simple Agent 在启动前拒绝。工具范围可以从原生工具集合增减启用项，预算范围目前只开放 max_steps。依赖 Desktop 单 sidecar 进程，不提供分布式任务接管或自动断点续跑。

`integration_test/desktop_rsi_live_test.dart` 是显式启用的 macOS 原生验证。需先准备真实模型 provider、独立测试 Agent 和 `setup.json`/`suite.json`，然后运行 `flutter test integration_test/desktop_rsi_live_test.dart -d macos --dart-define=RSI_LIVE_MODEL=true --dart-define=RSI_LIVE_ARTIFACT_DIR=<绝对目录>`。它调用真实后台与模型，通过原生前端检查人工保存、三轮进度、离开/重连、确认/取消、版本恢复和后端重启后的历史；仅系统文件选择器使用固定测试文件替代。默认不运行，避免普通测试产生模型费用。


### Streaming presentations / 流式演示文稿

`Deck(title, [slides])` contains `Slide(title, [blocks], layout, accent)`. The official parser updates native 16:9 pages incrementally; layouts are `cover`, `content`, `split`, with blue/rose/emerald/amber accents and light/dark palettes. Navigation, thumbnails, fullscreen presentation and editable PPTX export are native controls. Export is enabled for a validated persisted Deck and uses its exact revision, with no model/tool call. PPTX text, tables and charts are editable Office objects, not screenshots. Preview and export share generated canvas geometry, but Flutter Glass material and Office chart typography may differ.

幻灯片支持封面、内容、双栏三种固定版式，内容为文字、指标、表格、折线/柱状/环形图。当前不支持 PPTX 导入、任意自由排版、图片/视频、动画或逐字流式写入 PPTX 二进制。生成过程中更新的是幻灯片数据；完整验证后导出文件。旧 `pptx` 制作 Skill 已移除，模型通过 `sage-openui` 和系统中的组件签名直接输出 OpenUI 代码。超过版式限制应拆页，不能裁剪内容。此能力是 Sage 自己实现的渲染与导出，并非 OpenUI Cloud Reports API。

本地完成进度支持：`Computed` 的 `count` 对勾选项显式计数，`ratioPercent` 计算完成数 ÷ 总数 × 100；`Progress` 可绑定数值字段或计算结果。进度、指标和图表在输入变化时本地更新，无需提交。`sum` 不会隐式转换勾选数组，既有 `percent` 仍表示基数 × 百分比 ÷ 100。

## 标准运行控制

审批、提交、取消、暂停和恢复使用标准 App/Runtime。受理前失败返回结构化 HTTP 错误，不创建占位 Run；候选结果通过 entrypoint 发布以保留原 Agent 版本和记忆处理。接口与生命周期边界见[控制接口核对](../../../docs/zh/architecture/sagents-v2-host-controls.md)。
