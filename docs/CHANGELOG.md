---
layout: default
title: Changelog
nav_order: 90
description: "Sage Examples and Server Changelog"
---

# Sage Examples Changelog

## 2026-02-03 - Frontend UI Refactoring and Feature Enhancements

**Changes:**
- **Frontend UI Refactoring**:
  - Comprehensively optimized interface design to improve user experience.
  - Added mobile responsiveness support to ensure good display effects on mobile devices.
- **Management Feature Enhancements**:
  - **User List**: Added a user management page visible only to administrators, supporting user viewing and management.
  - **System Settings**: Added a system settings page, providing richer system configuration options.

**Modification Time:** 2026-02-03

## 2026-01-31 - Memory Configuration Logic Update

**Changes:**
- **Configuration Parameter Update**:
  - Replaced `memory_root` parameter with `memory_type` (session | user).
  - `memory_root` parameter is deprecated but backward compatibility is maintained (automatically sets `MEMORY_ROOT_PATH` environment variable).
- **Environment Variable Support**:
  - Added `MEMORY_ROOT_PATH` environment variable to specify user memory storage path.
  - Default path logic: If environment variable is not set, use `user_memory` directory under workspace.
- **Component Updates**:
  - Updated `sage_cli.py`, `sage_demo.py`, `sage_server.py` to support the new memory configuration logic.

**Modification Time:** 2026-01-31

## 2026-01-25 - Support Defining Tools with Annotations

**Changes:**
- **Tool Development Optimization**:
  - Support defining internal tools using `@sage_mcp_tool` annotation, automatically handling Schema generation and tool registration.
  - Recommended using the annotation approach instead of traditional class inheritance to simplify the development process.
- **Documentation Update**:
  - Updated `TOOL_DEVELOPMENT_CN.md` and `TOOL_DEVELOPMENT.md` with detailed guides and examples for defining tools with annotations.

**Modification Time:** 2026-01-25

## 2026-01-25 - Add Observability Trace and Enhanced Features

**Changes:**
- **Add Observability Trace**: Enhance system observability with trace tracking and performance monitoring.
- **Server Enhancements**:
  - Add Multi-LLM Agent Pool support to improve model invocation flexibility and reliability.
- **Core Features Expansion**:
  - Add Skill function to extend agent capability boundaries.
  - Add Memory function supporting long/short-term memory management for better context coherence.
- **Testing Tools**:
  - Add stress test scripts for evaluating system performance under high concurrency.

**Modification Time:** 2026-01-25

## 2026-01-09 14:45:00 - Update Sage Server Deployment Docs and Build Scripts

**Changes:**
- **Update README_SERVER.md**:
  - Supplement local source deployment guide (non-containerized startup method)
  - Complete the comparison table of environment variables and command line arguments configuration
  - Fix port mapping in Docker run examples
- **Refactor Server for Modular Startup**:
  - Modify `app/server/docker/Dockerfile` to use `python -m app.server.main` startup to resolve relative import issues
  - Modify `app/build_exec/build_server.py` to generate temporary entry scripts to support modular packaging

**Modification Time:** 2026-01-09 14:45:00

## 2025-12-30 12:00:00 - Add Web Frontend and Server Backend Services

**Changes:**
- **Add Web Frontend Service (`app/web/`)**:
  - Modern Web Interface built with Vue 3 + Vite
  - Provides visual operations for Agent configuration, chat interaction, knowledge base management, MCP server management, etc.
  - Supports Docker containerized deployment
- **Add Server Backend Service (`app/server/`)**:
  - Agent streaming service based on Sage framework, providing HTTP API and SSE real-time communication
  - Supports multiple LLM model configurations, MCP (Model Context Protocol) service integration
  - Provides complete Docker deployment support, including workspace, log mounting, and detailed parameter configuration capabilities

**Modification Time:** 2025-12-30 12:00:00

## 2025-09-21 21:11:00 - Fix sage_demo.py MCP Tool Discovery Function

**Issue**: `_init_tool_manager` method in sage_demo.py lacks MCP tool discovery logic, causing MCP tools to fail registration.

