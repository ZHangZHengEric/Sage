---
layout: default
title: Remote Skill Import
nav_order: 17
lang: en
ref: v2-detail-skill-import
parent: Architecture
---

{% include lang_switcher.html %}

# Remote Skill Import

## Supported sources

The Server Skills page supports local ZIP, online ZIP, and Skills CLI import. Online ZIP accepts public HTTPS URLs on port 443. Skills CLI accepts public GitHub sources, resolves a fixed commit, downloads its repository ZIP, validates selected Skills, and uses a pinned CLI for project-local copying and catalog publication.

The server requires Node.js 22.20+, npx, and GitHub/npm registry connectivity. Downloads revalidate DNS on redirects and reject local, private, and reserved addresses.

## Preview and publish

Call `POST /api/skill-import-previews` to discover candidates and inspect paths, digests, and conflicts. Publish selected candidates with `POST /api/skill-imports`. Same-name updates require explicit selection and expected version/digest checks. Identical content reuses the existing version; each item returns success, unchanged, conflict, or failure.

Import reuses existing Skill versions and artifact directories. Publication does not bind every agent, install plugins, register MCP services, or expand tool grants. Runtime authorization and bindings remain host-owned.

## Scope limits

The current entry point does not provide marketplaces, private repositories, a separate Git URL input, source auto-updates, or team HTTP catalogs. Download and publication depend on actual network availability; a successful preview does not guarantee subsequent publication or execution.

[Import UI](../../../app/v2/server/web/src/views/Skills.vue) · [HTTP routes](../../../app/v2/server/routers/skills.py) · [Source resolution](../../../app/v2/server/skills/import_sources.py) · [Catalog and versions](../../../app/v2/server/skills/service.py)
