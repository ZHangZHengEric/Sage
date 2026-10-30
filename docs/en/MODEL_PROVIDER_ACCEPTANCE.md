---
layout: default
title: Built-in model provider acceptance
nav_order: 18
lang: en
ref: v2-model-provider-acceptance
permalink: /en/model-provider-acceptance/
---

{% include lang_switcher.html %}

# Built-in model provider acceptance

This is the acceptance standard for future built-in model-provider presets and plugins. Discuss inclusion in an issue before implementation. A provider preset, a new wire-protocol adapter, and an optional external example have different scopes; name the intended scope and supported hosts explicitly.

## Evidence boundary and terminology

The current implementation below was traced by source inspection at `5e66cbc8cc931155802c84e29d1cfd32d68a2c30` (2026-10-29). It is not an interactive Desktop test, live-provider certification, or a claim that every acceptance requirement is already enforced. Recheck paths against the PR base. “Acceptance requirement” below describes what a future PR must demonstrate; existing gaps are not silently implemented by this document.

| Identifier | Meaning |
| --- | --- |
| Protocol / provider alias | `ModelRoute.provider` chooses a wire protocol or a supported alias; e.g. `orcarouter` resolves to `openai-chat-completions`. |
| Plugin ID | Stable implementation identity, e.g. `sage.model.openai-chat-completions`; distinct from a commercial provider name. |
| Upstream model | `ModelRoute.model` is the endpoint's model identifier, not a catalog record ID. |
| Host record / binding | Server model `id` and Desktop provider-record `id` identify saved configurations. Agent primary/fast bindings select these records. |
| Credential reference | SDK routes refer to a credential declaration; they do not embed a secret. Hosts resolve their stored key into credential material. |

## Current implementation: SDK and request dispatch

Source map (repository-relative paths):

- `sagents/v2/package/manifest/models.py`: `ModelRoute`, request defaults, limits and capability declarations.
- `sagents/v2/model/protocols.py`: descriptors, alias resolution, default endpoints and `create_registered_model_provider`.
- `sagents/v2/model/registry.py` and `registrations.py`: `model.provider` registry and real plugin registrations; metadata alone is not an implementation.
- `sagents/v2/model/plugins/`: OpenAI Chat Completions, Responses, Anthropic Messages and Gemini GenerateContent adapters. A compatible gateway preset should reuse the appropriate adapter rather than copy its transport.
- `sagents/v2/model/capability_contracts.py` and `capability_probe.py`: capability evidence and probe contracts. `protocols.py` checks profile protocol, plugin ownership and version.

For the Chat Completions path, `create_registered_model_provider` builds the adapter with route model, endpoint, request options and resolved credential. `plugins/openai_compatible.py` constructs `AsyncOpenAI` with the configured key/base URL and calls `chat.completions.create` with streaming enabled. It normalizes text and tool-call chunks, closes the upstream stream, classifies errors and rejects incomplete streams. Its bounded dialect negotiation is not permission to retry arbitrary partial outputs or switch providers. Protocol labels and declared capabilities are not proof that a particular gateway/model supports every feature.

## Current implementation: Server

1. `app/v2/server/web/src/views/Models.vue` owns the form/default endpoint map; `model-presentation.js` owns protocol options and provider presentation. `api.js` calls `/api/models`. A brand option here is independent of Desktop.
2. `app/v2/server/routers/models.py` exposes list, POST upsert, detail, delete and `/probe`; `routers/schemas/catalog.py` defines request/response shapes. `catalog/service.py`, `records.py::apply_upsert` and `repository.py` validate and persist the user's model records. Alias defaults are resolved before `ModelRecord.route()` normalizes the protocol.
3. A new record needs a model and key. A blank key on update retains the existing key. Omitted/empty endpoint uses the protocol/alias default; custom endpoints are retained when supplied. The web form replaces an empty or known default endpoint on protocol change, not an arbitrary custom endpoint. Test these semantics rather than assuming PATCH-like behavior for POST upsert.
4. `catalog/model_config.py::app_models` publishes saved records as SDK model bindings and host credential references, with a default binding. `catalog/packages.py` maps Agent primary/fast bindings. `runtime/models.py` builds providers and `runtime/model_pool.py` manages client reuse and cleanup. A successful form save does not prove the Agent selected that record or sent the intended upstream request.

