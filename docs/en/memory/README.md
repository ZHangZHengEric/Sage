---
layout: default
title: Memory
nav_order: 8
has_children: true
description: "Documents related to session memory, user memory, workspace memory, and memory search"
lang: en
ref: memory
---

{% include lang_switcher.html %}

# Memory

This section collects the Sage memory system docs. In Sage, memory is broader than user memory: it also includes session history, Agent workspace files, and `search_memory`-based workspace retrieval.

## Architecture

```mermaid
flowchart TB
    A[Conversation / files / experience] --> B[Session Memory<br/>short-term history]
    A --> C[User Memory<br/>long-term memory]
    A --> D[Agent Workspace<br/>workspace files / task files / MEMORY.md]
    C --> E[Memory Extraction<br/>auto extract & dedupe]
    D --> F[search_memory<br/>workspace retrieval]
    B --> G[SessionContext]
    C --> G
    D --> G
    E --> G
    F --> G
```

## What This Folder Contains

- Session memory: short-term conversation history and compression
- User memory: cross-session long-term memory and extraction
- Workspace memory: Agent workspace files, notes, and task outputs
- Memory search: `search_memory`-based workspace retrieval and validation

## Current Documents

1. [Session Memory](SESSION_MEMORY.md)
2. [User Memory](USER_MEMORY.md)
3. [Workspace Memory](WORKSPACE_MEMORY.md)
4. [Memory Search Validation](memory-search/README.md)