**Fix**:
1. Changed `_init_tool_manager` method to async, added complete MCP tool discovery flow.
2. Added `_auto_discover_tools()` call for basic tool discovery.
3. Added `_discover_mcp_tools()` async call for MCP tool discovery.
4. Changed `initialize` method to async, used `asyncio.run()` to call in Streamlit.
5. Added asyncio import to support async operations.

**Test Results**: MCP tool discovery function works normally, 23 tools successfully registered, environment variables set correctly, application starts normally.

## 2025-09-21 21:07:00 - Fix sage_demo.py Unused Parameters Issue

**Issue**: `mcp_config` and `preset_running_config` parameters in sage_demo.py were not used.

**Fix**:
1. Added `mcp_config` environment variable setting logic in `_init_tool_manager` method.
2. Added `preset_running_config` configuration reading and `system_prefix` passing logic in `__init__` method.
3. Added `system_prefix` and `memory_type` parameter passing in `_init_controller` method.

**Test Results**: Function works normally, parameters parsed and passed correctly, consistent with sage_server.py usage.

## 2025-01-27 16:45 - Add CLI Command Line Usage Introduction
- **Files**: `README.md`, `README_CN.md`
- **New**: Detailed usage introduction for sage_cli.py command line tool, including basic usage, advanced options, and functional features.
- **Guidance**: Added link to examples/README.md for detailed CLI usage documentation.
- **Author**: Eric ZZ

## 2025-01-27 16:30 - Sync Chinese README with All Function Updates
- **Files**: `README_CN.md`
- **Sync**: Synced all updates from English README to Chinese version, ensuring content alignment.
- **Update**: Chinese introduction for all new features like Multi-Agent Collaboration v0.9.3, Built-in MCP Server, Custom Agent Development, AgentFlow Orchestration, etc.
- **Author**: Eric ZZ

## 2025-01-27 16:00 - Add Custom Agent and AgentFlow Function Introduction
- **Files**: `README.md`
- **New**: Detailed explanation of Custom Agent Development Framework, AgentFlow Orchestration Function, and Agent-to-Tool Mechanism.
- **Improvement**: Included complete code examples for Custom Agent Development Guide, updated v0.9.3 new feature list.
- **Author**: Eric ZZ

## 2025-01-27 15:30 - Supplement Missing README Function Introductions
- **Files**: `README.md`
- **New**: Streamable HTTP MCP connection method, 13 professional agent types, MCP connection type comparison table.
- **Improvement**: Explanations for MCP security features, API key authentication, connection verification, etc., updated v0.9.3 new features.
- **Author**: Eric ZZ

## 2025-01-27 15:00 - Update README Function Introduction
- **Files**: `README.md`
- **Update**: Added introduction for new features like Built-in MCP Server, Advanced File System Operations, Security Features.
- **New**: Detailed explanation for File Parser, Command Execution, Web Search MCP Servers, updated v0.9.3 feature list.
- **Author**: Eric ZZ

## 2025-01-27 14:30 - Version Update to 0.9.3
- **Files**: `setup.py`, `README.md`, `README_CN.md`
- **Update**: Upgraded project version from 0.9.2 to 0.9.3.
- **Modification**: Updated version number in setup.py, synced version badges in English and Chinese README files.
- **Author**: Eric ZZ

## 2025-01-25 16:50 - Optimize File Content Search Function
- **Files**: `sagents/tool/file_system_tool.py`
- **Optimization**: Improved search_content_in_file function to search characters in the entire file content instead of splitting by lines, removed line number and line content return.
- **Features**: Precise search based on character position, smart merging of overlapping contexts, sorting by matched keyword count and position.
- **Author**: Eric ZZ

## 2025-01-25 16:45 - Complete File Content Search Function Implementation
- **Files**: `sagents/tool/file_system_tool.py`
- **Function**: Completed implementation of search_content_in_file function, supporting multi-keyword search, scoring sort, and context extraction.
- **Features**: Scoring by keyword match count, supporting custom context size and result quantity, including detailed execution logs and error handling.
- **Author**: Eric ZZ

## 2025-01-25 14:30 - Fix Streaming Response Merge Type Error
- **Files**: `sagents/utils/stream_format.py`
- **Issue**: ChatCompletion choices field type error, causing "Cannot instantiate typing.Union" error.
- **Fix**: Imported Choice type, changed choices field from dict to Choice object instantiation, and fixed ChatCompletionMessageToolCall type field to "function".
- **Impact**: Fixed TaskExecutorAgent streaming response merge failure issue.

