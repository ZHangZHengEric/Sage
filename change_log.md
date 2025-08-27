# Sagents 项目修复记录

## 2025-01-27 16:45 - 添加CLI命令行使用介绍
- **文件**: `README.md`, `README_CN.md`
- **新增**: sage_cli.py命令行工具的详细使用介绍，包含基本用法、高级选项和功能特性
- **引导**: 添加指向examples/README.md的链接，方便用户查看详细的CLI使用文档
- **作者**: Eric ZZ

## 2025-01-27 16:30 - 同步中文README所有功能更新
- **文件**: `README_CN.md`
- **同步**: 将英文README的所有更新同步到中文版本，确保中英文内容完全对齐
- **更新**: 多智能体协作v0.9.3、内置MCP服务器、自定义Agent开发、AgentFlow编排等所有新功能的中文介绍
- **作者**: Eric ZZ

## 2025-01-27 16:00 - 添加自定义Agent和AgentFlow功能介绍
- **文件**: `README.md`
- **新增**: 自定义Agent开发框架、AgentFlow编排功能、Agent转Tool机制详细说明
- **完善**: 包含完整代码示例的自定义Agent开发指南，更新v0.9.3版本新功能列表
- **作者**: Eric ZZ

## 2025-01-27 15:30 - 补充README遗漏功能介绍
- **文件**: `README.md`
- **新增**: Streamable HTTP MCP连接方式、13个专业agent类型、MCP连接类型对比表
- **完善**: MCP安全功能、API密钥认证、连接验证等特性说明，更新v0.9.3版本新功能
- **作者**: Eric ZZ

## 2025-01-27 15:00 - 更新README功能介绍
- **文件**: `README.md`
- **更新**: 添加内置MCP服务器、高级文件系统操作、安全功能等新特性介绍
- **新增**: 文件解析器、命令执行、Web搜索等MCP服务器详细说明，更新v0.9.3版本功能列表
- **作者**: Eric ZZ

## 2025-01-27 14:30 - 版本更新至0.9.3
- **文件**: `setup.py`, `README.md`, `README_CN.md`
- **更新**: 将项目版本从0.9.2升级到0.9.3
- **修改**: 更新setup.py中的版本号，同步更新英文和中文README文件中的版本徽章
- **作者**: Eric ZZ

## 2025-01-25 16:50 - 优化文件内容搜索功能
- **文件**: `sagents/tool/file_system_tool.py`
- **优化**: 改进search_content_in_file函数，不再按行切分，直接在整个文件内容中搜索字符，移除行号和行内容返回
- **特性**: 基于字符位置的精确搜索，智能合并重叠上下文，按匹配关键词数量和位置排序
- **作者**: Eric ZZ

## 2025-01-25 16:45 - 完成文件内容搜索功能实现
- **文件**: `sagents/tool/file_system_tool.py`
- **功能**: 完成search_content_in_file函数的实现，支持多关键词搜索、评分排序和上下文提取
- **特性**: 按关键词匹配数量评分，支持自定义上下文大小和返回结果数量，包含详细的执行日志和错误处理
- **作者**: Eric ZZ

## 2025-01-25 14:30 - 修复流式响应合并类型错误
- **文件**: `sagents/utils/stream_format.py`
- **问题**: ChatCompletion choices字段类型错误，导致 "Cannot instantiate typing.Union" 错误
- **修复**: 导入Choice类型，将choices字段从字典改为Choice对象实例化，并将ChatCompletionMessageToolCall的type字段固定为"function"
- **影响**: 修复了TaskExecutorAgent流式响应合并失败的问题

## 修复内容总结

### 1. 类型注解统一 (message_manager.py, executor_agent.py)
- 将相关方法和参数的类型注解从 `List[Dict[str, Any]]` 修改为 `List[MessageChunk]`
- 确保类型一致性，避免 AttributeError

### 2. MessageChunk 对象属性访问统一 (sage_demo.py)
- 统一使用点号访问属性（如 `chunk.content`）而不是字典访问（如 `chunk['content']`）
- 修复了所有相关的属性访问方式

### 3. session_id 访问方式统一 (sagents/agent/ 目录)
- 统一 `sagents/agent/` 目录下所有文件中 `session_id` 的访问方式
- 从字典访问 `session['session_id']` 改为直接访问 `session.session_id`

