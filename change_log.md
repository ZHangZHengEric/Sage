# Change Log

- **2026-07-15 18:49** 完成判断模型注入最近仍活跃的完整 Todo 计划，并保留每项完成、进行中或待办状态。

- **2026-07-15 18:29** 重复熔断恢复问卷改为自由填空，由用户直接说明后续策略、约束或停止要求。

- **2026-07-15 18:10** 问卷“其他”、回答标题及空值文案跟随中英葡语言，移除提交结果中的中文硬编码。

- **2026-07-15 18:00** 恢复问卷支持中英葡多语言，并让 self-check 接受 value/label 选项对象。

- **2026-07-15 17:40** 历史压缩结果持久保留恢复提示，引导模型重读关键文件并回顾重要过程。

- **2026-07-15 16:55** 恢复问卷固定使用英文，并让原始问卷消息原样进入后续模型历史。

- **2026-07-15 16:41** Simple 模式移除 final_answer；工具结果触发重复熔断时改为持久化恢复问卷。

- **2026-07-13 17:56** 去掉重复的 _build_probe_extra_body，能力探测直接复用 build_llm_extra_body(extra=...)。

- **2026-07-13 17:10** 抽取 build_llm_extra_body，压缩/主 Agent/能力探测共用同一套 reasoning 与思考参数配置。

- **2026-07-13 17:05** 压缩历史去掉写死 temperature，改跟会话 model_config；reasoning 模型仍由请求清洗去掉采样参数。

- **2026-07-13 16:25** 修复历史压缩：reasoning 模型（如 gpt-5.4）不再传自定义 temperature，避免 400 unsupported_value。

- **2026-07-08 19:30** 修复 retry 落盘测试：构造 APIConnectionError 时补全 openai SDK 要求的 httpx.Request 参数。

- **2026-07-08 19:15** 修复 LLM 连接错误重试成功后未写入 llm_request 的落盘遗漏：以 stream_succeeded 标志确保重试成功也会 add_llm_request。

- **2026-07-03 14:55** 新增希腊酸奶问卷坏例回归测试，验证 SelfCheckAgent 可检出 options 内误嵌 default/allow_other 的非法 JSON。

- **2026-07-03 14:50** SelfCheckAgent 为 Artifacts/Questionnaire 标签增加 JSON 语法与结构校验，失败时复用 runtime_diagnostic 重试流程，保留原有路径存在性校验。

- **2026-06-23 15:21** 格式化 `session_context.py` 与 `message_sanitizer.py`，修复 CI Ruff format 检查失败。

- **2026-06-23 15:11** 修复桌面端技能拖入无反应：接入 Tauri 文件拖放事件并将本地路径转换为 ZIP File 后批量导入。

- **2026-06-23 14:59** 桌面端技能库新增页面拖拽导入与多 ZIP 批量导入，复用现有上传接口逐个导入。

- **2026-06-18 16:58** 格式化 `sagents/utils/llm_request_utils.py`（ruff 0.15.14 单行签名），修复 CI Ruff format 检查。

- **2026-06-18 15:46** 修复发消息报 400「role 'tool' 缺前序 tool_calls」：新增 `drop_orphan_tool_messages` 并在发往 LLM 前清理孤儿 tool 消息，兜住压缩覆盖/offload/多调用 assistant 被丢弃导致的 tool 失配。

- **2026-06-18 15:40** 工作台修复补强：会话切换/新建时重置自动弹出抑制，并为面板 Transition 加 mode=out-in，消除离场过渡期间的 node.parentNode 报错。
- **2026-06-18 15:25** 修复桌面端工作台关闭后被流式新增项反复自动打开的问题。
- **2026-06-18 11:27** 更新 `sagents/README.md`，补充新版记忆/上下文压缩策略说明。
- **2026-06-16 13:43** 重写 `sagents/README.md`，补充核心编排层学习指南。
