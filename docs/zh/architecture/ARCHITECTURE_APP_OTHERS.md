---
layout: default
title: CLI、示例与外部入口架构
parent: 架构
nav_order: 3
description: "app/cli/、examples/、app/chrome-extension/、app/wiki/ 等轻量入口"
lang: zh
ref: architecture-app-others
---

{% include lang_switcher.html %}

# CLI、示例与外部入口架构

除了 `app/server/` 和 `app/desktop/` 这两个完整产品形态外，Sage 还提供若干更轻量的入口，分别面向不同场景：开发调试、最小演示、第三方集成、文档/Wiki。

## 入口全景

```mermaid
flowchart TD
    User((用户)) --> CLI[app/cli<br/>sage 命令]
    User --> Demo1[examples/sage_cli.py]
    User --> Demo2[examples/sage_demo.py<br/>Streamlit]
    User --> Demo3[examples/sage_server.py<br/>独立 FastAPI]
    User --> Browser[(浏览器)]
    User --> Reader[文档读者]

    Browser --> Ext[app/chrome-extension<br/>侧边栏插件]
    Browser --> Wiki[app/wiki<br/>静态站点]

    CLI --> SAgent
    Demo1 --> SAgent
    Demo2 --> SAgent
    Demo3 --> SAgent
    Ext -->|HTTP/SSE| Server[app/server<br/>已部署]
    Wiki -. 纯静态 .-> Browser
```

## CLI：`app/cli/`

```mermaid
flowchart LR
    User -->|sage run / chat / doctor| Argparse[main.py · argparse]
    Argparse --> Service[service.py<br/>会话调度]
    Service --> SAgent[sagents 运行时]
    Service --> LocalFS[(本地会话文件)]
```

特点：

- 直接复用 `sagents/` 运行时，不依赖 `app/server/`。
- 适合本地开发、提示词迭代、运行时诊断。
- `sage doctor` 用于排查环境问题（依赖、模型连通性、沙箱）。

详细命令请见 [CLI 使用指南](CLI.md)。

## Examples：`examples/`

```mermaid
flowchart TB
    subgraph G_Ex ["examples/"]
        SCli[sage_cli.py<br/>极简 CLI]
        SDemo[sage_demo.py<br/>Streamlit 演示]
        SSrv[sage_server.py<br/>独立 FastAPI 示例]
        Helper[_example_support.py]
        Mcp[mcp_setting.json<br/>演示用 MCP 配置]
        Cfg1[preset_running_agent_config.json]
        Cfg2[preset_running_config.json]
        Build[build_exec/<br/>单文件构建示例]
    end

    SCli --> SAgent
    SDemo --> SAgent
    SSrv --> SAgent
    SCli -.读.-> Helper
    SDemo -.读.-> Helper
    SSrv -.读.-> Helper
    SCli -.读.-> Mcp
    SCli -.读.-> Cfg1
    SCli -.读.-> Cfg2
```

什么时候用：

- 验证“最少需要哪些参数才能跑通 sagents”。
- 快速做一个不依赖完整服务端的演示。
- 需要一个最小 PyInstaller 构建样本。

什么时候不用：要做完整产品功能（多用户、知识库、可观测性 UI），请用 `app/server/` 而不是 `examples/`。

## Chrome 扩展：`app/chrome-extension/`

```mermaid
flowchart LR
    Web[(浏览网页)] --> ContentScript[content-script.js<br/>注入页面]
    Web --> SidePanel[sidepanel.html<br/>侧边栏 UI]
    SidePanel --> SidePanelJS[sidepanel.js]
    ContentScript --> SW[service-worker.js<br/>后台]
    SidePanelJS --> SW
    SW -->|HTTP/SSE| Server[app/server<br/>已部署]
```

它本身不嵌入 sagents 运行时，而是作为浏览器侧的 UI 客户端，通过 HTTP/SSE 调用部署在某处的 `app/server/`。等价于一个“住在浏览器侧边栏里的 Web 客户端”。

## Wiki / 静态文档：`app/wiki/`

```mermaid
flowchart LR
    SrcMd[Markdown 业务内容] --> Gen[generate-docs.js]
    Gen --> Site[静态站点产物]
    Site --> ServeUser[(浏览器读者)]
```

`app/wiki/` 是面向产品/运营的内部 Wiki 站点，与本套 `docs/` 的定位不同：

- `docs/`（你正在看的）：技术文档，绑定当前代码库。
- `app/wiki/`：业务/产品/教程类内容，可独立出站。

它不参与运行时，但属于仓库中的“应用”之一，所以放在这一章。

## 总结：什么时候选哪种入口

```mermaid
flowchart TD
    Need[需求]
    Need --> P1{完整多用户<br/>Web 产品?} -->|是| Server[app/server + web]
    Need --> P2{单机 / 离线?} -->|是| Desktop[app/desktop]
    Need --> P3{命令行 / 脚本?} -->|是| CLI[app/cli]
    Need --> P4{最小演示 / 集成模板?} -->|是| Examples[examples/sage_*.py]
    Need --> P5{浏览器侧入口?} -->|是| Ext[app/chrome-extension]
    Need --> P6{产品/教程内容?} -->|是| Wiki[app/wiki]
```
