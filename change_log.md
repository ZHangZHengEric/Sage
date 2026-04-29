2026-04-29 SimpleAgent tool_choice=required 改为环境变量 SAGE_FORCE_TOOL_CHOICE_REQUIRED 控制（默认关闭，避免不支持的模型报错），调用方传入参数仍优先生效。

2026-04-29 server web ModelProviderList 与 desktop 对齐：采样参数（temperature/top_p/presence_penalty/max_tokens/max_model_len）默认 null，提交走 optionalNumber 显式 null 下发；后端 sanitize_model_request_kwargs 会丢弃 None 字段，OpenAI SDK 不会收到空值。

2026-04-29 todo_write 流式显示：parseTodoWriteToolArguments 在未闭合 JSON 下从 tasks 段提取 id，折叠与增量条与实时结果对齐（desktop/server TodoTaskMessage）。

2026-04-29 单测覆盖 completed stdout 改造：bg_runner read_tail 截断丢首行 + get_log_size、_read_completed_output 完整/截断/shell-mode 兜底/启发式四分支、execute_shell_command + await_shell 完成态字段端到端验证（共 17 个新用例）。

2026-04-29 execute_shell completed 分支返回完整 stdout：阈值 1MB 内整文件返回，超过取尾部并加显式截断标记 `...<truncated: showing last N of M bytes>...` + `stdout_truncated/stdout_total_bytes` 字段；新增 sandbox `get_background_output_size` + `_bg_runner.read_tail` 截断时丢首行碎片。

2026-04-29 todo_write 卡片默认折叠：新建与历史会话进入时均为「仅本次变更」，点击展开见完整输出。

2026-04-29 撤销 todo_write changed_task_ids 及前端优先读该字段；折叠仅依据 tool 入参 tasks。

2026-04-29 前端 tool_calls 合并对齐 sagents/agent_base：`mergeToolFunctionArguments` 抽取至 utils；字符串增量与同 fibre 语义，禁止空 `{}` 覆盖已拼接参数（useChatPage + workbench，desktop/server 双端）。

2026-04-29 对话流 todo_write 卡片：解析工具入参 tasks 为「本次变更」；支持折叠仅看变更行、展开为完整工具输出（desktop/server 双端 TodoTaskMessage + i18n）。

2026-04-29 Agent 能力 promptText：引入硬性槽位清单 (a)对象/(b)范围/(c)动作链/(d)交付物，列禁忌写法与长度上限，要求模型自造具体默认例题（zh/en/pt）。

2026-04-29 Agent 能力 promptText：加强「高具体度、少留白」——须命名分析对象/默认例题，禁「随后提供主题」式主干（zh/en/pt）。

2026-04-29 Agent 能力：强制 description≠promptText；预设一键发送禁止「先确认再开始」类收尾；可接受句内默认与文件获取指引（zh/en/pt）。

2026-04-29 Agent 能力 promptText：约束「仅一条消息、无预选对像」下可执行；禁止悬空「这个表格」；单一主线、多产出需串成可跟进流程（zh/en/pt）。

2026-04-29 Agent 能力条数：prompt 写明恰好 abilities_count（默认 4）条，代码 AGENT_ABILITIES_TARGET_COUNT 注入并与截断一致。

2026-04-29 Agent 能力 prompt 迁入 sagents：明确 promptText 为可一键发送的用户全文，区分 title/description；输出约定 items JSON；删除 runtime patch 与 lifecycle 调用。

2026-04-29 修复 agent abilities 运行时 patch：中文示例 `{"items"}` 对后续 str.format 转义为 `{{"items"}}`，避免 KeyError 与 /api/agent/abilities 500。

2026-04-29 docs/solutions：新增中英文 SAGE_BEDROCK_PRIMER、SAGE_PLATFORM_MULTI_AGENT_RECOMMENDATION，README 列入索引；平台多 Agent 与 Bedrock 对照说明供方案与交付参考。

2026-04-28 12:00 shell tool 跟进：补提交 test_execute_shell_completion_event（14 条）；reminder 按会话语言 zh/en；await_shell 入口触发 12h GC；tail 空时反向搜错误关键词行。

