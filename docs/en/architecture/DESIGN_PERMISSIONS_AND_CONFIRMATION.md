---
layout: default
title: Permissions & Confirmation Design
parent: Architecture
nav_order: 98
description: "Permission tiers, confirmation flows, and policy model for tools, sandboxes, and multi-entry apps; design draft, not implemented in code yet"
lang: en
ref: design-permissions-confirmation
---

{% include lang_switcher.html %}

# Permissions & Confirmation Design

> **Status**: design draft for future implementation and acceptance criteria; the codebase does **not** fully implement this document yet.

This note aligns Sage’s stack (`sagents` tools, sandboxing, Web/Desktop/CLI entries) with common patterns in coding agents: **tiered permissions** and **explicit confirmation** for risky operations.

---

## 1. Goals and Principles

| Principle | Meaning |
|-----------|---------|
| **Secure by default** | Sensitive capabilities without explicit policy default to **deny** or **require user confirmation**. |
| **Least privilege** | Split by **domain** (workspace I/O, execution, network, secrets), not one global toggle for all tools. |
| **Explainable** | Surface **human-readable intent** (command, paths, outbound calls), not only internal tool names. |
| **Auditable** | Log allow/deny, policy version, linkage to `session` / `tool_call` for enterprise deployments. |
| **Policy-driven** | Personal, repo, and org layers; org overrides personal. |

---

## 2. Permission Dimensions (Proposed)

| Category | Scope | Examples |
|----------|-------|----------|
| **READ_WORKSPACE** | Read repo | Search, read file, `git diff` |
| **WRITE_WORKSPACE** | Mutate repo | Write file, apply patch, `git commit` (optional sub-split) |
| **EXECUTE** | Run commands | Shell, build; optional: sync vs background vs long-running |
| **NETWORK** | Outbound | HTTP, external MCP, downloads |
| **SECRETS** | Credentials | Env, `.env`, keychain, cloud metadata |
| **ADMIN / DESTRUCTIVE** (optional) | Extreme risk | Mass delete, `git push --force`, global git config, system settings |

---

## 3. Confirmation Granularity

1. **Silent allow** — low risk only (e.g. policy-whitelisted read or diagnostics).
2. **Session grant** — user opts in for a class of actions until session ends or timeout.
3. **Per invocation** — confirm each boundary cross; support **batched** confirmations in one step.
4. **Deny / admin-only** — org lock; UI shows reason only.

**Batching**: multiple `WRITE_WORKSPACE` steps in one turn should be mergeable into one confirmation with a single change list.

---

## 4. Policy Model (Conceptual)

Example shape (not final schema):

```yaml
version: 1
defaults:
  read_workspace: allow
  write_workspace: ask
  execute: ask
  network: ask
  secrets: deny
rules:
  - when: { command_prefix: ["git ", "npm ", "pnpm "] }
    execute: allow_in_sandbox_only
  - when: { path_glob: ".env*" }
    read: deny
```

**Precedence**: `ORG > REPO > USER > product defaults`.

**Sandbox coupling**: `allow_in_sandbox_only` **must** use a strong isolation provider; if only passthrough/weak mode is available, **deny** instead of silently weakening.

---

## 5. UX Across Entry Points

- **On session start**: trust scope (repo root, network, execute) → session grant.
- **Pending action card**: labels, risk summary, expandable detail (full command, paths, outbound).
- **Actions**: once / session for class / deny; **no** “always allow” for destructive classes.
- **CLI**: TTY prompt or explicit `--yes` / `--policy-file`; automation must be explicit.
- **Enterprise**: audit fields `user_id`, `session_id`, `tool_call_id`, policy version, `decision`.

**Consistency**: Web, Desktop, and CLI should share one **decision protocol** (pending → user choice → resume tool execution).

---

## 6. Technical Touchpoints in Sage

| Layer | Hook |
|-------|------|
| **Tools** | **PolicyGate** before execution: normalized intent → `ALLOW` / `ASK_USER` / `DENY` + `reason_code`. |
| **Shell tools** | Stack PolicyGate on top of existing `SecurityManager` (blacklist = hard floor). |
| **Sandbox** | `sagents/utils/sandbox/`: type tied to policy; no silent downgrade on mismatch. |
| **Server** | For weakly authenticated APIs, default **deny** execute-class tools or require API key + quota. |
| **Frontends** | `app/server/web/`, `app/desktop/ui/`: wire pending-approval events into stream lifecycle. |
| **MCP** | Each server declares **required permission set**; intersect with session policy or prompt. |

---

## 7. Phased Rollout

| Phase | Scope |
|-------|-------|
| **P0** | Enums, `reason_code`, PolicyGate API; wire **write**, **execute**, **network** tools first. |
| **P1** | Session grants + confirmations in UI/CLI; structured logs or audit store. |
| **P2** | Repo policy file; org policies; MCP capability declarations. |
| **P3** | Batched confirmations, richer summaries; SSO/audit integrations. |

---

## 8. Acceptance Checks

- No silent **write / execute / network** without policy or user consent.
- Org overrides user; sandbox mode inconsistent with policy → **deny**, not fallback.
- Low-risk batches can merge; **DESTRUCTIVE** cannot be “remember forever allow”.
- On deny, return a **structured signal** to the model (e.g. `POLICY_DENY`) to limit retry loops.

---

## 9. Related Docs

- [Tool & Skill System](ARCHITECTURE_SAGENTS_TOOL_SKILL.md)
- [Sandbox, LLM & Observability](ARCHITECTURE_SAGENTS_SANDBOX_OBS.md)
- [Server & Web App Architecture](ARCHITECTURE_APP_SERVER.md)
- Chinese mirror: [权限与确认设计方案](../../zh/architecture/DESIGN_PERMISSIONS_AND_CONFIRMATION.md)

---

## 10. Revision History

| Date | Notes |
|------|-------|
| 2026-05-11 | Initial draft: dimensions, confirmation tiers, policy sketch, touchpoints, phases |
