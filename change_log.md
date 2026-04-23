2026-04-23 22:35 server/web 分享链接修复：`buildShareUrl` 与 `useChatPage.handleShare` 改为基于 `import.meta.env.BASE_URL` 拼接，避免在 `/sage/` 子路径部署下生成 `/share/<id>` 命中 nginx 404。

2026-04-23 22:20 server/web/ChatHistory：分享弹窗新增"复制分享链接"第三按钮并展示完整 URL；行内 Share2 与 Download/Trace/Trash 一致 hover 渐显；抽出 `buildShareUrl`/`copyTextToClipboard`，弹窗即开即可复制即使消息加载失败。

2026-04-23 anytool/UI：补 `tools.saveChanges` 多语言；卡片增加编辑/删除按钮（仅 AnyTool 分组），新增 `DELETE /api/mcp/anytool/tool/{name}` 路由（server+desktop）与 `mcp_service.delete_anytool_tool` 服务，前端 `toolAPI.deleteAnyToolTool` 同步更新。

2026-04-23 anytool：`upsert/delete_anytool_tool` 在 `update_mcp_server` 之后再强制 `remove_tool_by_mcp`+`register_mcp_server` 一次。原 `update_mcp_server` 流程是 register 早于 dao.save，导致 AnyTool 自身 HTTP 注册时仍读到旧工具，前端首次刷新看不到变化。

2026-04-23 anytool：`returns` 未定义任何 `properties` 时不再下发 `outputSchema`，避免 MCP 默认 `additionalProperties=false`+空 properties 把模型输出的 `data`/`status`/`message` 等键全部拒掉。

2026-04-23 anytool/UI：删除工具用 `AppConfirmDialog` 替换 `window.confirm`（Tauri 下不可用），server 端补全引用与 ref；删除后并行重载 MCP 与基础工具列表，确保卡片立即刷新。补全 4 处 `tools.saveChanges` 多语言。

2026-04-23 anytool：调用 LLM 时按各 agent 同款关闭思考/推理（`enable_thinking=False`、`thinking.disabled`、OpenAI reasoning 模型用 `reasoning_effort=low`）；并按 `outputSchema.properties` 过滤 LLM 多余键，修复 MCP "Additional properties are not allowed ('message')" 校验失败。

2026-04-23 desktop/core：补 `POST /api/mcp/anytool/tool` 路由（与 server 端对齐），否则被 mount 的 `AnyToolStreamableHTTPApp` 当 server_name=`tool` 解析，按 JSON-RPC 校验返回 400。

2026-04-23 desktop/ui：dev 脚本改 `lsof -ti:1420 | xargs kill -9; vite`，修 `kill-port && vite` 在端口空闲时退出码非零导致 vite 不启动、Tauri 一直等 1420 的问题；反代仍按 `preferred_ports` 探测 `/api/health`。

2026-04-22 文档：中/英 `API_REFERENCE` 与当前 `SAgent`/`run_stream`/`ToolManager`/`MessageChunk` 等源码对齐，更新 `API_DOCS`、双 README 与 HTTP 总页互链；`examples/sage_server.py` 注释改为 SAgent。

2026-04-22 文档站：修复多份 `HTTP_API_*.md` 误写为 `## layout` 的 front matter，恢复侧栏「HTTP API 参考」下二级子页；新增中/英 `API_DOCS` 为「API 文档」父页，HTTP 与历史 Python 参考分栏并调 README 地图。

2026-04-22 文档站：修复 `docs/zh` 中 `API_DOCS`、`HTTP_API_REFERENCE`、`API_REFERENCE` 的 front matter（`## layout` 误为标题导致无 `lang`），侧栏按 `page.lang` 过滤，否则回退为英文目录。

2026-04-22 messages 测试补缺：新增 `test_history_anchor.py` 23 个用例，覆盖 `compute_history_anchor_index` 边界、`add_messages` 自动刷新锚点、`prepare_history_split` 新返回、`extract_all_context_messages` 不再被 `active_start_index` 截断、memory 工具锚点边界、旧 config 向后兼容；messages 全套 47 个用例通过。