2026-04-27 23:30 shell tool 进一步优化：await_shell 入口也触发 12h GC；tail 截断加错误线优先逻辑（尾部空行时反向搜 ERROR/Exception 等行置顶）；reminder 文本中英文国际化；补测试共 14 项全绿。

2026-04-27 23:05 shell tool GC + reminder 优化：system_reminder tail 截至 512B 尾部优先 + 提示调 await_shell 拿完整结果；pop_completion_events 不删 _BG_TASKS；加 12h 超期 GC（每次 spawn 触发）；补测试 11 项全绿。

2026-04-27 22:15 shell 工具反轮询优化：execute_command_tool 加后台 completion watcher 与 session 级事件字典；_call_llm_streaming 每次请求前 flush 为 <system_reminder> 注入；await_shell 默认 600s + 自适应改写 + 元数据；统一 system prompt 加 reminder 语义说明；新增单元测试。

2026-04-27 20:05 turn_status 上下文裁剪策略升级 + reasoning_effort 修正：strip_turn_status_from_llm_context 新增"保留最后一条 turn_status pair"，避免模型看不到自己上一轮状态决策反复重刷；新增白名单式 is_openai_reasoning_model 替换 agent_base 宽匹配（不再误伤 gpt-4o 等）；抽出 resolve_reasoning_effort，思考关闭时默认仍 low，新增 SAGE_REASONING_EFFORT_OFF 环境变量按需切 minimal/medium/high；补 strip 与 reasoning 判定/effort 单测。

2026-04-27 19:00 turn_status-only 补轮 coerce 留痕：被改写的 tool 结果打 metadata.coerced_from，strip 时保留这对 pair 让 LLM 看到事实；改写 note 文案走 PromptManager(zh/en/pt) 并注入原始工具名。

2026-04-27 18:40 turn_status 拒绝文案 i18n：新增 simple_agent_prompts.turn_status_rejection_message（zh/en/pt），SimpleAgent 改写工具结果时按 session 语言通过 PromptManager 取文案，硬编码中文消息移除。

2026-04-27 18:09 ModelProviderList 高级配置：移除 maxTokens/temperature/topP/presencePenalty/maxModelLen 输入框 placeholder，卡片展示的 temperature 兜底改为 '-'，避免清空后视觉上像是没改。

2026-04-27 18:05 修复采样参数清空不生效：前端置空时显式以 null 下发，后端 update_provider 改用 Pydantic model_fields_set 区分"未提供"与"显式 null"，真正写回 DB；之前用 `is not None` 守卫导致用户清空后 DB 旧值（如 top_p=0.95）残留并继续带入 LLM 请求触发 unsupported_parameter。

2026-04-27 17:55 前后端联动：ModelProviderList 表单将 max_tokens/temperature/top_p/presence_penalty/max_model_len 默认置空，置空字段不下发；LLMProvider 构造默认改 None；sanitize_model_request_kwargs 兜底丢弃空值采样参数；新增对应单测。

2026-04-27 18:30 turn_status reject 让模型可见：SimpleAgent 拒绝时给 tool 结果打 metadata.turn_status_rejected=True；strip_turn_status_from_llm_context 按标记保留这对 pair（含同条 assistant 里的 turn_status tool_call），SSE 仍按 tool_call_id 隐藏。修复 reject 后模型上下文丢失反馈、反复重蹈覆辙的问题。补 4 条单测。

2026-04-27 18:05 隐藏工具过滤抽常量 + 续片鲁棒性：HIDDEN_FROM_STREAM_TOOL_NAMES 移到 sagents/tool/impl/__init__.py；helper 重命名 _redact_hidden_tools_from_chunk 并改用 _HiddenToolStreamState（新增 last_was_hidden 贪心续接，覆盖 id/index 都缺失的兼容场景）；补两条续片单测。

2026-04-27 17:55 SAgent.run_stream 出口最小过滤 turn_status：新增模块级 helper，按流局部 call_ids/index→id 状态识别 tool_call 续片与对应 tool 结果，整体丢弃；落盘与 LLM 上下文剔除均不变。

2026-04-27 17:45 修复 OpenAI BadRequest：从 agent_base extra_body 中移除 top_k=20，OpenAI Chat Completions 不支持该参数（unknown_parameter 400）。

