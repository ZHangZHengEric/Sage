---
layout: default
title: Applications
nav_order: 2
lang: en
ref: v2-applications-README
has_children: true
---

{% include lang_switcher.html %}

# Applications

| Entry point | Requirements | Guide |
| --- | --- | --- |
| Desktop v2 | Python 3.12+, Flutter, native desktop toolchain | [Desktop](DESKTOP.md) |
| Server v2 | Python 3.12+, MySQL, Node.js 22.12+ | [Server](WEB.md) |
| Embedded runtime | Python 3.12+ and a model provider | [Python quick start](GETTING_STARTED.md) |

Desktop and Server share SAgents v2 but own separate identity, credentials, settings, and conversation indexes. Desktop v2 does not import v1 data. The legacy `scripts/dev-up.sh` does not start Server v2.
