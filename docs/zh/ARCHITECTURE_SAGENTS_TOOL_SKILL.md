---
layout: default
title: 工具与技能系统
parent: 架构
nav_order: 7
description: "ToolManager / ToolProxy、内置工具、MCP 代理、SkillManager / SkillProxy 与沙箱内技能"
lang: zh
ref: architecture-sagents-tool-skill
---

{% include lang_switcher.html %}

# 工具与技能系统

`sagents/tool/` 与 `sagents/skill/` 是“能力层”：决定一次会话里 Agent 可以调用什么、技能包是怎么被加载和执行的。

## 1. 工具系统 `sagents/tool/`

### 1.1 模块组成

```mermaid
flowchart TB
    subgraph 注册
        TBase[tool_base · @tool 装饰器 + _DISCOVERED_TOOLS]
        MBase[mcp_tool_base · _DISCOVERED_MCP_TOOLS]
        Schema[tool_schema · ToolSpec / OpenAI 函数调用 schema]
    end

    subgraph 运行时
        TM[ToolManager · 全局工具管理器]
        TP[ToolProxy · 会话级白名单]
        MP[mcp_proxy · 与 MCP Server 的代理]
        Impl[impl/ · 内置工具实现]
    end

    TBase -.收集.-> TM
    MBase -.收集.-> TM
    TM --> Impl
    TM --> MP
    Schema -.转换.-> TM
    TP --> TM
```

### 1.2 工具的两类来源

```mermaid
flowchart LR
    Agent --> TP[ToolProxy]
    TP --> TM[ToolManager]
    TM -->|本地| Impl[tool/impl/*]
    TM -->|MCP| MCPProxy[mcp_proxy]
    MCPProxy --> Stdio[stdio MCP Server]
    MCPProxy --> SSE[SSE MCP Server]
    MCPProxy --> HTTP[Streamable HTTP MCP]
    Impl --> Sandbox
```

无论本地工具还是 MCP 工具，对 Agent 都长得一样。`ToolManager` 把它们统一登记，再按调用名字派发。

### 1.3 ToolManager 的关键能力

```mermaid
flowchart TB
    Start[启动期] --> Scan[扫描已注册工具<br/>本地 @tool + MCP]
    Run[运行期] --> Call[run_tool name + args + SessionContext]
    Call --> Exec[本地实现 / MCP 远端]
    Exec --> Trunc[结果按 token 截断<br/>MAX_TOOL_RESULT_TOKENS=12000]
    Trunc --> ToAgent[返回 tool_message]
    Run --> Meta[list_all_tools_name / get_tool_spec]
```

ToolManager 通常是进程级单例，由 `app/server/lifecycle.py`（或桌面端等价物）在启动期初始化。

### 1.4 ToolProxy：会话级白名单

```mermaid
flowchart LR
    Caller[服务端构造请求] --> Pick[按用户/Agent 权限选 available_tools]
    Pick --> TP[ToolProxy<br/>tool_managers + available_tools]
    TP --> Filter[白名单过滤 + 优先级排序]
    TP --> Warn[白名单不存在的工具打 warning]
    TP --> SAgent[SAgent.run_stream tool_manager=TP]
```

`ToolProxy` 接受多个 `ToolManager`（按列表顺序优先级递减），并兼容 `ToolManager` 的接口，所以 Agent 不需要区分。

### 1.5 内置工具 `tool/impl/`

```mermaid
flowchart TB
    subgraph 命令与文件
        Cmd[execute_command_tool]
        FS[file_system_tool]
    end
    subgraph 网络与多模态
        Web[web_fetcher_tool]
        Img[image_understanding_tool]
    end
    subgraph 上下文管理
        Compress[compress_history_tool]
        TodoT[todo_tool · 多智能体任务清单]
    end
    subgraph 用户交互
        Quest[questionnaire_tool · 结构化问卷]
    end
    subgraph 记忆
        Mem[memory_tool]
        MIdx[memory_index]
    end

    Cmd --> Sandbox
    FS --> Sandbox
    Web --> Sandbox
```

它们的执行最终都要落到 `Sandbox` 抽象上（详见 [Sandbox/LLM/Obs](ARCHITECTURE_SAGENTS_SANDBOX_OBS.md)）。

### 1.6 MCP 集成

```mermaid
flowchart LR
    MCPServer[(任意 MCP Server)] --> Conn{连接方式}
    Conn -->|stdio| Stdio[StdioServerParameters]
    Conn -->|HTTP+SSE| SSE[SseServerParameters]
    Conn -->|Streamable HTTP| HTTP[StreamableHttpServerParameters]
    Stdio --> MP[mcp_proxy]
    SSE --> MP
    HTTP --> MP
    MP --> Convert[把 MCP Tool 转成 OpenAI 函数调用 schema]
    Convert --> TM
    MP --> Health[连接生命周期 / 超时 / 健康检查]
```

仓库内置的 `mcp_servers/` 也是同样的方式接入。

## 2. 技能系统 `sagents/skill/`

“工具”是函数级能力，“技能”是更大粒度的工作流：一个目录、一份说明、可能配套脚本与示例资源。

### 2.1 模块组成

