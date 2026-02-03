---
layout: default
title: 更新日志
nav_order: 90
description: "Sage 示例和服务器更新日志"
---

# Sage Examples 修改日志

## 2026-02-03 - 前端 UI 重构与功能增强

**修改内容：**
- **前端 UI 重构**：
  - 全面优化界面设计，提升用户体验。
  - 新增移动端适配支持，确保在移动设备上的良好展示效果。
- **管理功能增强**：
  - **用户列表**：添加仅管理员可见的用户管理页面，支持用户查看与管理。
  - **系统设置**：新增系统设置页面，提供更丰富的系统配置选项。

**修改时间：** 2026-02-03

## 2026-01-31 - 记忆配置逻辑更新

**修改内容：**
- **配置参数更新**：
  - 将 `memory_root` 参数替换为 `memory_type` (session | user)。
  - `memory_root` 参数已标记为废弃，但保留向后兼容性（自动设置 `MEMORY_ROOT_PATH` 环境变量）。
- **环境变量支持**：
  - 新增 `MEMORY_ROOT_PATH` 环境变量，用于指定用户记忆的存储路径。
  - 默认路径逻辑：若未设置环境变量，则使用 workspace 下的 `user_memory` 目录。
- **组件更新**：
  - 更新了 `sage_cli.py`, `sage_demo.py`, `sage_server.py` 以支持新的记忆配置逻辑。

**修改时间：** 2026-01-31

## 2026-01-25 - 支持注解方式定义工具

**修改内容：**
- **工具开发优化**：
  - 支持使用 `@sage_mcp_tool` 注解定义内部工具，自动处理 Schema 生成和工具注册。
  - 推荐使用注解方式替代传统的类继承方式，简化开发流程。
- **文档更新**：
  - 更新 `TOOL_DEVELOPMENT_CN.md` 和 `TOOL_DEVELOPMENT.md`，添加注解定义工具的详细指南和示例。

**修改时间：** 2026-01-25

## 2026-01-25 - 添加观测链路与增强功能

**修改内容：**
- **添加观测链路**：增强系统可观测性，支持链路追踪与性能监控。
- **Server 功能增强**：
  - 添加多 LLM 代理池支持，提高模型调用的灵活性和可靠性。
- **核心功能扩展**：
  - 添加 Skill 功能，扩展智能体能力边界。
  - 添加记忆功能，支持长短期记忆管理，提升上下文连贯性。
- **测试工具**：
  - 添加压测脚本，用于评估系统在高并发场景下的性能表现。

**修改时间：** 2026-01-25

## 2026-01-09 14:45:00 - 更新 Sage Server 部署文档与构建脚本

**修改内容：**
- **更新 README_SERVER.md**：
  - 补充本地源码部署指南（非容器化启动方式）
  - 完善环境变量与命令行参数的配置说明对照表
  - 修正 Docker 运行示例中的端口映射
- **服务端重构为模块化启动**：
  - 修改 `app/server/docker/Dockerfile`，使用 `python -m app.server.main` 启动以解决相对导入问题
  - 修改 `app/build_exec/build_server.py`，生成临时入口脚本以支持模块化打包

**修改时间：** 2026-01-09 14:45:00

## 2025-12-30 12:00:00 - 新增 Web 前端与 Server 后端服务

**修改内容：**
- **新增 Web 前端服务 (`app/web/`)**：
  - 基于 Vue 3 + Vite 构建的现代化 Web 界面
  - 提供 Agent 配置、对话交互、知识库管理、MCP 服务器管理等功能可视化操作
  - 支持 Docker 容器化部署
- **新增 Server 后端服务 (`app/server/`)**：
  - 基于 Sage 框架的智能体流式服务，提供 HTTP API 和 SSE 实时通信
  - 支持多种 LLM 模型配置、MCP (Model Context Protocol) 服务集成
  - 提供完整的 Docker 部署支持，包括工作区、日志挂载及详细的参数配置能力

**修改时间：** 2025-12-30 12:00:00

## 2025-09-21 21:11:00 - 修复sage_demo.py MCP工具发现功能

**问题**: sage_demo.py中_init_tool_manager方法缺少MCP工具发现逻辑，导致MCP工具无法被正确注册

**修复内容**:
1. 将`_init_tool_manager`方法改为异步方法，添加完整的MCP工具发现流程
2. 添加`_auto_discover_tools()`调用进行基础工具发现
3. 添加`_discover_mcp_tools()`异步调用进行MCP工具发现
4. 将`initialize`方法改为异步方法，使用`asyncio.run()`在Streamlit中调用
5. 添加asyncio导入支持异步操作