## 2025-01-25 Fix Content Summary

### 1. Type Annotation Unification (message_manager.py, executor_agent.py)
- Changed type annotations for relevant methods and parameters from `List[Dict[str, Any]]` to `List[MessageChunk]`.
- Ensured type consistency to avoid AttributeError.

### 2. MessageChunk Object Attribute Access Unification (sage_demo.py)
- Unified attribute access using dot notation (e.g., `chunk.content`) instead of dict access (e.g., `chunk['content']`).
- Fixed all relevant attribute access methods.

### 3. session_id Access Method Unification (sagents/agent/ directory)
- Unified `session_id` access method in all files under `sagents/agent/`.
- Changed from dict access `session['session_id']` to direct access `session.session_id`.

### 4. Remove Unused Code (message_manager.py)
- Removed `self.pending_chunks` attribute initialization.
- Removed `_filter_default_strategy` method.
- Removed reference to `self.pending_chunks` in `clear_messages` method.

### 5. Fix Content Duplication in planning_agent.py
- Modified `show_content` assignment in `_execute_streaming_planning` method.
- Changed from `delta_content_all` to `delta_content_char`, ensuring content yielded each time is not duplicated.

### 6. Re-optimize add_messages Method in message_manager.py
- **First Fix**: Added check for `is_final` attribute, replacing content if `is_final=True`, otherwise appending.
- **Second Optimization**: Removed check for `message.is_final` based on user feedback.
- **Final Optimization**: Simplified logic, directly appending incremental content for streaming messages, removing unnecessary attribute updates.
- Solved `content` and `show_content` duplication issues.
- Streaming messages feature incremental content delivery, requiring no complex judgment logic.

## 2025-01-25 Major Issues Fixed

1. **AttributeError**: 'MessageChunk' object has no attribute 'get'
2. **Type Mismatch**: List[Dict[str, Any]] vs List[MessageChunk]
3. **Content Duplication**: Streaming message content repeatedly accumulated
4. **Incorrect show_content Display**: Displayed content did not match actual content

## 2025-01-25 Technical Highlights

- MessageChunk is a dataclass object, should use attribute access instead of dict access.
- Streaming message processing requires correct handling of incremental content accumulation.
- Type annotation consistency is crucial for avoiding runtime errors.
- Simplified logic is easier to maintain and understand.

## 2025-01-25
### Fix Message Duplication Issue
- **Files**: `sagents/agent/message_manager.py`
- **Method**: `add_messages`
- **Issue**: Message content added repeatedly.
- **Fix**: When processing messages, check `is_chunk` attribute of `MessageChunk` to decide whether to append or replace content, avoiding duplication.
- **Impact**: Solved message duplication issue in MessageManager.

### Fix Repeated Serialization Issue During Session State Saving
- **Files**: `sagents/agent/agent_controller.py`
- **Method**: `_save_session_state`
- **Issue**: `MessageChunk` objects repeatedly serialized causing incorrect data structure.
- **Fix**: Removed call to `_convert_message_chunks_to_dicts` method since `MessageManager.to_dict()` already handles `MessageChunk` object conversion.
- **Impact**: Avoided data issues caused by repeated serialization.

### Fix MessageManager Repeated Retrieval Issue After Task Analysis Phase
- **Files**: `sagents/agent/agent_controller.py`
- **Method**: `run_stream`
- **Issue**: After task analysis phase, code re-retrieved `message_manager` from `_session_managers`, causing message content duplication.
- **Fix**: Removed unnecessary `message_manager` reassignment, directly using passed parameter instance.
- **Impact**: Solved message duplication display issue after task analysis phase.

## 2025-01-25 (Afternoon)

### Fix Agent Message Duplication Issue
- **Time**: 2025-01-25 16:30
- **Issue**: All agents repeatedly called `message_manager.add_messages` in `run_stream` method, causing messages to be added to MessageManager repeatedly.
- **Fix Plan**: 
  1. Modified `_collect_and_log_stream_output` method in `agent_base.py` to add `message_manager` and `agent_name` parameters, unifying message addition handling.
  2. Updated `run_stream` method in all agents to pass necessary parameters when calling `_collect_and_log_stream_output`.
  3. Deleted repeated `message_manager.add_messages` calls in each agent.