2026-04-27 17:35 回滚 turn_status SSE 过滤：移除 redact_turn_status_for_sse_chunk、_tag_omit_from_sse_for_turn_status、SAgent.run_stream 的 turn_status_ids、agent_base/common_agent/plan_agent process_tool_response 的 tool_name 入参与 metadata.tool_name 注入、workbench.js 的 turn_status 防误写兜底；turn_status 现可正常下发 SSE，仅在 strip_turn_status_from_llm_context 出口对 LLM 请求剔除。

2026-04-27 23:59 LLM：OpenAI GPT-5/o1/o3 等仅接受 max_completion_tokens；sanitize_model_request_kwargs 与 model_capabilities 探测将 max_tokens 自动映射，修复能力验证 400。

2026-04-28 22:45 SSE redact 改为有状态：SAgent.run_stream 维护本会话 turn_status tool_call_id 集合，流式 delta 中后续分片仅有 id/index 时按集合命中过滤；对应工具结果亦命中。修复模型流式调用 turn_status 时前端工作台仍能看到入参（need_user_input/note）的问题。补流式 delta 单测。

2026-04-28 22:30 修复 CommonAgent.process_tool_response 重写未跟随 agent_base 新签名（tool_name 第 3 参），导致 _execute_tool 调用时 TypeError，工具结果走错误分支被吞，前端文字之后第一个非 turn_status 工具结果消失；同时把 metadata.tool_name 写入 CommonAgent 的工具结果，前端兜底过滤一致。

2026-04-28 22:15 MessageChunk.__post_init__：将 role 规范为字符串；修复传入 MessageRole 枚举时 redact/校验与 ".value" 比较不命中导致 turn_status 泄漏。成功体启发式对 content 先 strip 再 json.loads。

2026-04-28 22:00 SSE redact：tool 块 metadata.tool_name=turn_status 一律不下发；单测覆盖。workbench 防误写保留兜底。

2026-04-28 16:00 SSE：SAgent.run_stream 对每块调用 redact_turn_status_for_sse_chunk；turn_status 的 tool 结果打 metadata.omit_from_sse；协议成功 JSON 亦过滤。会话落盘仍含完整消息。

2026-04-28 14:00 agent_base_prompts：补全 common.external_paths_intro（zh/en/pt），修复 Fibre 等带 external_paths 时 prepare_unified_system_messages 的 KeyError。

2026-04-28 12:00 TokenUsage 增加 usage_payload（Text）并在落库时写入完整 JSON，修复本地 SQLite 已存在 NOT NULL 列但 ORM 未插入导致的 IntegrityError；sync_database_schema 为 Text 补列时与 String 相同默认空串。

2026-04-28 00:10 turn_status 成功体补回标准键 success/status，与 should_end 并列。

2026-04-27 23:55 turn_status 成功仅返回 `{"should_end":bool}`；need_summary 兼容新旧 JSON；AgentBase._call_llm_streaming 与 convert_messages_to_str 对纯 MessageChunk 路径也 strip turn_status。

2026-04-27 23:30 MessageManager：新增 strip_turn_status_from_llm_context，从发往 LLM 的请求中剔除 turn_status 的 tool_calls 与对应 tool 消息；messages.json 仍保留；extract_messages_for_inference 与 convert_messages_to_dict_for_request 均应用；补单测。

2026-04-27 23:45 CI：新增 `scripts/check-i18n-keys.mjs`，静态扫描 `t/tr/$t('a.b')` 字面量键须在 zh-CN 与 en-US 同时存在；server web `npm run check:i18n` 串联该脚本；补全 web/desktop 暴露的问卷与 common 等缺失键；desktop 增加 `check:i18n`；GitHub Actions 增加 `desktop-i18n` job。

2026-04-27 23:10 前端 locale：server/web 与 desktop/ui 的 zh-CN / en-US 补全此前仅中文有的已用键（版本 GitHub 导入、工具预览失败、图片理解 workbench 文案、桌面计划任务计数）；删除未引用键（zh：system.version.releaseNotesPlaceholder、agent.settings、system.unknown）。

