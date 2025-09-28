# Sage Examples 修改日志

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