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
| Embedded SAgents v2 | `SageManifest`: YAML text, validated Python dictionary, or `sage.yaml`. |
| Desktop v2 | Persisted application settings and catalog; configure models and Agents in the UI. |
| Server v2 | `SAGE_SERVER_*` variables plus per-user model, Agent, Skill, and MCP catalogs. |

## Loading a manifest

```python
from sagents.v2.package.manifest import SageManifest, SageManifestLoader

manifest = SageManifestLoader().loads(yaml_text)
# Alternative: manifest = SageManifest.model_validate(config_dict)
# Then: application = await builder.build(manifest)
```

`loads()` validates YAML and rejects duplicate keys. `load("path/to/sage.yaml")` additionally resolves instruction files inside the package directory. Passing a plain string to `build()` selects file loading. Use inline instructions for in-memory packages.

`credentials` declares where to resolve a secret; `models` references credentials without embedding their values. `agents` selects instructions and model routes; `entrypoint` selects the initial Agent.

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
