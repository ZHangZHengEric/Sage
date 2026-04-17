
2026-04-17 修复 slash 触发选中后 `/` 未删除：点击下拉项时 contenteditable 失焦导致 Selection.modify 失效。下拉项加 `@mousedown.prevent` 阻止失焦；ChipInput 同时记录 lastRange，`deleteCharsBeforeCaret` 在调用时主动 focus + 必要时恢复 range，键鼠两条路径都能正确删掉触发的 `/keyword`。

2026-04-17 输入框任意位置 `/` 触发技能选择 + 多技能支持：ChipInput 增加基于光标的 `getSkillQuery` / `deleteCharsBeforeCaret`（用 Selection.modify 跨 chip 安全删除），并在 input/keyup/click 抛 `caret-update`。MessageInput 用 `currentSkills` 数组承载多个技能 chip，选中后自动删除光标前 `/keyword`，提交时把所有 `<skill>name</skill>` 串联到消息头部；解析支持多个连续 `<skill>` 标签，Backspace 在空输入时逐个回删。Web 与 Desktop 同步。

2026-04-17 修复 ChipInput 附件 chip 看起来"裸字"问题：chip 节点是 JS createElement 动态生成的，不带 Vue scoped 的 data-v 属性，导致 `<style scoped>` 里的 `.chip-input__chip` 选择器全部失效。把 chip 相关样式拆到非 scoped `<style>` 块，同时把外观调成更明显的卡片：圆角矩形 + 主题色细描边 + 半透明底 + 轻投影 + hover 反馈。Web 与 Desktop 同步。

2026-04-17 桌面端图片走 HTTP 静态化与 server 端统一：sidecar 新增 `GET /api/oss/file/{agent_id}/{filename}`，`POST /api/oss/upload` 改为返回 `http://127.0.0.1:<port>/api/oss/file/...` URL；agent_base `_process_multimodal_content` 把 localhost 的 sage 文件 URL 反解回 `~/.sage/agents/<agent_id>/upload_files/<filename>` 再走"本地图片→base64"，避免远程 LLM 拉不到 localhost。前端 desktop MessageRenderer 删除 convertFileSrc/isLocalPath 分支，与 server-web 共用同一份 `<img src="http(s)://...">` 渲染路径。

2026-04-17 修复 recurring task 调度：原逻辑用 `next_run`（未来时间）做 base 并把未到点的 pending 实例误判为 missed_instances 取消，导致同一任务每轮都被 cancel→重派生（日志一直刷）。改为"到点才派生"：用 `croniter.get_prev` 取最近触发点，与 `last_executed_at` 比较；首次见到只初始化游标。同时把 DAO/调度器中高频 INFO 日志降级为 DEBUG。

2026-04-17 修复桌面端本地图片预览破图：resolveFilePath/imageUrl 不再剥掉绝对路径开头的 `/`，convertFileSrc 编码 %2F 后 Tauri asset handler 才能正确还原文件路径；同时将 data:/blob: 一并视为已可加载直接返回。MessageRenderer 与 ImageRenderer 同步。

2026-04-17 桌面端气泡里 image_url part 不再走"本地路径=文件链接"分支，统一通过 Tauri convertFileSrc 转成 asset:// 直接渲染真实图片缩略图（最大 220/280px 内自适应）。

2026-04-17 多模态提交内容补充图片路径：图片提交时同时写入 `![name](url)` 文本引用和 `image_url` 视觉 part，让 LLM 既能"看图"又能拿到资源 URL；前端渲染层对紧邻 `image_url` 的同 url markdown 引用自动剥离，气泡内不重复出现大图。

2026-04-17 用户消息气泡融合：新格式 multimodal 消息改为单个气泡内自然交错文本与图片缩略图（不再切成多段独立气泡），去除冗余的文件名标签，图片直接以 220/280px 内的缩略图显示并支持点击放大。Web 与 Desktop 同步。

2026-04-17 对话输入框附件 chip 化：新增 ChipInput（contenteditable）替换原 Textarea，光标位置插入图片/文件时渲染为不可分割的圆角胶囊（图标+文件名），Backspace 整体删除即同步移除附件。提交仍按位置切片成有序 multimodal content。Web 与 Desktop 同步。

