# Sage Desktop v2

Sage Desktop v2 是验证 `sagents/v2` 的独立 Flutter 客户端，不替换、复用或修改旧 `app/desktop` 的前端代码。

## 目录

```text
app/desktop_v2/
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

从仓库根目录启动：

```bash
cd app/desktop_v2
flutter pub get
flutter run -d macos
```

Flutter 默认启动随应用托管的本机 Python sidecar，并与 Yiii 一样使用 `--port 0` 让操作系统分配临时端口。Python 通过 stdout readiness envelope 把实际地址交给 Flutter；端口只绑定 `127.0.0.1`，用户无需配置。也可从命令行直接启动开发服务：

```bash
.venv/bin/python -m app.desktop_v2.backend.main
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
- Desktop catalog 以 `(user_id, id)` 作为 Agent/模型身份边界；不同用户复用 `sage` 或 `model_main` 不会互相覆盖。
- Desktop 的 persistent-summary 使用当前模型 route 生成结构化摘要，原始 Session Event 不被改写；摘要保存在所选 SessionStore 的 derived namespace，不存在第二个 summary 数据库。
- 所有设置使用字段级自动保存；选择和开关即时提交，文本字段防抖提交，不提供全局保存按钮。模型密钥保存在权限收紧的 Desktop catalog 文件中，不进入 manifest 或组件 inventory。

## 验证

```bash
cd app/desktop_v2
flutter analyze
flutter test

cd ../..
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/app/desktop_v2 -q
```

## 品牌图标

Desktop v2 复制并沿用旧 Desktop 的 Sage 标识，独立源文件是 `assets/brand/sage_logo.png`。修改后运行 `python scripts/generate_icons.py`，同步生成 macOS AppIcon 与 Windows ICO；旧 Desktop 的图标资源不会被修改。macOS 输出使用与 Yiii 相同的原生图标外形比例，平台遮罩独立保存在 `assets/brand/macos_icon_mask.png`；黑色主体约占画布 89%，四角透明，S 标识位于中央安全区。macOS 版本的 S 使用肉眼不可见的冷白色差，避免 macOS 26 把纯黑白扁平图标误判为单色前景并添加浅色系统底板。