**测试结果**: MCP工具发现功能正常，成功注册23个工具，环境变量设置正确，应用启动正常

## 2025-09-21 21:07:00 - 修复sage_demo.py参数未使用问题

**问题**: sage_demo.py中mcp_config和preset_running_config参数未被使用

**修复内容**:
1. 在`_init_tool_manager`方法中添加mcp_config环境变量设置逻辑
2. 在`__init__`方法中添加preset_running_config配置读取和system_prefix传递逻辑
3. 在`_init_controller`方法中添加system_prefix和memory_type参数传递

**测试结果**: 功能正常，参数解析和传递正确，与sage_server.py使用方式一致

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

## 2025-01-25 修复内容总结

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

## 2025-01-25 修复的主要问题

1. **AttributeError**: 'MessageChunk' object has no attribute 'get'
2. **类型不匹配**: List[Dict[str, Any]] vs List[MessageChunk]
3. **content 重复**: 流式消息内容被重复累积
4. **show_content 显示不正确**: 显示内容与实际内容不符

## 2025-01-25 技术要点

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

## 2025-01-21 22:30:00 - 更新README.md文档，添加三个示例的完整介绍

**修改内容：**
- 将README.md从单一CLI工具介绍更新为三个示例的完整指南
- 添加sage_cli.py、sage_demo.py、sage_server.py三个示例的详细功能介绍
- 为每个示例提供完整的使用方法、参数说明和配置示例
- 增加API接口文档、故障排除指南和使用场景说明
- 优化文档结构，提供更好的用户体验和开发指导
- 修正preset_running_config.json描述，移除对外部"agent development"页面的引用

**新增功能说明：**
- CLI工具：命令行交互，支持流式输出和工具调用
- Web界面：基于Streamlit的现代化Web演示应用
- API服务器：基于FastAPI的HTTP服务，支持SSE流式通信

**修改时间：** 2025-01-21 22:30:00

## 2025-01-21 22:19:00 - 修复Streamlit端口参数未使用问题

**问题描述：**
- sage_demo.py中解析了--host和--port参数，但这些参数未被传递给run_web_demo函数
- Streamlit服务器无法使用用户指定的端口和主机配置

**修复内容：**
- 修改run_web_demo函数，添加host和port参数
- 通过环境变量STREAMLIT_SERVER_PORT和STREAMLIT_SERVER_ADDRESS设置Streamlit配置
- 修改main函数，将解析的host和port参数传递给run_web_demo函数
- 添加日志输出显示服务器启动信息

**测试验证：**
- 验证参数解析功能正常，端口参数类型为int
- 确认环境变量设置逻辑正确
- 测试完整的参数传递流程

**修改时间：** 2025-01-21 22:19:00

## 2025-01-21 22:17:00 - 修复preset_available_tools功能

**问题描述：**
- sage_demo.py中preset_available_tools功能无法正常工作
- 配置文件test_config.json中的键名与代码中查找的键名不匹配

**修复内容：**
- 修正test_config.json中的键名从`preset_available_tools`改为`available_tools`
- 确保ComponentManager能够正确读取预设工具配置

**测试验证：**
- 验证ToolProxy正确初始化并过滤工具列表
- 确认preset_available_tools功能正常工作

**修改时间：** 2025-01-21 22:17:00

## 2024-07-30 - 版本更新至0.9.4
- **文件**: `setup.py`, `README.md`, `README_CN.md`
- **更新**: 将项目版本从0.9.3升级到0.9.4
- **修改**: 更新setup.py中的版本号，同步更新英文和中文README文件中的版本徽章
- **作者**: Eric ZZ

## 2024-07-29

- **2024-07-29 10:00 AM**：优化了图表轴显示范围的计算逻辑，新增 `calculate_axis_range` 方法，确保所有图表类型（柱状图、折线图、散点图等）的 X/Y 轴显示范围都能自动适配数据，并留有适当的缓冲区，提升图表可读性。支持数值型、时间型和类目型数据，并统一了轴配置的生成方式。
- **2024-07-29 03:30 PM**：修复了 `file_parser_tool.py` 中PPT文件处理逻辑。现在当遇到 `.ppt` 文件时，系统会尝试调用 `libreoffice` 将其自动转换为 `.pptx` 格式，然后继续提取内容。此举增强了文件解析的兼容性，减少了手动转换的需要。如果 `libreoffice` 未安装或转换失败，将返回相应的错误提示。
