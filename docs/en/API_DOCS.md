---
layout: default
title: API documentation
nav_order: 8.5
has_children: true
description: "Entry point for current HTTP and legacy Python runtime API material"
lang: en
ref: api-docs
---

{% include lang_switcher.html %}

# API documentation

Use this page to pick the right doc set (and avoid mixing “HTTP” with “old Python API”):

- **[HTTP API Reference](HTTP_API_REFERENCE.md)** (expand for **subpages**): backend HTTP endpoints, payloads, and `curl` examples aligned with `register_routes` in `app/server/routers`. This is the **source of truth** for integrating with the current server.
- **[Python runtime API (legacy v0.9)](API_REFERENCE.md)**: restored runtime-facing Python notes from older material; **not** the current HTTP API. Skip it if you only care about HTTP.