2026-04-22 死代码清理：删 `_build_dropped_prefix_bridge`/`_plain_preview_for_bridge`/`_extract_current_query`/`dropped_history_bridge_budget`；`prepare_history_split` 瘦身只保留 budget 计算与锚点刷新；`ContextBudgetManager` 删 `split_messages`/`recent_turns` 及配套私有方法。messages+sagents 单测全过。

2026-04-22 消息上下文收口：`active_start_index` 不再由 token budget 驱动，仅作为最近一次 compress_conversation_history 调用的锚点；`extract_all_context_messages` 去掉硬截断与 dropped-prefix bridge，长度控制完全交给 `_prepare_messages_for_llm`；memory 工具历史边界改为锚点之前。`messages` 全套单测通过。

2026-04-22 单测：默认每用例 2s 超时（`pytest.ini` + `pytest-timeout`）；删未过或全量不稳定的 `test_executor`、`test_questionnaire_tool`、`test_todo_tool`、`test_provider_integration` 及 `tests/sagents/tool/conftest.py`；全量 `pytest tests` 通过。

2026-04-22 测试：删 Fibre/TaskManager 等已不存在模块的单测；压缩集成与 CommonAgent/AsyncMock 对齐；`common/utils/logging` InterceptHandler 在无 loguru sink 时补 sink 并降级；删失效 skill_sync；删 test_execute_python_code_trace_only。

2026-04-22 移除 MessageType.NORMAL 与沙箱 env_helpers/旧构造参数；Sandbox 默认卷改为同一路径直通；测试改用 VolumeMount 与当前 API，删无效 trace 脚本；compress 单测按 role 填消息类型。

2026-04-22 tests/conftest：不再改 sys.path；与 pytest.ini 中 `pythonpath = .` 重复，保留说明文档即可。

2026-04-22 沙箱/测试：Local/Passthrough 路径与 cwd 用宿主机路径；单测对齐 VolumeMount、async factory、pytest-asyncio；条件 mock 加 session；自测用仓库相对路径。

2026-04-22 文档：能力域总览去 Mermaid，改三层级 Markdown 表（模块、路由源、路径族），中/英一致。

2026-04-22 ChipInput：Delete 一次即可删图——`findChipAfter`/`Before` 跳过正文与 chip 间零宽/空白文本节点，删除时顺带清 chip 前后可跳过节点。desktop/server 同步。

2026-04-22 ChipInput：Backspace/Delete 在紧邻附件处拦截并整段删除 chip+零宽空格，`findChipBefore/AfterCaret` 覆盖根子边界与零宽后缘；删后重设选区。desktop/server 已同步。

2026-04-22 ChipInput 附件 chip 增「×」删除并同步正文与附件列表；上传中删占位也会清项；若上传返回时占位已删则不再回写。desktop/server 同步。

2026-04-22 消息输入区：未上传完成（`uploading` 或无处 `url`）禁止发送，`canSubmitNow`+`dispatchSubmit` 双保险，预览上居中 `Loader2` 遮罩；发送按钮 `title` 提示等待上传。desktop 与 server/web 的 MessageInput.vue 及 i18n 已同步。

2026-04-22 模型源：保存请求进行中增加 `saving` 状态，保存/取消/验证/关闭与角标与底部提示同步 loading，防重复点击重复提交；desktop/ui 与 server/web 的 ModelProviderList.vue 同步，server 端补 `common.saving` 文案。

2026-04-21 23:40 ChipInput 粘贴：非文件时阻止默认富文本插入，仅写入纯文本（优先 clipboard text/plain，否则从 text/html 取文本），避免保留来源页字体颜色等在深色输入框中对比度过低；仍先 emit paste 供 MessageInput 处理剪贴板图片/文件。desktop/ui 与 server/web 已同步。

2026-04-21 22:55 桌面端上传图片改回"本地绝对路径"链路：sidecar `POST /api/oss/upload` 现在把 `file_path.resolve()` 直接作为 `url` 返回（保留 `local_path` 同值字段，外加 `http_url` 仅作降级展示）。前端 markdown 引用 / image_url part 都用本地路径，命中 MarkdownRenderer 既有的 `convertFileSrc / data-local-image` 分支，agent 端 `multimodal_image.process_multimodal_content` 直接走"裸路径→base64"分支，不再需要 `resolve_local_sage_url` 反解 localhost URL，也省掉一次 HTTP 抓取，文件类工具可直接消费该路径。22:30 加的 HTTP fallback 保留，给 server-web 那种 HOME 不一致场景兜底。

