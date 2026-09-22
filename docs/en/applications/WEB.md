---
layout: default
title: Server v2
nav_order: 3
lang: en
ref: v2-applications-WEB
parent: Applications
---

{% include lang_switcher.html %}

# Server v2

## Requirements

Python 3.12+, MySQL, and Node.js 22.12+. Complete the [source setup](GETTING_STARTED.md) first. **Redis is not a Server v2 startup dependency.**

## Start

Run from the checkout root with the Python environment active:

```bash
python -m pip install -e '.[server-v2]'
cp app/server_v2/.env.example app/server_v2/.env
```

Set `SAGE_SERVER_MYSQL_URL`, your own `SAGE_SERVER_JWT_SECRET` (at least 32 bytes), and initial administrator credentials in `app/server_v2/.env`.

```bash
cd app/server_v2/web
npm install
npm run build
cd ../../..
python -m app.server_v2
```

Open [http://127.0.0.1:8090](http://127.0.0.1:8090). Configure a model and an Agent after login. `/studio` manages Agent packages; `/docs` exposes the running server's OpenAPI.

For frontend development use `npm run dev` in `app/server_v2/web`; Vite proxies to port 8090. Process environment variables override the component `.env` file.

## Storage and deployment boundary

- MySQL stores users, catalogs, thread indexes, Agent package inventory, and runtime Sessions.
- AG-UI replay reads canonical RuntimeEvents from Sage Sessions, not a separate Redis event log.
- Workspace files live under the configured data root's tenant directories.
- Run **one worker**. The built-in SessionStore rejects a second writer; the Scheduler and JobRuntime do not supply multi-host durability.

[`deploy/`](https://github.com/ZHangZHengEric/Sage/blob/main/deploy/README.md) contains several stacks. Inspect the image and module used by a Compose environment before treating it as a Server v2 deployment.

[Environment reference](../ENV_VARS.md) · [HTTP API](../api/HTTP_API_REFERENCE.md) · [Component reference](https://github.com/ZHangZHengEric/Sage/blob/main/app/server_v2/README.md)
