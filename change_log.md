
2026-02-10 14:35:00
1. 功能增强：SimpleAgent 和 TaskExecutorAgent 现在支持自动提取并保存响应中的 Markdown 代码块到 `agent_workspace/artifacts` 目录。
2. 命名规则：Markdown 文件使用首行作为文件名（如果存在），其他代码块使用时间戳自动命名。
3. 架构优化：新增 `sagents/utils/content_saver.py` 工具模块，统一处理内容提取和保存逻辑，并将生成物归档至 `artifacts` 子目录。

2026-02-10 15:00:00
1. 体验优化：将 `update_file` 工具重命名为 `file_update`，并同步更新前端（Web/DevWeb）的标签和图标映射。
2. 描述改进：优化 `file_update` 的多语言描述，明确其“局部修改”的特性，引导用户优先使用该工具进行增量更新。

2026-02-10 15:10:00
1. 文档更新：在 `file_update` 工具描述中明确 `search_pattern` 参数支持正则表达式（取决于 `use_regex` 参数），消除歧义。