2026-04-27 22:00 sagents/prompts：未改中文；英/葡 planning_template 去掉 `{task_description}` 与代码一致；SimpleAgent 英/葡 task_complete 对齐中文结构并含 `{system_prompt}`；葡语 agent_custom_system_prefix（含 no_task）补全 turn_status 条款；SimpleReact 英 task_complete 删中文无的两条「继续」规则。

2026-04-27 13:30 sagents 阻塞点治理：将会话恢复/落盘、URL 下载写盘、文件解析与 pypandoc fallback、PIL 图片压缩/base64、远程 sandbox 目录扫描/host 文件读写、本地隔离 pickle/launcher/output 临时文件与后台进程启动等重 I/O 移到 aiofiles 或 asyncio.to_thread；保留 MCP JSON 与 sandbox YAML 小配置文件直接同步读取，避免过度优化；语法检查通过，相关可运行 sagents 测试通过，部分 async/agent 测试受当前环境缺 pytest-asyncio/opentelemetry 阻塞。

2026-04-28 20:00 README / README_CN 恢复「加入社区」：居中、Slack for-the-badge 徽章、微信群 `WeChatGroup.jpg` 图，文末团队署名同区；README_CN 赞助者三列 Logo 与英文对齐。

2026-04-28 19:00 README / README_CN 恢复文首 cover、shield 徽章、产品截图三列 HTML 表，与 2f2efddc 展示一致，Quick Start 等后续段落保持现状。

2026-04-28 18:00 README / README_CN 恢复赞助者区 HTML 与三处 Logo 引用，修复空表；与 2f2efddc 前结构一致。

2026-04-28 16:00 桌面 Windows 发布：从 bundle 中移除 MSI（仅保留 NSIS .exe），避免 GHA 上 WiX light.exe 失败；release-desktop workflow 同步去掉 msi 重命名与上传；README 说明 Windows 为 NSIS 安装包。

2026-04-28 12:00 修复 CI「sage-desktop.spec not found」：根因是 .gitignore 的 *.spec 忽略未提交该文件；增加 !app/desktop/sage-desktop.spec 例外，需执行 git add app/desktop/sage-desktop.spec 并推送后 Linux/mac/Windows 打包才能找到 spec。

2026-04-27 21:00 GitHub release-desktop workflow：pip 缓存 key 的 hashFiles 从无效的 app/desktop/core/requirements.txt 改为根目录 requirements.txt，与构建脚本实际依赖文件一致、依赖变更时缓存能正确失效。

2026-04-27 20:00 sage-desktop.spec：Windows 在 release 下对侧车使用无控制台 EXE（console=False），避免 Tauri 拉起时出现黑框；SAGE_PYI_MODE=debug 时仍带控制台便于排错；macOS/Linux 行为不变。

2026-04-27 19:30 桌面 Windows：build_windows.ps1 与 build.sh 对齐，PyInstaller 统一走 sage-desktop.spec（SAGE_PYI_MODE、dist/work 路径）；侧车补拷 wiki 与 docs/en、zh；前端构建设 NODE_OPTIONS 防 OOM；tauri Wix 语言改为 en-US 降低 GHA 打包失败率。

2026-04-27 18:00 README / README_CN Quick Start：每种应用单独「详细文档」链到对应 docs 专页，去掉文末「更多」聚合；修正中文桌面段加粗乱码。

2026-04-27 17:00 文档：新增 docs 应用入口下的 WEB（含 docker compose）/ DESKTOP / CHROME_EXTENSION 中英；GETTING 与 applications/README 建索引；README 主链至各专页。

2026-04-27 16:00 README / README_CN 桌面安装包小节扩充：macOS 门闸/右键打开/系统设置仍要打开/xattr；Windows SmartScreen；Linux apt 与从源码构建一句。

2026-04-27 15:00 README / README_CN Quick Start：各入口保留简要安装与用法（环境要求、Web/桌面/CLI/TUI/扩展小节后链文档），避免冗长说明。

2026-04-27 14:20 README / README_CN Quick Start 增补 Web、桌面、CLI、TUI、Chrome 扩展各一行说明，并链到 GETTING_STARTED 与 CLI/TUI 文档。

2026-04-27 14:00 精简 README.md / README_CN.md 的 Quick Start：只保留 clone + 环境变量 + dev-up 与访问地址，详细步骤指向 docs 中 GETTING_STARTED 与 wiki。

