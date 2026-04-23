---
layout: default
title: Session Memory
parent: Memory
nav_order: 1
description: "SessionMemoryManager and historical message retrieval strategies"
lang: en
ref: memory-session
---

{% include lang_switcher.html %}

# Session Memory

Session memory is Sage's short-term memory layer. It manages message history organization, compression, and retrieval within a single session.

## Scope

- Unit: one session
- Contents: historical messages, turns, compression results
- Lifecycle: lives with the session; not persisted as long-term memory

## Runtime Components

- [SessionMemoryManager](../../sagents/context/session_memory/session_memory_manager.py)
- `MessageManager`
- `ContextBudgetManager`

## Key Behavior

- Uses BM25 by default for history retrieval
- Supports `messages` and `grouped_chat` strategies
- Selectively stitches history into prompts before LLM calls

## Why It Is Memory

Session memory is the short-term context the Agent actively uses. It decides what to keep, what to compress, and what to recall during the current conversation.