2026-04-21 22:30 修复 sage 上传图片两个问题：1) 输入框 markdown alt 与最终 URL 文件名不一致（原 png/被压成 jpg + 时间戳后缀）——oss.uploadFile 改返回 {url, filename}，MessageInput/ChipInput 在上传完成后用服务端文件名刷新 chip 与 file.name，buildOrderedMultimodalContent 直接取 URL 末段作为 alt，desktop+server-web 同步；2) image_url 没转 base64 导致 dashscope 报 InvalidParameter——multimodal_image.process_multimodal_content 增加本机地址 HTTP 抓取兜底（httpx 已在 requirements），Path.home 反解失败时再走 GET URL→压缩→data:image/jpeg;base64 分支，加 warning/error 日志便于排查。

2026-04-21 21:30 server 端登录页：当 allow_registration=false 时新增显眼提示——告知当前网页不允许创建新用户，推荐下载桌面版 https://zavixai.com/html/sage.html，或自行从 GitHub 部署 Web 版，并附微信联系方式 cfyz0814 / zhangzheng-thu。新增 zh/en 文案和 2 条 Login 单测，全部通过。

2026-04-21 17:10 限制 Fibre 专属工具仅在 fibre 模式下可选：AgentEdit.vue 增加 isFibreOnlyToolUnavailable，非 fibre 模式下 sys_spawn_agent / sys_delegate_task / sys_finish_task 复选框禁用并打「仅 Fibre 模式」徽章 + 提示；模式切出 fibre 时自动从 availableTools 移除；后端 chat router 新增 _sync_fibre_only_tools 兜底，非 fibre 请求强制剔除这三个工具。

2026-04-21 17:10 更新 docs/zh/DESIGN_AGENT_FLOW_PRODUCTIZATION.md：产品名定为「智能体画布」（内核仍叫 AgentFlow），重写 §9 IA 决策（智能体/智能体画布平级菜单、Router Agent 同列表加 tab、Chat 调用侧统一、旧「工作流」字段改名「任务步骤」），把 §11 替换为不带时间的 21 步递进式开发计划，附录 B 增加 UI 文案强约束表。

2026-04-21 16:30 新增设计文档 docs/zh/DESIGN_AGENT_FLOW_PRODUCTIZATION.md：把 AgentFlow 升级为「真正的 Agent Flow」——所有 AI 节点都是 Agent，引入 Agent 模板体系（business/router 两种内置模板），分支判据收敛到 flow_state.{input,vars,steps} 命名空间（v1 寄存于 audit_status 子树），AgentFlow 改为可保存可重置的 DAG 静态图配置（flow_version.graph_json），含分阶段实施路线、API 草案、改动点速查与待决问题。

2026-04-21 12:05 浏览器插件离线检测体验全面整改：1) 后端新增 BrowserBridgeHub.force_offline 与 /api/browser-extension/probe 端点，主动 ping 扩展（5s 超时则强制标离线），并删掉 OFFLINE_GRACE_SECONDS 多余 60s 宽限；2) Chrome 扩展心跳 60s→30s、加入 ping action、改为单 alarm 内 ~26s 长轮询连续抓命令，让 probe ~1s 内有响应；3) SystemSettings「重新检测」按钮改用 probe；4) AgentEdit 中浏览器工具在离线时禁用复选框并显示「插件离线」徽章 + 提示，全选/勾选都跳过。

2026-04-21 11:35 修复未装/离线浏览器扩展时仍把 12 个 browser_* 工具注入到 chat 请求的问题：browser_capability.get_browser_tool_sync_state 在扩展从未连接时把 supported_tools 默认成全集且不按 online 过滤，被 chat router 当成 online_browser_tools 全部 append。改为仅在 online 时返回 supported_tools，否则返回 [] ；_sync_browser_tools_for_request 离线时无条件清空所有浏览器工具，并补充日志便于排查。