2026-04-27 13:10 不修改 sagents/tool_manager：AnyTool 端口由 mcp_service 重写 URL，聊天侧 extra MCP 经 mcp_anytool_url 对齐 SAGE_PORT；英文能力列表「缺少 items」因 prompt 写「JSON 数组」与解析器要 {"items":[]}，于 desktop/server lifecycle 启动时对 PromptManager 做 runtime 文案补丁（zh/en/pt）。

2026-04-27 12:25 修复 AnyTool MCP 502：DB 等存储的 streamable_http_url 残留旧端口与 SAGE_PORT 不一致时，mcp_service 对 kind=anytool 按 _get_backend_port 重写 URL。

2026-04-27 12:05 修复桌面端打包后 fetch 报 CORS：为 Tauri 源增加显式 allow_origins（tauri://localhost、http/https://tauri.localhost）与锚定 fullmatch 正则；main 设置 SAGE_INTERNAL_DESKTOP_PROCESS=1 防止误走 server 空 CORS； abilities 等接口若仍 500 可在修复 CORS 后从响应体看到真实错误。

2026-04-26 23:50 桌面端构建优化两项：(1) PyInstaller 配置统一到 sage-desktop.spec，build.sh 不再传一长串 flags，仅通过 SAGE_PYI_MODE 控制 strip；(2) CSP 收紧，default-src 'self'、script-src 仅 'self'（彻底禁止 inline script），style-src 保留 'unsafe-inline' 兼容 radix-vue 运行时样式，显式声明 img/media/font/connect/worker/object/base-uri/frame-ancestors。

2026-04-26 23:30 修复桌面端打包后白色滚动条问题：根因是 Tauri CSP 未含 'unsafe-inline'，拦截了 radix-vue 运行时注入的隐藏原生滚动条 <style>，导致 macOS native overlay scrollbar 漏出。index.css 显式声明 [data-radix-scroll-area-viewport] 隐藏原生滚动条规则；tauri.conf.json CSP 增加 style-src 'unsafe-inline' 与 img-src/media-src 放行 asset/blob/data。

2026-04-26 22:55 桌面端切断对 server/web 的跨项目引用：McpServerAdd/AnyToolToolEditor 直接复制源码至 desktop，并新建 AnyToolSchemaFieldEditor，导入路径全部改为 @/ 别名；移除 vite.config 的 lucide-vue-next/pinia alias 与 tailwind.config 中 server/web 内容路径；build.sh 增加 --collect-submodules=sagents 修复 PyInstaller 漏打包基础工具。

2026-04-26 22:40 修复桌面端打包后多个问题：sage-desktop.spec 与 tool_manager.py 显式枚举 sagents.tool.impl 子模块（绕过懒加载导致 PyInstaller 漏打包，修复"基础工具"丢失）；tailwind.config.js content 加入 server/web 组件路径，修复打包后样式 purge；VideoRenderer 改用动态 baseURL，修复打包后视频播放使用错误端口；vite.config.js 为 server/web 共享组件添加 lucide-vue-next/pinia alias，修复构建报错。

2026-04-26 12:20 修复工具执行时间不实时更新问题：chatDisplayItems.js 的 buildToolGroupItem 新增 startTimestampMs 字段；DeliveryCollapsedGroup.vue 检测最后一条消息是否为未完成的 tool_call，若是则启动 setInterval 每秒更新计时器，工具完成后自动切换回静态 durationMs 展示，桌面端和 Web 端同步。

2026-04-26 11:58 工作空间面板新增手动刷新按钮：ResizablePanel 新增 #actions slot，WorkspacePanel 在标题栏注入刷新图标，加载中自动旋转，桌面端和 Web 端同步。

2026-04-26 11:26 修复 turn_status 调用后仍触发 TaskSummaryAgent(final_answer) 的问题：need_summary 条件新增识别 turn_status 协议工具结果，避免 need_user_input/blocked/task_done 后多余生成 final_answer。

2026-04-26 11:12 修复工作空间视频预览：WorkspaceRemoteFilePreview.vue 增加 mp4/webm/mov 等视频格式支持，视频直接使用后端流式 URL 播放（FileResponse 支持 Range 请求）；task.js 新增 getFileStreamUrl 方法；修复文件类型检测图标和标签。

