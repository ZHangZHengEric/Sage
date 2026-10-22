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
| Offline RSI demo | Python 3.12+ and repository dependencies; no model key, scripted grades | [First RSI run](FIRST_RSI_RUN.md) |
| Desktop installer | Installer for your OS, bundled Python and backend; Linux also needs GTK and bubblewrap | [Desktop](DESKTOP.md) |
| Desktop from source | Python 3.12+, Flutter, native desktop toolchain | [Source setup](https://github.com/ZHangZHengEric/Sage/blob/main/app/v2/desktop/README.md) |
| Server from source | Python 3.12+, MySQL, Node.js 22.12+ | [Server](WEB.md) |
| Embedded runtime | Python 3.12+ and a model provider | [Python quick start](GETTING_STARTED.md) |

## Run and improve

Desktop provides interactive use, background RSI, and version selection. The Python API supports custom hosts and evaluation bindings. See the [RSI workflow](RSI.md) for inputs, authorized scope, and adoption behavior.

Desktop and Server share SAgents but own separate identity, credentials, settings, and conversation indexes. Desktop does not import v1 data, and legacy startup scripts do not launch the current Server.
