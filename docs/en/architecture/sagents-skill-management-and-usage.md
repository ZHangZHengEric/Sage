---
layout: default
title: Skill management and usage
parent: Architecture
lang: en
ref: v2-skill-management-and-usage
---

{% include lang_switcher.html %}

# Skill management and usage

Two configuration groups select management and usage capabilities. The defaults
are **filesystem + lazy + auto-sync**.

```yaml
skills:
  management:
    plugin: sage.skill.filesystem
    scope: process
    config:
      roots: [/srv/sage/managed-skills]
  usage:
    workspace:
      plugin: sage.skill.workspace.auto-sync
      scope: run
    loading:
      plugin: sage.skill.loading.lazy
      config:
        max_active_characters: 24000
```

This is RuntimeConfig input; put it under `runtime` in a package. Parsing expands
the groups to standard capability selections. Management provides
`skill.management`, `skill.catalog` and `skill.source`; usage chooses
`skill.workspace` and `skill.loading`. Conflicting grouped and explicit selections
are rejected. Only canonical selections are serialized.

| Management plugin | Behavior |
| --- | --- |
| `sage.skill.filesystem` (default) | Read directories from `roots`; files are managed outside Sage, for example through Git; no historical version guarantee |
| `sage.skill.repository.sqlite` | Durable transactional metadata, file BLOBs, immutable versions and per-Run catalog snapshots |
| `sage.skill.repository.memory` | The same version semantics in memory; lost on process exit |

`default_runtime(root)` reads filesystem Skills from `root/skills`. Explicit host
sources remain unchanged. SQLite requires `path`; version repositories accept
`max_files` (2000) and `max_total_bytes` (67108864). Trusted hosts can publish with
`app.service("skill.management").publish(bundle, expected_version=...)` when a
writable repository is selected. Publishing is not automatically an Agent tool.
Use separate roots per tenant or a tenant-authorized provider. Repositories pin a
Run's visible catalog on first lookup; SQLite pins survive restart. Hosts that
need acceptance-time selection retain their accepted composition snapshots.

## Workspace policies

All three policies expose a Skill at `skills/<name>/`. A reference is read at
`/workspace/skills/demo/references/guide.md`; no version-hash root is exposed.

| Workspace plugin | Behavior |
| --- | --- |
| `sage.skill.workspace.readonly-mount` | Require a genuine sandbox mount that enforces read-only access for both files and processes |
| `sage.skill.workspace.auto-sync` (default) | Archive local Agent changes, then fully synchronize the visible directory to manager contents |
| `sage.skill.workspace.fixed-copy` | Create one working copy and retain it, including Agent edits; later manager updates do not replace it |

Workspace plugins use Run scope and the real `execution.environment` sandbox and
signed grants. The default is assembled only inside an existing Run sandbox.
`sage.skill.loading.lazy` remains the loading algorithm: discovery does not copy
packages; explicit loading, preloads and user selection materialize within the
active context budget.

Auto-sync keeps only current source metadata and file hashes at
`skills/.catalog/<name>/state.json`. Manager-only updates replace current bytes
and delete obsolete files and empty directories, without archiving old manager
packages. Local changes against the previous manager hashes are archived first
at `.catalog/<name>/agent-edits/<content-hash>/files/`, with a record of deletions.
Only modified/added files and deletion records are archived; unchanged manager
files are not duplicated. The visible directory is then restored to manager contents, even if the source
version did not change. Untracked existing local contents are conservatively
archived. If archiving fails, current files are preserved. Pending file hashes
allow interrupted synchronization to resume without misclassifying a partial
manager update as an Agent edit. This is not a multi-file transaction.

For `CurrentSkillSource`, auto-sync calls `fetch_latest` on every explicit load,
retaining the Run's admitted-name boundary. Built-in filesystem, repositories and
Server catalog support this port. Custom sources with only `fetch` retain their
own version selection.

Writer attribution uses a separate manager source and last-delivered hashes,
not an OS writer audit. Auto-sync rejects an identical source and working
directory because a rewritten sole original cannot be restored. Agent editing
uses the visible stable directory. Optional `edit_skill` requires tool declaration
plus `skill.load` and `skill.edit` scopes. Auto-sync archives edits on the next
load; fixed-copy retains them. Archives are not automatically promoted to sources.

Within a process, handles expose a stable `workspace_identity` for backing files.
Same-version readers can coexist; replacing a directory while another Run is
using it is rejected. Separate workspaces do not block one another. Distributed
hosts need cross-process coordination or isolated workspaces; these plugins do
not claim distributed locking. Recovery verifies accepted contents and refuses
to downgrade an already-advanced shared directory.

Read-only mounting uses the optional `sandbox.skill_mounts` port implementing
`SkillReadonlyMountProvider`. A signed request binds Run, destination and hashes.
The backend must verify the request and enforce read-only file and process access.
Current local, ephemeral and Cube backends do not provide this port: selection
fails with `skill.readonly_mount_unsupported`, without copying or symlink fallback.
Hosts with real mount support can implement the public protocol.

Register plugins through `builder.register(ExtensionRegistration(...))` and keep
the standard `build → load_agent → entrypoint().run_stream` sequence.