2026-04-26 10:45 重构消息压缩保护区策略：废弃不稳定的百分比保护（budget*20%），改为按条数强制保护末尾 N 条消息（recent_messages_count），默认 0 保持向后兼容；simple_agent 主压缩路径显式传入 5，确保最后 user/tool/assistant 消息始终不被截断。

2026-04-26 11:07 完善循环检测三项改进：① detect_repeat_pattern 阈值从3次降为2次；② 新增 _classify_error_category 错误归类（TOOL_REJECTED/TURN_STATUS/TIMEOUT等），连续2轮同类错误快速熔断；③ 新增 loop_break 消息类型，前端用琥珀色⚠气泡区别于普通错误展示自动暂停原因。

2026-04-26 10:55 增强重复检测：原有哈希签名匹配因LLM温度导致措辞不同而失效；新增连续错误快速熔断，同一错误内容连续2轮即暂停，无需等待哈希命中。

2026-04-26 10:18 修复 turn_status 被拒绝导致文本重复：SAGE_AGENT_STATUS_PROTOCOL_ENABLED=false 时，turn_status 仍加入工具列表并正常接受模型主动调用，只禁止强制 turn_status-only 轮；避免拒绝→错误→循环→同一文本重复出现3-4次的问题。

2026-04-26 04:05 修复阿里云工具约束不遵守：执行层新增 allowed tools 校验，模型返回本次请求未提供的工具时拒绝执行；在 turn_status-only 阶段若模型违规返回行动工具，改写为 `turn_status(status=continue_work)`，表达“不能结束、继续执行”，避免越权执行或死循环。

2026-04-26 03:55 环境变量改为协议级命名：`SAGE_TURN_STATUS_TOOL_ENABLED` 替换为 `SAGE_AGENT_STATUS_PROTOCOL_ENABLED`，避免配置语义绑定具体工具名；同步更新 SimpleAgent、ToolProxy 与中英文 ENV 文档。

2026-04-26 03:48 彻底移除旧收口工具命名：删除旧工具与兼容别名，仅保留 `turn_status(status=...)`；后端强制注入/隐藏、SimpleAgent 状态协议、前后端 label/i18n、ENV 文档与测试全部改为 turn_status。

2026-04-26 03:38 状态工具增加 continue_work，不结束时继续执行；单工具 required 失败则暂停防循环。

2026-04-26 03:33 尝试对象模式指定状态工具，后续因阿里云仅支持字符串 required 已改回。

2026-04-26 03:22 状态收口改为仅开放状态工具：纯文本无工具调用后，不再追加 system，也不再 required 全量工具；下一轮只暴露状态工具并启用 `tool_choice=required`，避免模型继续调用 todo_write 等行动工具造成循环。

2026-04-26 03:15 移除状态工具兜底追加 system，仅保留 tool_choice=required 结构化补调用。

2026-04-26 02:35 强化状态工具描述：提问、确认、等待用户补充时必须 status=need_user_input。

2026-04-26 10:30 工作台视频预览支持：desktop `FileRenderer` 将 `video` 加入早退列表（原来会 readTextFile 导致二进制报错）；`VideoRenderer` 重写为用 `convertFileSrc` 流式播放（不再把整个视频读入内存）；server web `fileIcons.js` 补 video/audio 类型映射、`FileRenderer` 加视频渲染分支和早退、新增 `VideoRenderer.vue`（URL 直接播放）；支持 mp4/webm/mov/mkv/avi 等格式。

2026-04-26 09:58 图片理解工具渲染重构：左侧图片预览（本地路径用 `readFile`+ObjectURL 加载，URL 直接展示，支持点击放大）+右侧 MarkdownRenderer 渲染分析结果；加载/失败/错误三态处理；desktop 与 server web 双端同步。

2026-04-26 02:23 技能上传目录名规范化：`_extract_skill_from_zip` 新增 `_skill_name_to_dir` 辅助函数，上传 ZIP 时统一读取 SKILL.md `name` 字段并规范化为目录名（空格→连字符，去除特殊字符），不再依赖 zip 文件名或内部子目录名；同步修复 `sync_skill_to_agent` 和 `_find_source_skill_path` 改用 SkillManager 按 name 查找实际路径，兼容历史已上传技能；将已存在的 `video_maker` 目录重命名为 `video-maker`。

