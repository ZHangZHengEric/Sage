---
layout: default
title: Overview
nav_order: 1
lang: en
ref: v2-README
permalink: /en/
---

{% include lang_switcher.html %}

# Overview

This documentation covers **SAgents v2**, **Desktop v2**, and **Server v2**, on Python **3.12+**.

| Your goal | Start here |
| --- | --- |
| Run Sage locally | [Desktop v2](applications/DESKTOP.md) |
| Use the multi-user web app | [Server v2](applications/WEB.md) |
| Run an agent from Python | [Quick start](applications/GETTING_STARTED.md) |
| Compose plugins and Agent packages | [Configuration](CONFIGURATION.md) · [Extensions](architecture/PLUGINS.md) |
| Integrate a client | [Python API](api/API_REFERENCE.md) · [HTTP API](api/HTTP_API_REFERENCE.md) |

## Understand the runtime

[Core concepts](CORE_CONCEPTS.md) → [Architecture](architecture/README.md) → [Memory](memory/README.md) → [Tools and MCP](MCP_SERVERS.md).

## Operate and contribute

[Environment variables](ENV_VARS.md) · [Troubleshooting](TROUBLESHOOTING.md) · [Development](DEVELOPMENT.md).

Desktop is a local single-user host. Server is multi-user but currently runs with one worker. Persistence alone does not enable distributed execution.

## Documentation scope

Legacy application guides, proposals, and historical audits are excluded from this site's navigation and search. They remain in the [repository archive](https://github.com/ZHangZHengEric/Sage/blob/main/docs/archive/README.md) for historical reference, not as v2 instructions. The separate `app/wiki` content describes the older product and is not the v2 reference.