```mermaid
flowchart TB
    subgraph 宿主侧
        Schema[SkillSchema · 元数据]
        SM[SkillManager · 扫描/注册/加载]
        SP[SkillProxy · 会话级白名单]
    end

    subgraph 沙箱侧
        SSM[SandboxSkillManager · 复制/投影到沙箱]
    end

    subgraph 暴露给 Agent
        STool[skill_tool · 把技能包装成工具]
    end

    SM --> Schema
    SM --> SP
    SP --> SSM
    SSM --> STool
```

### 2.2 数据流

```mermaid
flowchart LR
    Disk[(技能目录)] --> SM
    SM --> Reg[(SkillSchema 注册表)]
    Caller[一次请求] --> Pick[按 Agent 权限选 available_skills]
    Pick --> SP[SkillProxy]
    SP --> SC[SessionContext.init_more]
    SC --> SSM[SandboxSkillManager]
    SSM --> Sandbox[(沙箱内固定路径)]
    Sandbox --> Use[沙箱里的工具/脚本读写技能资源]
```

`SkillManager` 不负责把技能拷贝到沙箱——那是 `SandboxSkillManager` 的职责。这种解耦让 remote 沙箱场景也能正常用技能。

### 2.3 技能 → 工具

```mermaid
flowchart LR
    Skill[一个技能包] --> MD[SKILL.md 说明]
    Skill --> Assets[脚本 / 资源文件]
    MD -->|注入| SysPrompt[system prompt 合适位置]
    Skill -->|可注册| ST[skill_tool]
    ST --> TM[ToolManager]
    SysPrompt --> LLM
    TM --> LLM
```

技能既能通过说明影响模型行为，也能直接以工具的形式被 LLM 通过 function call 调用。

## 3. 推荐 / 选择策略

```mermaid
flowchart LR
    AllTools[(全部工具)] --> ToolSug[tool_suggestion Agent]
    AllWFs[(全部 workflow)] --> WfSel[workflow_select Agent]
    ToolSug -->|本次该用什么| LLM
    WfSel -->|本次该走哪条| LLM
```

工具/技能层负责“有什么”，建议 Agent 负责“这次用什么”。这样不用一次把全部 schema 塞进上下文。

## 4. 启动期 vs 运行期

```mermaid
flowchart TD
    Bootstrap[app 启动] --> ToolMgr[ToolManager 单例]
    Bootstrap --> SkillMgr[SkillManager 单例]
    Request[一次请求] --> Build[构造 ToolProxy + SkillProxy]
    Build --> SAgent[SAgent.run_stream]
    SAgent --> Sess[Session/SessionContext]
    Sess --> SSM[SandboxSkillManager 投影到沙箱]
    Sess --> Agents
    Agents --> Tools[ToolProxy.run_tool]
```

## 5. 二次开发：自定义工具 / MCP / 技能

Sage 的扩展点几乎都在这两层。三种最常用的“给 Agent 加能力”的方式互不冲突。

### 5.1 写一个本地工具

```python
# my_pkg/my_tools.py
from sagents.tool.tool_base import tool

@tool(
    name="get_weather",
    description="按城市名查询天气",
)
async def get_weather(city: str) -> dict:
    """返回 dict 即可，框架自动序列化为 tool_message。"""
    return {"city": city, "temp_c": 23, "condition": "sunny"}
```

只要这个模块被 import 到进程里（例如在 `app/server/bootstrap.py` 的工具初始化阶段 import），它就会被 `ToolManager` 自动收集。

### 5.2 接入一个 MCP Server

```python
from mcp import StdioServerParameters
from sagents.tool.tool_schema import SseServerParameters, StreamableHttpServerParameters

# 三种连接方式按需选一种：
stdio_cfg = StdioServerParameters(command="my-mcp", args=["--stdio"])
sse_cfg = SseServerParameters(url="https://mcp.example.com/sse")
http_cfg = StreamableHttpServerParameters(url="https://mcp.example.com/mcp")

# 通过 ToolManager 提供的注册接口加入（具体 API 看当前 tool_manager.py）
tool_manager.register_mcp_server(name="my_mcp", params=stdio_cfg)
```

注册后，该 MCP Server 暴露的所有工具会被自动转成 OpenAI 函数调用 schema，并和本地工具同等对待。

### 5.3 写一个技能包

技能就是一个目录，按约定包含：

```text
my_skill/
├── SKILL.md          # 必需，人类可读的“怎么用”说明，会注入 LLM
├── skill.yaml        # 可选元数据：id / name / description / 激活场景
├── scripts/          # 可选脚本，可在沙箱里执行
└── assets/           # 可选静态资源
```

`SKILL.md` 的开头一般写：

```markdown
# Skill: My Skill

## 用途
描述这个技能解决什么问题，什么时候该用它。

## 步骤
1. ...
2. ...

## 注意事项
- ...
```

把这个目录所在的根目录注册给 SkillManager 即可：

```python
from sagents.skill import SkillManager

skill_manager = SkillManager()
skill_manager.add_skill_dir("/path/to/skills_root")
```

之后通过 `SkillProxy(skill_manager, available_skills=["my_skill"])` 限定本次会话能看到的技能子集，再传给 `SAgent.run_stream`。