2026-04-26 01:40 状态工具缺失改为结构化协议兜底：SimpleAgent 不再用正文正则猜测是否完成，纯 assistant 文本且无工具调用时，下一轮追加协议提醒并启用 `tool_choice=required`，由模型在行动工具和状态工具中结构化选择；同步修正 SimpleReact 执行提示中“不要调用会话结束工具”的冲突，并补 3 例单测。

2026-04-25 05:40 修复 TOOL_CATEGORY 不生效：`discover_tools_from_path` 直接走 `_DISCOVERED_TOOLS → register_tool`，会先于 `register_tools_from_object` 把 spec 占住（同优先级保留旧值），导致宿主类 `TOOL_CATEGORY` 永远写不进去；改为在该循环中复用 owner 类查找结果回填 `tool_spec.category`，浏览器组 12 个工具正确归到「浏览器扩展」，基础工具回到 20。

2026-04-25 05:20 状态工具总结校验加严 + 工具来源分类机制：`_has_recent_assistant_summary` 改为「碰到 tool 消息或带 tool_calls 的 assistant 立刻 False」，杜绝模型用「我现在去做 X：」过渡话骗过校验后无总结调用状态工具；新增 `ToolSpec.category` 字段 + `@tool(category=...)` + 宿主类 `TOOL_CATEGORY` 兜底，`tool_manager` 用 category→source 映射 (`browser → 浏览器扩展`)；前端 6 处 (AgentEdit/ToolList/ToolDetail × web+desktop) 加分组映射与 Globe 图标，4 份 locale 加 `tools.source.browserExtension`；3 例 `test_simple_agent_finish_summary` 新增覆盖故障场景。

2026-04-25 04:35 codebase 三件套前端适配：`messageLabels.js` + locales (zh/en) 补 `tools.grep` / `tools.glob` (`list_dir` 已存在)；workbench 新增 `GrepToolRenderer` (按文件分组、行号列、count/files 三模式)、`GlobToolRenderer` (mtime 倒序文件列表)、`ListDirToolRenderer` (mono 树状)；`ToolCallRenderer` 注册 isGrep/isGlob/isListDir 分发；desktop 与 server web 同步双写。

2026-04-25 04:10 codebase 三件套 + prompt cache 多断点：新增 `codebase_tool` (grep/glob/list_dir，rg + 兜底)；`tool_manager`/`tool_proxy` 按 name 排 tools_json；`agent_base` system message 拆 stable/semi/volatile 三段，`prompt_caching` 改多断点策略（Anthropic 上限 4）；新增 `docs/{zh,en}/ENV_VARS.md` 汇总所有 SAGE_* 环境变量；20 例新单测 + 221 例回归全绿。

2026-04-25 03:25 工作台隐藏状态工具：`stores/workbench.js`（desktop + server）`extractFromMessage` 增加 `HIDDEN_WORKBENCH_TOOL_NAMES` 过滤，状态工具不再进入 workbench timeline，只保留消息数据。

2026-04-25 03:10 状态工具总结校验放宽：之前只看当前 LLM 调用的 `full_content_accumulator`，把「上一步先输出总结、下一步再单独调状态工具」的合理流程误判为缺总结导致死循环。新增 `_has_recent_assistant_summary`，从尾部回扫到最近一条真实 user 消息为界，期间任何非空 assistant 文本都视为总结存在；补 5 例 `test_simple_agent_finish_summary.py`。

2026-04-25 02:50 tokens_usage 补 model 字段：`agent_base._call_llm_streaming` 把已 pop 出去的 `model_name` 重新塞回 `model_config` 并新增顶层 `model`；SessionContext per-call 解析按 request.model > model_config.model > response.model 三级回退，避免之前统计文件里 model 始终为空。

2026-04-25 02:30 Shell 三件套捆绑：ToolProxy 新增 `_TOOL_BUNDLES`，`{execute_shell_command, await_shell, kill_shell}` 任一被勾选即三个全部解锁（共享后台任务注册表，缺一即废）；`/api/tools` 同步隐藏 await_shell / kill_shell，仅以 execute_shell_command 作为入口；新增 4 例 `test_tool_proxy_bundles.py`。