- **Fixed Files**: `agent_base.py`, `task_analysis_agent.py`, `task_decompose_agent.py`, `observation_agent.py`, `direct_executor_agent.py`, `executor_agent.py`, `task_summary_agent.py`, `inquiry_agent.py`, `planning_agent.py`
- **Impact**: Avoided message duplication, unified message management logic, simplified code maintenance.

### Fix Message Duplication Caused by yield from in TaskAnalysisAgent
- **Time**: 2025-01-25 16:35
- **Files**: `task_analysis_agent.py`
- **Issue**: Using `yield from` in `_execute_streaming_analysis` method directly passed messages, causing them to be processed repeatedly by `_collect_and_log_stream_output`.
- **Fix**: Changed `yield from` to `for...yield` loop, ensuring message stream is passed correctly.
- **Impact**: Solved message duplication display issue in TaskAnalysisAgent.

## 2025-01-21 22:30:00 - Update README.md, Add Complete Introduction for Three Examples

**Changes:**
- Updated README.md from single CLI tool introduction to complete guide for three examples.
- Added detailed function introductions for sage_cli.py, sage_demo.py, sage_server.py.
- Provided complete usage methods, parameter descriptions, and configuration examples for each example.
- Added API interface documentation, troubleshooting guide, and usage scenario descriptions.
- Optimized document structure for better user experience and development guidance.
- Fixed preset_running_config.json description, removed reference to external "agent development" page.

**New Features:**
- CLI Tool: Command line interaction, supporting streaming output and tool calling.
- Web Interface: Modern Web demo application based on Streamlit.
- API Server: HTTP service based on FastAPI, supporting SSE streaming communication.

**Modification Time:** 2025-01-21 22:30:00

## 2025-01-21 22:19:00 - Fix Streamlit Port Parameter Not Used Issue

**Issue Description:**
- sage_demo.py parsed --host and --port parameters, but these were not passed to run_web_demo function.
- Streamlit server could not use user-specified port and host configuration.

**Fix Content:**
- Modified run_web_demo function, added host and port parameters.
- Set Streamlit configuration via environment variables STREAMLIT_SERVER_PORT and STREAMLIT_SERVER_ADDRESS.
- Modified main function to pass parsed host and port parameters to run_web_demo function.
- Added log output to show server startup information.

**Test Verification:**
- Verified parameter parsing function normal, port parameter type is int.
- Confirmed environment variable setting logic correct.
- Tested complete parameter passing flow.

**Modification Time:** 2025-01-21 22:19:00

## 2025-01-21 22:17:00 - Fix preset_available_tools Function

**Issue Description:**
- preset_available_tools function in sage_demo.py did not work properly.
- Key name in configuration file test_config.json did not match key name looked up in code.

**Fix Content:**
- Corrected key name in test_config.json from `preset_available_tools` to `available_tools`.
- Ensured ComponentManager can correctly read preset tool configuration.

**Test Verification:**
- Verified ToolProxy initialized correctly and filtered tool list.
- Confirmed preset_available_tools function works normally.

**Modification Time:** 2025-01-21 22:17:00

## 2024-07-30 - Version Update to 0.9.4
- **Files**: `setup.py`, `README.md`, `README_CN.md`
- **Update**: Upgraded project version from 0.9.3 to 0.9.4.
- **Modification**: Updated version number in setup.py, synced version badges in English and Chinese README files.
- **Author**: Eric ZZ

## 2024-07-29

- **2024-07-29 10:00 AM**: Optimized chart axis display range calculation logic, added `calculate_axis_range` method, ensuring X/Y axis display ranges for all chart types (bar, line, scatter, etc.) automatically adapt to data with appropriate buffers, improving chart readability. Supports numeric, temporal, and categorical data, unified axis configuration generation.
- **2024-07-29 03:30 PM**: Fixed PPT file processing logic in `file_parser_tool.py`. Now when encountering `.ppt` files, the system attempts to call `libreoffice` to automatically convert them to `.pptx` format before extracting content. This enhances file parsing compatibility, reducing the need for manual conversion. Returns corresponding error prompt if `libreoffice` is not installed or conversion fails.