## Current implementation: Desktop

1. `app/v2/desktop/lib/src/ui/settings_screen.dart` implements Models settings. Its protocol picker contains the four protocols, not Server's commercial alias list. A model record has a display name, protocol, base URL, upstream model, key and limits. Adding an SDK alias or Server option does **not** add a Desktop brand preset.
2. `lib/src/state/workspace_controller.dart` and `lib/src/api/v2_api.dart` send list/create/PATCH/delete requests to `/api/v2/model-providers`, plus capability verification requests. `backend/app.py`, `schemas.py` and `catalog_service.py` handle them. Both Desktop request schemas and `catalog.py::DesktopModelProviderRecord` constrain protocol values to the four protocols.
3. The form sends `api_keys` only when a nonempty replacement is entered. The backend accepts at most one key; omitted keys on PATCH preserve the saved value, while an explicitly empty list clears it. Changed configuration requires capability detection before the UI save path proceeds; a display-name-only edit can save without detection. This UI gate is not proof that every direct API client has performed a probe.
4. `backend/catalog.py::JsonDesktopCatalogStore` persists records in `desktop-catalog.json` under the runtime root, using an atomic replacement and mode 0600. Reloaded records populate the model list. Models settings can set a default; Agent settings choose main/fast models using record IDs (`llm_provider_id`, `fast_llm_provider_id`), not upstream model strings.
5. `backend/run_composition.py::_provider` resolves the Agent record, then default/first available record if needed, and rejects missing usable key/endpoint. `backend/model_providers.py::DesktopModelProviders.route/get` translates that record to an SDK route and credential, preserves request settings/profile and reuses providers using a configuration/key-sensitive cache. The selected route reaches the same protocol adapter described above. Fast-model selection has its own binding path in `run_composition.py`.

**Acceptance requirement:** A PR claiming a built-in Desktop option must demonstrate discovery, selection, save, restart/reload, Agent binding and the resulting request. If it only supports manual configuration, say so and give the exact protocol/base-URL/model steps. A new brand preset may map to an existing protocol; do not add an unsupported alias to the Desktop protocol field. Any intentional Server/Desktop difference needs an explicit scope decision and documented gap.

## Credentials, compatibility and failure boundaries

Current storage is not an encryption guarantee. Desktop stores the key as a string in its protected JSON catalog. Server `ModelRecord` uses `SecretStr`, but `catalog/records.py::catalog_payload` extracts raw keys for persistence through `catalog/repository.py`; masking a Python value is not encryption at rest. Deployment storage protection remains a host responsibility.

Ordinary Server list/upsert responses omit the key; authorized detail reads return it with `Cache-Control: no-store`. Desktop lists expose only `api_key_configured`, with a separate key-reveal endpoint also marked `no-store`. Do not describe either API as strictly write-only. Inspect authorization, tenant/user isolation and the actual storage backend when changing this boundary.

Acceptance requirements:

- Never commit real keys, put secrets in model IDs or URLs, or expose them in diagnostics, fixtures, screenshots or PR logs. Preserve list redaction and explicit reveal authorization. Document storage accurately; any redesign needs separate security review.
- Preserve custom base URLs, key retention/rotation and default-selection behavior; do not silently migrate existing users to the added provider. Test cold and warm clients and invalidation when endpoint/key/model/profile changes.
- Provide protocol compatibility evidence for the named endpoint and representative models. Test text streaming and tool-call arguments/results, multiple or fragmented calls where claimed, cancellation, usage and completion markers. Separately establish reasoning, structured output, images and token limits; do not infer them from “OpenAI-compatible.”
- Test invalid keys (401/403), quota/rate limits, invalid model/endpoint, timeouts, malformed responses, interrupted streams and unsupported parameters. Keep errors actionable and sanitized, retries bounded, and cancellation/cleanup correct. Never silently replace a requested capability or retry a partially delivered tool call as a fresh successful run.
- Live capability checks can send data and incur charges. Report sanitized probe scope, endpoint/model, date, profile version and limitations. Mock success does not prove live compatibility; no live test should use another person's credentials without permission.

