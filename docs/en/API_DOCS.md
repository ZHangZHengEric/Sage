---
layout: default
title: API documentation
nav_order: 8.5
has_children: true
description: "Entry point for HTTP and Python (SAgent) runtime documentation"
lang: en
ref: api-docs
---

{% include lang_switcher.html %}

# API documentation

Use this page to pick the right doc set (and avoid mixing the hosted **HTTP** API with the **Python** `sagents` API):

- **[HTTP API Reference](HTTP_API_REFERENCE.md)** (expand for **subpages**): backend HTTP endpoints, payloads, and `curl` examples aligned with `register_routes` in `app/server/routers`. This is the **source of truth** for integrating with the current server.
- **[Python runtime API](API_REFERENCE.md)**: embedding `SAgent` and related types from this repo; **not** the HTTP surface of the main app. Skip it if you only integrate over HTTP.