2026-04-17 对话输入框/气泡：附件按光标位置以 markdown 占位符插入，提交时按位置切片成有序 multimodal content；气泡按顺序渲染真实图片+文件名标签，文本与图片可交错展示。手动删除占位符同步移除附件；老消息保持原有"文本+图片网格"渲染。Web 与 Desktop 同步。

2026-04-17 Agent 编辑页「可用技能」：增加全部/系统/我的筛选（依据 source_dimension/dimension），列表行展示来源徽标；修复复选框 pointer-events-none 导致点击无效，改为 label 包裹正文并与复选框联动。Web 与 Desktop 的 AgentEdit 同步。

2026-04-17 桌面端技能列表：前端按后端 `dimension` 字段判定我的/系统（不再依赖前端拿不到的 userid），分类正确；Tab 顺序调整为「我的技能 → 系统技能 → 全部技能」。
2026-04-17 桌面端技能：用户 ZIP 导入写入 `~/.sage/users/<用户>/skills`，`list_skills` 返回 `user_id`/`dimension`；`SkillManager` 注册新技能时在所有 skill 目录中解析路径，与「我的技能/系统技能」筛选及同步到 Agent 逻辑一致。
2026-04-17 修复 desktop 模式下 populate_request_from_agent_config 用 agent 的 systemContext 直接覆盖 request.system_context，导致子 session 的 parent_session_id 等字段丢失；改为统一 merge（request 值优先）。同时 Fibre 子 session 冲突检查改为按 parent_session_id 判断，允许同一父 session 复用已结束的子 session_id；_delegate_task_via_backend 对流式 tool_calls.arguments 的空串/不完整 JSON 跳过而不再报 ERROR。
2026-04-16 修复 Fibre 多层后端委派：parent_session_id 自动从 system_context 提取；子 session 不再继承父的 custom_sub_agents，改由后端 auto_all 自动配置；server 端 populate_request 补齐 auto_all 扩展逻辑；create_agent 处理"已存在"返回视为成功。
2026-04-16 重构 SessionManager：用 SQLite 中央注册表（sessions_index.sqlite）替换内存字典 _all_session_paths 和启动全量扫描，首次启动自动迁移；Fibre delegate_tasks 增加手动 session_id 全局冲突校验。
2026-04-16 修复 SeatbeltIsolation/BwrapIsolation 同步 subprocess.run 阻塞 asyncio 事件循环导致服务无响应的严重 Bug，改为 async def + asyncio.to_thread 异步执行，与 SubprocessIsolation 保持一致。
2026-04-16 移除 `sagents/agent/agent_base.py` 中未使用的 `User` 导入，避免 sagents 依赖 `common.models`。
2026-04-16 delete_agent 在删除 DB 记录后调用 delete_agent_workspace_on_host，清理宿主机上该 Agent 工作区（desktop/server）；与本地/直通/远程 bind 挂载路径一致；未镜像到宿主机的纯远端数据不在此删除。

2026-04-15 新增 POST /api/skills/sync-workspace-skills 接口，支持按 Agent 配置批量同步 skills 到 workspace，purge_extra 可清理多余 skill；server 与 desktop 共用同一业务逻辑。

2026-04-14 修复 Web 端技能列表页保存后卡住：移除 Agent 维度 Tab 及 getAgents 并行调用，loadSkills 改为仅调 getSkills；保存/导入/删除后静默刷新不再全屏 loading。

2026-04-14 提取 agent 工作空间路径管理为独立模块 `agent_workspace.py`，重构 chat_service/skill_service/agent_service 统一调用新接口；server 模式下新增技能自动同步逻辑；content-script.js 加 IIFE 初始化守卫防重复执行。

