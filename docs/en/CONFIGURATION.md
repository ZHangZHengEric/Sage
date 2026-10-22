---
layout: default
title: Configuration
nav_order: 5
lang: en
ref: v2-CONFIGURATION
---

{% include lang_switcher.html %}

# Configuration

## Three configuration owners

| Host | Configuration source |
| --- | --- |
| Embedded SAgents | `SageManifest`: YAML text, validated Python dictionary, or `sage.yaml`. |
| Desktop | Persisted application settings and catalog; configure models and Agents in the UI. |
| Server | `SAGE_SERVER_*` variables plus per-user model, Agent, Skill, and MCP catalogs. |

## Loading a manifest

```python
from sagents.v2.package.manifest import SageManifest, SageManifestLoader

manifest = SageManifestLoader().loads(yaml_text)
# Alternative: manifest = SageManifest.model_validate(config_dict)
# Then: application = await builder.build(runtime=manifest.runtime, models=model_config)
```

`loads()` validates YAML and rejects duplicate keys. `load("path/to/sage.yaml")` additionally resolves instruction files inside the package directory. Passing a plain string to `build()` selects file loading. Use inline instructions for in-memory packages.

`credentials` declares where to resolve a secret; `models` references credentials without embedding their values. `agents` selects instructions and model routes; `entrypoint` selects the initial Agent.

## OrcaRouter models

`orcarouter` is an optional provider preset using the existing OpenAI-compatible
Chat Completions implementation. In Server, select `orcarouter` in the model
form and enter your model ID and API key. The default endpoint is
`https://api.orcarouter.ai/v1`; a custom Base URL is preserved.

For an embedded manifest, add this model route and configure the referenced
credential in the complete manifest:

```yaml
models:
  primary:
    provider: orcarouter
    model: your-model
    credential: orcarouter_key
```

When `base_url` is omitted, the route uses the same OrcaRouter endpoint.
This preset supports the existing chat protocol; it does not add image or
video generation APIs.

## Cheaper Inference models

`cheaperinference` is an optional provider preset using the existing
OpenAI-compatible Chat Completions implementation. In Server, select
`cheaperinference` in the model form and enter your model ID (for example
`gpt-5.4-mini`) and API key. The default endpoint is
`https://api.cheaperinference.com/v1`; a custom Base URL is preserved.

For an embedded manifest, add this model route and configure the referenced
credential in the complete manifest:

```yaml
models:
  primary:
    provider: cheaperinference
    model: gpt-5.4-mini
    credential: cheaperinference_key
```

When `base_url` is omitted, the route uses the same Cheaper Inference endpoint.
This preset supports the existing chat protocol; it does not add image or
video generation APIs.

## Selecting runtime implementations

Use `runtime.capabilities` for provider bindings. For example, the lazy Skill loader accepts a token budget:

```yaml
runtime:
  capabilities:
    skill.loading:
      plugin: sage.skill.loading.lazy
      config:
        max_active_tokens: 6000
```

This is a fragment to add to a complete manifest. Plugin configuration is schema-validated. Availability and behavior depend on actual registered implementations; a metadata-only declaration does not create a working provider.

[Extensions](architecture/PLUGINS.md) · [Environment reference](ENV_VARS.md) · [Full integration manual](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/使用手册.md)

## Desktop interactive UI default

Desktop settings persist `default_interactive_ui` as a boolean, initially `false`. Change it in Settings → General. It initializes new ordinary chats and does not overwrite existing chat preferences. Each chat stores `prefer_interactive_ui`; requests carry `ui_preference: "interactive"` or `"auto"`. Enabled requests preload the bundled OpenUI Skill instructions in host context. This setting belongs to Desktop and does not change embedded SAgents or Server behavior.

See [Desktop usage](applications/DESKTOP.md).
