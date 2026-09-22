---
layout: default
title: Troubleshooting
nav_order: 11
lang: en
ref: v2-TROUBLESHOOTING
---

{% include lang_switcher.html %}

# Troubleshooting

| Symptom | Check |
| --- | --- |
| v2 import or sidecar fails on Python | Use Python 3.12+; confirm the repository `.venv` points to it. |
| YAML text is treated as a filename | Parse it with `SageManifestLoader().loads(text)` before `build()`. |
| Manifest rejected | Inspect the validation error; check schema version, required Agent name, duplicate YAML keys, and selected plugin configuration. |
| No model configured | Desktop: add a route and assign it to the Agent. Embedded: supply the credential declared in the manifest. Server: configure a model in that user's catalog. |
| Server fails to start | Check MySQL connectivity and `SAGE_SERVER_MYSQL_URL`; Redis is not required. |
| Second Server worker fails | Built-in Session storage has an exclusive writer. Use one worker. |
| MCP tools unavailable | Check connection settings and discovery errors; enabled does not mean successfully discovered. |
| Run is waiting | Inspect pending interactions and approve, reject, or provide input through the host. |
| Tool outcome is unknown | Inspect the recorded effect and reconcile before retrying; do not replay blindly. |
| Context does not fit | Configure the actual model window and budgets; fixed instructions cannot be silently dropped. |

For reports, include the entry point, Python/Flutter version, Run or request ID, redacted logs, and reproduction steps. Do not publish API keys or raw credential catalogs.

[Configuration](CONFIGURATION.md) · [Server settings](ENV_VARS.md) · [Runtime reference](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/README.md)