2026-02-22 12:40:00 Prompts Update: Enhanced Fibre Sub-Agent (Strand) prompts to include full Orchestrator capabilities (planning, decomposition, delegation) while retaining mandatory task result reporting requirement.
2026-03-06 12:00:00 新增Session改造方案文档，采用预置Agent类注册并将default_memory_type改为运行时传入。
2026-03-06 12:20:00 备份sagents.py并引入Session运行时，SAgent入口改为委托SessionManager。
2026-03-06 12:35:00 直接重写sagents.py内SAgent实现，移除别名替换写法。
2026-03-06 12:50:00 调整SAgent参数到run_stream，并拆分session_space与agent_workspace路径。
2026-03-06 13:05:00 清理sagents.py旧代码并强制run_stream必传运行时参数。
2026-03-06 13:20:00 SessionManager改全局单例，收尾下沉Session并删除sagent_entry.py。
2026-03-06 13:35:00 改为SessionManager持有会话状态，SAgent初始化改含session_space并移除run_stream的session_space。
2026-03-06 13:50:00 对齐Fibre初始化参数，删除Session多余路由入参并保留会话关闭函数供显式清理。
2026-03-06 17:30:00 优化SessionContext与SessionRuntime：重命名set_history_context为set_session_history_context，合并system_context更新逻辑至_ensure_session_context以消除冗余，修复SAgent.run_stream缺失agent_mode参数问题。
2026-03-06 17:40:00 优化SessionContext路径管理：SessionContext必须传入有效的session_space；agent_workspace属性改为绝对路径字符串（原沙箱对象改为agent_workspace_sandbox）；移除_agent_workspace_host_path并更新Fibre Orchestrator引用。
2026-03-06 18:20:00 引入 AgentFlow 编排系统：新增 `sagents/flow` 模块（schema, conditions, executor），支持基于 JSON 结构的声明式流程定义。重构 `SessionRuntime` 支持 `run_stream_with_flow`，并在 `SAgent` 中实现默认的 Hybrid Flow（Router -> DeepThink -> Mode Switch -> Suggest）。
2026-03-06 19:10:00 修复 AgentFlow 参数透传：在 `_build_default_flow` 中使用传入的 `max_loop_count`，并确保 `agent_mode` 参数正确影响 Flow 的构建与执行。增加 `sagents/flow` 单元测试。
2026-03-06 19:30:00 完善 Flow 执行细节：恢复 `_emit_token_usage_if_any` 调用以确保 token 统计正常；`FlowExecutor` 遇到缺失变量时改为抛出异常；实现 `check_task_not_completed` 真实逻辑，综合判断中断、完成状态及待办列表。
2026-03-06 19:50:00 重构 Fibre Orchestrator：移除 `SubSession` 和 `SubSessionManager`，改用统一的 `Session` 和 `SessionManager` 管理子会话。删除废弃的 `sagents/agent/fibre/sub_session.py`，完成 Fibre 架构与全局 Session 运行时的统一。
2026-03-06 20:00:00 优化子会话路径结构与管理：Orchestrator 改用全局 `SessionManager` 单例；SessionContext 根据 `parent_session_id` 自动解析嵌套工作区路径（父会话/sub_sessions/子会话），不再硬编码扁平结构。
2026-03-06 20:15:00 增强 SessionContext 路径推断能力：显式引入 `parent_session_id` 初始化参数；`_resolve_workspace_paths` 现在能根据根 `session_space` 和 `parent_session_id` 智能推断父会话路径并构建嵌套结构。
2026-03-06 20:30:00 完善 Orchestrator 子会话创建流程：适配 `AgentFlow` 执行简单子 Agent，修正 `_get_or_create_sub_session` 和 `delegate_task` 的调用逻辑，确保路径、上下文及 Orchestrator 引用正确传递。
2026-03-06 20:40:00 规范化 Session 空间变量名：将 `session_space` 全局重构为 `session_root_space`，明确其作为根目录的语义，避免与具体 Session 工作区混淆。修正 Orchestrator 中的异步调用遗漏。
2026-03-06 20:50:00 优化 Session 持久化与发现机制：SessionContext.save() 现统一保存为 `session_context.json`（包含上下文、状态、配置概要），移除旧的 agent_config/session_status 文件；SessionManager 新增 `_scan_sessions` 自动建立路径索引，实现对任意嵌套深度会话的 O(1) 访问。
2026-03-06 21:00:00 清理旧版配置文件加载逻辑：SessionRuntime._load_saved_system_context 已完全移除对 session_status_*.json 的读取，仅支持标准的 session_context.json；SessionContext._load_persisted_messages 仅保留从 messages.json 加载消息，确保不再读取已废弃的旧格式文件。
2026-03-06 21:10:00 Agent 接口全面重构：简化 `AgentBase.run_stream` 签名，移除冗余的 `tool_manager` 和 `session_id` 参数，统一通过 `SessionContext` 传递上下文。同步更新所有 Agent 实现、SessionRuntime、FlowExecutor 及 Orchestrator 中的调用逻辑。
2026-03-06 21:30:00 适配应用层调用：更新 `sage_cli.py` 和 `app/server` 中的 `SAgent` 调用，适配新的 `session_root_space` 参数和 `run_stream` 接口；修复构建脚本 `build_simple.py` 以包含新引入的 `sagents/flow` 模块。
2026-03-06 21:40:00 适配演示与服务层：更新 `sage_demo.py` 和 `sage_server.py` 以适配 `SAgent` 新接口，并显式配置 `app/server` 启用沙箱。重构了 `run_stream` 的调用逻辑，确保与底层的 Session 机制变更保持一致。
2026-03-06 21:50:00 分离会话与工作空间：在 `sage_cli.py`、`sage_demo.py` 和 `sage_server.py` 中，将 `session_root_space` 设置为独立于 `agent_workspace` 的专用目录（如 `cli_sessions`, `server_sessions`），并显式传递 `agent_workspace` 参数，避免路径冲突和运行时错误。
2026-03-06 22:00:00 增强命令行与序列化支持：在 `sage_cli.py`、`sage_demo.py` 和 `sage_server.py` 中新增 `--session-root` 参数以支持自定义会话路径；优化 `make_serializable` 工具函数，增加对 `numpy` 数值类型的支持，解决 Tool 结果序列化报错问题。
2026-03-06 22:15:00 修复演示应用变量作用域：修复 `sage_demo.py` 中 `session_root` 变量未定义的错误，确保其正确从 `setup_ui` 传递至 `ComponentManager`。同时在 `ToolManager` 中全面应用 `make_serializable`，防止因工具返回 numpy 类型导致的 JSON 序列化崩溃。
2026-03-06 22:30:00 废弃 multi_agent 参数：在 `sage_server.py` 和 `sage_demo.py` 中彻底移除了已废弃的 `multi_agent` 参数及其逻辑，全面转向使用 `agent_mode` 控制智能体模式。同时更新了演示应用的 UI，使用下拉菜单选择 `agent_mode`。
2026-03-06 22:45:00 优化 Desktop 服务路径：在 `app/desktop` 中将 `workspace` 重命名为 `sessions`，并显式将 `agent_workspace` 设置为 `{sage_home}/agents/{agent_id}`，确保会话数据与 Agent 工作空间分离。
2026-03-06 23:00:00 适配会话消息读取逻辑：在 `app/desktop/core/services/conversation.py` 中，更新 `get_conversation_messages` 和 `get_file_workspace` 以支持新的 `sessions` 和 `agents` 路径结构，并实现了对子会话消息的嵌套读取支持。
2026-03-06 23:15:00 修正工作空间路径逻辑：在 `app/desktop/core/services/conversation.py` 中，修复 `get_file_workspace` 的路径推断逻辑，确保其使用正确的 `{sage_home}/agents/{agent_id}` 结构，与 `run_stream` 中的配置保持一致，避免因路径不匹配导致文件访问失败。
2026-03-06 23:30:00 重构 Session 消息读取：将 `get_session_messages` 逻辑下沉至 `SessionManager`，利用其扫描能力自动定位会话路径，并从 `SessionContext` 中移除该函数。同时恢复了 `app/desktop` 中 `get_conversation_messages` 的原始调用结构，保持了接口的稳定性和兼容性。
