---
layout: default
title: Development
nav_order: 9
description: "Contributor workflow and source locations"
lang: en
ref: development
---

{% include lang_switcher.html %}

# Development

## Repository Areas

- `sagents/`: runtime and orchestration
- `app/server/`: main backend and web application
- `app/desktop/`: desktop backend, UI, and build scripts
- `examples/`: runnable examples and demos
- `mcp_servers/`: built-in MCP server implementations
- `app/skills/`: bundled skill content and helper assets

## Local Development Workflow

### Backend

```bash
pip install -r requirements.txt
python -m app.server.main
```

Use this path when you want to work on the main backend rather than the lightweight examples.

### Web frontend

```bash
cd app/server/web
npm install
npm run dev
```

Common frontend environment variables:

- `VITE_SAGE_API_BASE_URL`
- `VITE_SAGE_WEB_BASE_PATH`

### Desktop

For source builds and packaging, start with:

```bash
app/desktop/scripts/build.sh release
```

Development scripts also exist under `app/desktop/scripts/`.

### Lightweight examples

If you want the smallest possible feedback loop, start from:

```bash
python examples/sage_cli.py \
  --default_llm_api_key "$SAGE_DEFAULT_LLM_API_KEY" \
  --default_llm_api_base_url "$SAGE_DEFAULT_LLM_API_BASE_URL" \
  --default_llm_model_name "$SAGE_DEFAULT_LLM_MODEL_NAME"
```

### Documentation site

The docs site uses GitHub Pages Jekyll dependencies, so build it with the Ruby version pinned in `docs/.ruby-version`.

With RVM:

```bash
source ~/.rvm/scripts/rvm
rvm use 3.2.9
cd docs
bundle config set path vendor/bundle
bundle install
bundle exec jekyll serve
```

For a one-off build:

```bash
source ~/.rvm/scripts/rvm
rvm use 3.2.9 do bash -lc 'cd docs && bundle exec jekyll build'
```

## Where To Read First

### Runtime behavior

- `sagents/sagents.py`
- `sagents/agent/`
- `sagents/flow/`
- `sagents/context/`

### Server behavior

- `app/server/main.py`
- `app/server/routers/`
- `app/server/services/`
- `app/server/core/`

### Frontend behavior

- `app/server/web/src/views/`
- `app/server/web/src/api/`
- `app/server/web/src/components/`

### Example behavior

- `examples/README.md`
- `app/cli/main.py`
- `examples/sage_server.py`

## Documentation Standards for This Repository

- Prefer documenting stable concepts and entry points, not temporary refactors.
- Treat source files as the authority when docs and code disagree.
- Avoid duplicating the same full document set in multiple languages unless there is an explicit maintenance owner.
- Keep top-level docs short and route readers to source directories for implementation details.
