---
layout: default
title: Development
nav_order: 10
lang: en
ref: v2-DEVELOPMENT
---

{% include lang_switcher.html %}

# Development

## Source map

| Directory | Responsibility |
| --- | --- |
| `sagents/v2/` | Runtime contracts, composition, providers, and execution |
| `app/desktop_v2/` | Flutter UI and local FastAPI sidecar |
| `app/server_v2/` | Multi-user server and Vue web client |
| `tests/sagents/v2/` | Runtime tests and conformance checks |
| `tests/app/desktop_v2/`, `tests/app/server_v2/` | Host integration tests |
| `docs/en/`, `docs/zh/` | Current bilingual v2 documentation |

## Validate a change

Use the Python 3.12+ environment from [Getting Started](applications/GETTING_STARTED.md). Install server extras for server tests:

```bash
python -m pip install -e '.[server-v2]' pytest pytest-asyncio pytest-timeout
python -m pytest tests/sagents/v2 tests/app/desktop_v2 tests/app/server_v2 -q
```

Run focused tests while developing. Live-provider tests require explicit configuration and may incur model costs. Database tests with injected test stores do not prove production MySQL behavior.

```bash
cd app/desktop_v2
flutter analyze
flutter test
```

```bash
cd app/server_v2/web
npm install
npm run build
```

## Documentation checks

```bash
.venv/bin/python docs/scripts/check_docs.py
bash docs/scripts/build_jekyll.sh
python3 docs/scripts/check_language_nav.py
```

The Jekyll build requires Ruby and the gems in `docs/Gemfile`. Current pages must have matching language metadata, valid local links, and a v2 source reference. Historical files belong in `docs/archive/`, which is excluded from publication. Do not turn old audit pass counts into current readiness guarantees.