## Relay-provider inclusion policy

For relay providers requesting a built-in model option or plugin, the provider must recommend **Sage Harness on its website and through its Agent**. Request public evidence of both recommendations and disclosure of the submitter's relationship to the provider. Where “through its Agent” is unclear, clarify the proposed evidence with the maintainer; this standard invents no placement or technical implementation requirement.

This is a necessary condition for consideration, not sufficient approval. Compatibility, security, user benefit and ongoing maintenance remain separate decisions. It creates no promise of acceptance, default usage, endorsement, payment or exclusivity, and no star obligation. It does not apply automatically to unrelated community resources, evaluation reports or search-service submissions. Existing resource-submission guidance remains unchanged. Retrospective changes to already merged integrations require a separate scope decision.

## PR evidence and maintainer checklist

Use [testing guidance](TESTING.md), [configuration](CONFIGURATION.md) and the [contribution guide](https://github.com/ZHangZHengEric/Sage/blob/main/CONTRIBUTING.md). These are review requirements, not a new CI gate or approval automation.

- [ ] State preset versus new adapter/plugin, supported SDK/Server/Desktop surfaces, base/head SHAs, affiliation and responsible maintainer. For an in-scope relay, link both recommendation evidence sources.
- [ ] Trace actual files from UI/options through API/schema, persistence, Agent binding, registry/adapter and outgoing request. Explain every intentionally unsupported surface. Review the complete diff, not just the new alias.
- [ ] Verify endpoint defaults and overrides, upstream-model versus record IDs, secret handling, existing-record migration behavior, default preservation and user isolation.
- [ ] Supply focused regression results with commands/environment and failures/skips. Existing starting points: `tests/sagents/v2/test_builtin_model_protocols_matrix.py`, `test_openai_compatible_model_matrix.py`, `test_model_plugin_capability_contract_matrix.py`; `tests/app/v2/server/test_models.py`, `test_model_pool.py`; `app/v2/server/web/tests/model-presentation.test.js`; `tests/app/v2/desktop/test_model_probe.py`; `app/v2/desktop/test/v2_api_test.dart` and `widget_test.dart`. Choose affected cases; do not rerun unrelated completed CI merely to populate a checklist.
- [ ] Demonstrate Desktop visibility and save/reload/selection using appropriate widget/backend tests and sanitized manual evidence when available. Include failure/retry/cancel behavior. Label source inspection, mocked tests, interactive UI validation and live-provider tests separately; missing evidence remains a review gap.
- [ ] Show a representative streamed text and tool round trip, asserted outgoing model/endpoint/options, negative capability cases and safe failure behavior. Add new adapter-specific tests if existing coverage cannot establish the claim.
- [ ] Update English/Chinese user instructions and contributor references, validate documentation links, and record remaining gaps and follow-up ownership. Do not pad README activity history.
- [ ] Recheck current head, existing replies and concurrent reviews before final action. Recommendation evidence does not replace review; approval and merge remain explicit maintainer decisions.

## Known gaps at the inspected revision

Desktop has no shared commercial-preset list with Server; it requires manual protocol/endpoint/model configuration unless a future PR implements a preset. Storage paths above do not establish encryption at rest. Capability declarations and mocked tests do not certify every upstream model. This document changes none of these runtime behaviors and records no interactive Desktop or live-provider test result.