### 4. 移除不再使用的代码 (message_manager.py)
- 移除 `self.pending_chunks` 属性初始化
- 移除 `_filter_default_strategy` 方法
- 移除 `clear_messages` 方法中对 `self.pending_chunks` 的引用

### 5. 修复 planning_agent.py 中 content 重复问题
- 修改 `_execute_streaming_planning` 方法中 `show_content` 的赋值
- 从 `delta_content_all` 修改为 `delta_content_char`，确保每次 yield 的内容不重复

### 6. 重新优化 message_manager.py 中 add_messages 方法
- **第一次修复**: 添加了对 `is_final` 属性的判断，当 `is_final=True` 时直接替换内容，否则追加内容
- **第二次优化**: 根据用户反馈，移除了对 `message.is_final` 的判断
- **最终优化**: 简化逻辑，对于流式消息直接追加增量内容，移除不必要的属性更新
- 解决了 `content` 和 `show_content` 重复的问题
- 流式消息的特点是每次传递的都是新的增量内容，无需复杂的判断逻辑

## 修复的主要问题

1. **AttributeError**: 'MessageChunk' object has no attribute 'get'
2. **类型不匹配**: List[Dict[str, Any]] vs List[MessageChunk]
3. **content 重复**: 流式消息内容被重复累积
4. **show_content 显示不正确**: 显示内容与实际内容不符

## 技术要点

- MessageChunk 是 dataclass 对象，应使用属性访问而非字典访问
- 流式消息处理需要正确处理增量内容的累积
- 类型注解的一致性对于避免运行时错误至关重要
- 简化的逻辑更容易维护和理解

## 2025-01-25

### 修复消息重复问题
- **文件**: `sagents/agent/message_manager.py`
- **方法**: `add_messages`
- **问题**: 消息内容被重复添加
- **修复**: 在处理消息时，根据 `MessageChunk` 的 `is_chunk` 属性判断是追加内容还是替换内容，避免消息重复
- **影响**: 解决了消息管理器中消息重复的问题

### 修复会话状态保存时的重复序列化问题
- **文件**: `sagents/agent/agent_controller.py`
- **方法**: `_save_session_state`
- **问题**: `MessageChunk` 对象被重复序列化导致数据结构不正确
- **修复**: 移除了对 `_convert_message_chunks_to_dicts` 方法的调用，因为 `MessageManager.to_dict()` 已经处理了 `MessageChunk` 对象的转换
- **影响**: 避免了重复序列化导致的数据问题

### 修复任务分析阶段后message_manager重复获取问题
- **文件**: `sagents/agent/agent_controller.py`
- **方法**: `run_stream`
- **问题**: 在任务分析阶段完成后，代码重新从 `_session_managers` 获取 `message_manager`，导致消息内容重复
- **修复**: 移除了不必要的 `message_manager` 重新赋值操作，直接使用传入的参数实例
- **影响**: 解决了任务分析阶段后消息重复显示的问题

所有修改已完成并测试通过。

## 2025-01-25 (下午)

### 修复智能体消息重复添加问题
- **时间**: 2025-01-25 16:30
- **问题**: 所有智能体在 `run_stream` 方法中重复调用 `message_manager.add_messages`，导致消息被重复添加到 MessageManager
- **修复方案**: 
  1. 修改 `agent_base.py` 中的 `_collect_and_log_stream_output` 方法，添加 `message_manager` 和 `agent_name` 参数，统一处理消息添加
  2. 更新所有智能体的 `run_stream` 方法，在调用 `_collect_and_log_stream_output` 时传递必要参数
  3. 删除各智能体中重复的 `message_manager.add_messages` 调用
- **修复文件**: `agent_base.py`, `task_analysis_agent.py`, `task_decompose_agent.py`, `observation_agent.py`, `direct_executor_agent.py`, `executor_agent.py`, `task_summary_agent.py`, `inquiry_agent.py`, `planning_agent.py`
- **影响**: 避免消息重复，统一消息管理逻辑，简化代码维护

### 修复 TaskAnalysisAgent 中 yield from 导致的消息重复
- **时间**: 2025-01-25 16:35
- **文件**: `task_analysis_agent.py`
- **问题**: `_execute_streaming_analysis` 方法中使用 `yield from` 直接传递消息，导致消息被 `_collect_and_log_stream_output` 重复处理
- **修复**: 将 `yield from` 改为 `for...yield` 循环，确保消息流正确传递
- **影响**: 解决 TaskAnalysisAgent 中消息重复显示的问题