---
layout: default
title: MCP Servers
nav_order: 6
description: "Built-in MCP servers in the Sage repository"
lang: en
ref: mcp-servers
---

{% include lang_switcher.html %}

# MCP Servers

## Overview

The repository includes built-in MCP server implementations under `mcp_servers/`. These are part of Sage's extension model and can be surfaced through the tool system.

## Included Servers

### Search

`mcp_servers/search/`

Provides unified search capability with multiple provider backends such as Tavily, Brave, Serper, SerpAPI, and others.

### Image generation

`mcp_servers/image_generation/`

Provides unified image generation with provider adapters.

### Task scheduler

`mcp_servers/task_scheduler/`

Provides scheduled task execution and persistence backed by a local database path derived from `SAGE_ROOT`.

### IM server

`mcp_servers/im_server/`

Provides messaging-channel integration and provider-specific implementations for systems such as Feishu, DingTalk, iMessage, WeChat Work, and related channel adapters.

## How MCP Fits the Runtime

At the runtime level, MCP support is exposed through the tool subsystem:

- `sagents/tool/mcp_proxy.py`
- `sagents/tool/mcp_tool_base.py`
- `sagents/tool/tool_manager.py`

The intent is to make external or hosted capabilities look like tool invocations available to an agent session.

## Operational Note

Some MCP servers require provider credentials, external services, or additional environment setup. Treat `mcp_servers/` as the implementation layer; deployment policy should live with the specific app surface that hosts them.