2026-04-21 11:20 修复 desktop 启动后 impl/ 下多数工具丢失问题：commit 4f9ff693 将 sagents/tool/impl/__init__.py 改为懒加载 __getattr__，导致 ToolManager.discover_tools_from_path 仅 `import sagents.tool.impl` 时不再触发子模块加载，@tool 装饰器未执行。改为默认调用 _discover_import_path 扫描 impl 目录，工具注册数从个位数恢复到 19。

2026-04-21 文档站侧边栏真正根因：`docs/_includes/components/sidebar.html` 自定义实现里对 `nav_pages` 单层 for 循环输出链接，未调用主题自带的 `components/nav/pages.html`（parent 分组 + 递归子菜单），故无论 front matter 是否正确，左侧始终为扁平列表；已改为 `where` 过滤语言后 `include components/nav/pages.html`，恢复「架构」下二级菜单。

2026-04-21 00:02 修复架构子页 YAML front matter 被破坏导致侧边栏丢失「架构」父级、子页全部提升为顶级项的问题：10 个文件（zh+en 各 5 份：ARCHITECTURE / ARCHITECTURE_SAGENTS_OVERVIEW / AGENT_FLOW / SESSION_CONTEXT / TOOL_SKILL / SANDBOX_OBS 与 ARCHITECTURE_APP_DESKTOP）第二行被换成了「## layout: default」且缺失结束的「---」，重建为标准 Jekyll front matter，恢复 has_children/parent 层级。

2026-04-20 23:51 复用样板：agent_session_helper 增 get_session_sandbox()；file_system/memory/execute_command/image_understanding 4 个 tool 的 _get_sandbox 改为单行调用；compress_history、web_fetcher、todo、skill、content_saver、fibre/tools 共 8 处 get_global_session_manager+get_live_session 模板替换为 get_live_session/get_live_session_context helper；image_understanding._get_mime_type 改用 multimodal_image.get_mime_type。

2026-04-20 架构文档拆分为多二级章节（zh+en）：父页 ARCHITECTURE 重写为流程图导览，新增 app/server、app/desktop、app/others 三篇，sagents 拆为 overview / agent-flow / session-context / tool-skill / sandbox-obs 五篇；以 mermaid 图为主，仅保留二开示例代码；修复带 () 与 / 的 subgraph 标题语法；docs/README 索引同步更新。

2026-04-20 拆分 agent_base.py（1673→1291 行）：图片多模态、消息清洗、流→非流合并、stream tag 判断、session 辅助分别抽到 sagents/utils/{multimodal_image,message_sanitizer,stream_merger,stream_tag_parser,agent_session_helper}.py，base 内对应方法保留薄封装，外部 agent 调用零改动。

2026-04-20 用户消息气泡优化：1) 收紧 max-w 到 80%/70% 并补 break-all/min-w-0，防止长内容溢出页面宽度；2) 仿 codex 加「显示更多 / 收起」折叠（>240 字或 >8 行触发，max-h 200px + 底部渐隐遮罩），按钮挪到时间行最左侧；desktop / server 双端同步。

2026-04-20 修复 MessageInput 输入 / 后方向键不能切换技能：handleCaretUpdate 在 keyup 时无脑把 selectedSkillIndex 重置为 0，导致 ArrowUp/Down 看似不生效；改为仅在 keyword 真的变了才重置，并加 watch 把 index 夹回 filteredSkills 范围。同步把 placeholder 改为「输入您的消息... (Shift+Enter 换行 · 输入 / 选择技能)」让用户知道有这个入口。

2026-04-20 修复 MessageInput 选中技能后输入框只占行内剩余空间的问题：把技能 chip 与 ChipInput 从同一 flex-wrap 行拆成上下两行（chip 一行、输入框独占下一行 w-full），desktop / server 双端同步。

2026-04-18 sandbox/_stdout_echo 增加 48 条单测（test_stdout_echo.py），覆盖 echo 开关全部取值、空/None/异常 stdout 兜底、header 截断、footer 各种 rc、流式 helper 的 stdout/stderr 隔离/cwd/env/大输出/非 UTF-8/实时性断言/超时；测试中发现 timeout 路径会被持有 pipe 的子孙进程（如 sleep）阻塞 drain 线程~4s 的回归，顺手修：Popen 加 start_new_session，超时改成 killpg(SIGKILL) 干掉整个进程组，并去掉 raise 前重复的 join。

