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

Sage is an **RSI Agent Harness**, bringing task execution, independent evaluation, and recursive self-improvement into one runtime. These docs explain supported usage, integrations, and operating boundaries.

## Choose your entry point

| Your goal | Start here |
| --- | --- |
| Understand how RSI improves a Package | [RSI workflow](applications/RSI.md) |
| Inspect an iteration without a model key | [First RSI run](applications/FIRST_RSI_RUN.md) |
| Install Desktop and use RSI | [Desktop](applications/DESKTOP.md) |
| Embed Sage in a Python application | [Quick start](applications/GETTING_STARTED.md) · [Host development](architecture/sagents-host-development.md) |
| Provide a multi-user web service | [Server](applications/WEB.md) |
| Configure models, tools, and Skills | [Configuration](CONFIGURATION.md) · [Tools and MCP](MCP_SERVERS.md) |
| Integrate an existing client | [Python API](api/API_REFERENCE.md) · [HTTP API](api/HTTP_API_REFERENCE.md) |

## Understand and extend the Harness

[Core concepts](CORE_CONCEPTS.md) · [Architecture](architecture/README.md) · [Plugins](architecture/PLUGINS.md) · [Memory](memory/README.md) · [Support boundaries](architecture/support-boundaries.md).

## Operate and contribute

[Environment variables](ENV_VARS.md) · [Troubleshooting](TROUBLESHOOTING.md) · [Development](DEVELOPMENT.md).

Running from source requires Python **3.12+**. Desktop installers bundle the backend; Server currently supports one worker.

## Documentation scope

This site maintains Sage product, SDK, protocol, and operating references. Legacy usage is covered by [Sage v1](https://github.com/ZHangZHengEric/Sage/blob/main/app/v1/README.md) and the [legacy reference directory](https://github.com/ZHangZHengEric/Sage/blob/main/docs/archive/README.md). Customer delivery proposals, temporary audits, and phase-specific validation notes are not retained as repository documentation.