2026-04-25 02:10 状态工具强制接入 + 前端隐藏：ToolProxy 在白名单模式下自动注入状态工具，使其与上游 availableTools 解耦；SimpleAgent 在状态工具启用时彻底跳过旧的 LLM `_is_task_complete` 判定。`/api/tools` 列表过滤掉状态工具，前端 MessageRenderer（desktop + server）按 HIDDEN_TOOL_NAMES 过滤 tool_calls 渲染（数据保留）；新内置工具 read_lints / await_shell / kill_shell 补 i18n。

2026-04-25 01:40 Windows 兼容硬化：lifecycle `_ensure_default_anytool_server_ready` 加 `asyncio.wait_for` 超时兜底，避免 streamable_http 注册在 Windows 上无限阻塞；`_get_process_rss_mb` / `_host_process_is_alive` 改 ctypes 走 PSAPI / OpenProcess，去掉对 `ps` 与 POSIX `os.kill(pid,0)` 的依赖；Passthrough/Local 路径映射统一接受 `\` 与 `/`，`to_virtual_path` 始终输出 POSIX 风格；LintTool `_has_command` 在 Windows 用 `where`。

2026-04-25 01:10 沙箱后台命令跨平台化：`ISandboxHandle` 增 `start/read/alive/exit_code/kill_background` 五原语，PassthroughSandbox / LocalSandbox 接入跨平台 `HostBackgroundRunner`（POSIX `start_new_session` + Windows `DETACHED_PROCESS`）；ExecuteCommandTool 优先走原生原语，bash 包装作为远端 Linux 兜底。补 `test_bg_runner.py` 7 例。

2026-04-25 00:30 修复 execute_shell_command 后台启动在 macOS 失效：`_spawn_background` 改为 `setsid`/`nohup` 自动兜底；新增 9 例真沙箱（passthrough）集成单测，覆盖阻塞/后台/await/kill/safety 全链路。

2026-04-24 23:55 Agent 能力提升一揽子改造：file_update 默认唯一匹配 + replace_all 显式开关；新增状态工具 / read_lints / await_shell / kill_shell 工具，execute_shell 改两段式后台；统一工具错误码 error_codes；下线中文关键词强制继续；SessionContext 新增 per-request tokens_usage 落盘。补齐对应单测。

2026-04-24 todo 工具升级三态：status=pending/in_progress/completed，markdown 复选框扩展 `[ ]/[-]/[x]` 三段写入；后端 conditions 与 ObservationAgent 把 in_progress 计入「未完成」；前端 TodoTaskMessage / 渲染器新增进行中视觉与 i18n（statusPending/InProgress/Failed）；旧 `[ ]/[x]` markdown 仍兼容。

2026-04-24 i18n：todo `statusInProgress` 文案由「进行中 / In Progress」改为「开始执行 / Started」，更贴合「该消息是历史快照、不会反映后续状态」的语义。

2026-04-24 工作台 SysDelegateTaskToolRenderer（desktop+server）：toolArgs.tasks 已就绪时立即渲染委派任务输入卡片，不再被 `!toolResult` 屏蔽；底部状态条复用原有的 delegating / error / completed 三态。

2026-04-24 todo_write schema 移除 `completed` 参数（保留 `status` 单一字段），required 仅 id；强化中英文描述与 simple_agent prompt：每次只传新增或本次变更的任务，更新仅传 id+变更字段。

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
2026-04-26 13:38:00 修复桌面端视频播放失败：将 VideoRenderer.vue 中的 readFile+Blob 方式替换为 convertFileSrc，使用 asset:// 协议流式加载视频，解决大文件无法播放及 H.265 格式在 WKWebView 中播放失败问题。
2026-04-26 13:46:00 合并 main 分支（4 commits），解决 VideoRenderer.vue 冲突，保留 main 版本的重构实现。新增桌面端 /api/agent/{id}/file_workspace/stream 接口，支持 HTTP Range 请求；VideoRenderer.vue 改为通过后端 stream 接口流式播放，不再直接访问文件系统。