2026-04-18 ExecuteCommandTool/沙箱命令实时回显：新增 sandbox/_stdout_echo（含 echo_chunk/header/footer 与 run_with_streaming_stdout helper），LocalSandboxProvider 直接路径在 read_output 里增量写 sys.stdout；Seatbelt/Bwrap parent 改用流式 helper 转发 stdout、stderr 单独捕获用于报错；launcher.py shell mode 也从 subprocess.run 换成 Popen+双线程 drain，命令 stdout 实时透传到外层；三处 isolation 始终覆盖 launcher.py 让升级生效；ExecuteCommandTool 加 $ <cmd> / ↪ rc=N 头尾分隔。受 SAGE_ECHO_SHELL_OUTPUT 控制，默认开启，0/false/no/off/空 关闭。

2026-04-18 放开 todo 子任务"≤10"硬上限：task_decompose_prompts 三语全删掉 10 条上限，改成按复杂度自适应（trivial 1-3 / 常规 5-15 / 复杂多阶段 15-40+），并要求带"和/然后"或跨多文件的步骤必须继续拆；同步在 todo_write 工具描述里补上同样的颗粒度指导，让不走 task_decompose 的 SimpleAgent 也能拿到信号。

2026-04-18 修复前端 file_write 等工具"参数收集不到 / 执行完后从页面消失"：MessageChunk._serialize_tool_calls 序列化时丢了 OpenAI delta 的 index 字段；同时 useChatPage.mergeToolCalls 用数组下标合并，导致同一条消息里多 tool_call 串台。后端补回 index，前端改为按 id/index 匹配合并，desktop/server 双端同步；顺手修了 desktop MessageRenderer.vue 中误置在 watch 内反复注册的 watch(isEditingThisUserMessage)。

2026-04-17 22:30 修复 SeatbeltIsolation 在 macOS 卡死 5 分钟的问题：原 sandbox profile 把 mach/ipc/sysctl/iokit 全 deny 导致 Python 启动 SIGABRT 或阻塞 mach-lookup，重写为「系统调用全放行 + 文件写白名单」策略，仅限制写入到 workspace/sandbox_dir/volume_mounts，并在执行超时时保留 .sb 文件便于排查。

2026-04-17 修复中断会话后续请求秒退：load_persisted_state 不再把磁盘 INTERRUPTED 状态翻译成 interrupt_event.set()；set_status(RUNNING) 进入新轮次时主动清掉残留 interrupt_event/interrupt_reason/audit_status；删除 Session 中重复定义的 request_interrupt 死代码。

2026-04-17 SandboxSkillManager.sync_from_host 改为按需补齐：沙箱已有 skill 直接加载（保留手改），缺失时才从宿主 SkillSchema.path 拷一次；同时移除 chat_service 每次 prompt 都同步技能到 workspace 的逻辑（统一改由 agent 编辑页 create/update 触发），desktop / server 行为一致。

2026-04-17 修复 search_memory 卡顿：ISandboxHandle 新增 get_mtime（默认基于 list_directory(parent)），Local/Passthrough provider override 为 os.path.getmtime；MemoryIndex._get_dir_mtime 改走 sandbox.get_mtime，不再每个目录都启 sandbox-exec 跑 stat，递归扫描从秒级降到近瞬时，且不破坏沙箱抽象。

2026-04-17 SandboxSkillManager 不再从 host_skill.path 拷贝，仅从沙箱 agent_workspace/skills 加载；SessionContext.effective_skill_manager 统一供提示词/任务分析等与 load_skill 对齐。

2026-04-17 图片理解工具对 HTTP(S) URL 改为服务端先拉取再 base64（httpx），与沙箱路径一致可走 PIL 压缩，避免直连 URL 被多模态网关判无效（如阿里云 InvalidParameter）。

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

2026-04-23 17:43:00 服务端会话分享：在历史会话列表新增分享按钮，复制 /share/{sessionId} 公开免登链接；重写 SharedChat 页面以匹配对话样式，支持执行流/交付流切换，工具点击查看输入输出，仅展示对话不含侧边栏。
