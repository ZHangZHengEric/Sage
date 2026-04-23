---
layout: default
title: User Memory
parent: Memory
nav_order: 2
description: "UserMemoryManager, long-term memory, extraction, and injection"
lang: en
ref: memory-user
---

{% include lang_switcher.html %}

# User Memory

User memory is Sage's long-term memory layer. It stores preferences, requirements, persona, constraints, experience, learning, and skills across sessions.

## Scope

- Unit: user_id
- Contents: preference, requirement, persona, constraint, context, project, workflow, experience, learning, skill, note, bookmark, pattern
- Lifecycle: cross-session and persistable via local files, MCP services, or vector storage

## Runtime Components

- [UserMemoryManager](../../sagents/context/user_memory/manager.py)
- [MemoryType / MemoryEntry](../../sagents/context/user_memory/schemas.py)
- [ToolMemoryDriver](../../sagents/context/user_memory/drivers/tool.py)
- [VectorMemoryDriver](../../sagents/context/user_memory/drivers/vector.py)
- [MemoryExtractor](../../sagents/context/user_memory/extractor.py)

## Key Behavior

- Core APIs: `remember / recall / forget`
- Supports type-based recall
- Auto extraction, deduplication, and updates
- Injects system-level memory into `system_context`

## Why It Is Memory

This is the most classic form of Agent memory. The Agent can remember, recall, and forget actively, so it is a living long-term context layer rather than static reference data.

