---
layout: default
title: Applications
nav_order: 6
description: "The main user-facing application surfaces in Sage"
---

# Applications

## Which Surface Should You Use

### Example CLI

Use `examples/sage_cli.py` when you need the smallest possible runtime loop for local testing and prompt iteration.

### Streamlit demo

Use `examples/sage_demo.py` when you want a lightweight demo UI without starting the full application server.

### Main server + web UI

Use `app/server/main.py` with `app/server/web/` when you need the primary multi-user application stack:

- authentication
- agent management
- tool and skill administration
- knowledge base integration
- observability endpoints
- browser-based chat experience

### Desktop app

Use `app/desktop/entry.py` and the desktop source tree when you need a packaged local application with a desktop-local backend and UI shell.

## Web Application Structure

- `app/server/main.py`: FastAPI app creation and startup
- `app/server/routers/`: HTTP route groups
- `app/server/services/`: application service layer
- `app/server/web/src/`: Vue application source

The web client contains views for agents, chat, knowledge bases, tools, skills, versions, model providers, and system settings.

## Desktop Application Structure

- `app/desktop/entry.py`: bootstrap and path setup
- `app/desktop/core/main.py`: desktop-local FastAPI service
- `app/desktop/ui/`: frontend UI source
- `app/desktop/scripts/`: build and development scripts

The desktop backend binds to `127.0.0.1` and is intended for local packaged execution.

## Shared Platform Behavior

The server and desktop app both wrap Sage runtime capabilities behind FastAPI applications. They share the same broad platform concepts:

- session-based execution
- agent and tool management
- streaming responses
- skill and MCP integration
- persistent configuration and storage
