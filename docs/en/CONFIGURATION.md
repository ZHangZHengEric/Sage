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

## Model stream idle timeout

Set `models.<binding>.request.extra.stream_idle_timeout_seconds` to a positive
number of seconds on an `openai-chat-completions`, `openai-responses`,
`anthropic-messages`, or `gemini-generate-content` model route. Omit it or set it
to `null` to leave the idle check disabled. Python callers can set the same
field on the corresponding adapter config.

After the response stream opens, Sage counts only time spent waiting for
upstream events. Processing and delivering events does not consume this budget.
New text, reasoning, and tool call fragments reset the budget. Heartbeats, empty
deltas, and usage-only frames do not. Idle failures use `model.stream_idle_timeout`
and the existing retry budget. The `stream_idle_phase` diagnostic is `first_chunk` before any
progress or `mid_stream` after progress. Connection and Run deadlines still apply.

## Gemini GenerateContent request size

The native `gemini-generate-content` route defaults to a 20,000,000-byte limit
for the serialized request body. Set `models.<binding>.request.extra.max_request_bytes`
to match your endpoint. The adapter first applies `max_inline_videos`, then
replaces the oldest remaining inline videos and audio with text references until
the body fits. `analyze_audio` and `analyze_video` accept files up to 12 MiB, so
one attachment fits the default limit. If it still exceeds the byte budget, Sage reports `model.request_too_large`
before sending it. The budget includes text, tools, and all media in the request.

## Audio and video input

`analyze_audio` and `analyze_video` are visible only to models that accept the
matching input. Declare it with `audio_input` and `video_input` under
`models.<binding>.capabilities`:

- `gemini-generate-content`: follows `multimodal` when omitted.
- `openai-chat-completions`: `false` when omitted. Set `true` when the backend
  model accepts it (for example Qwen-Omni or some OpenRouter models). Audio is
  sent as `input_audio` and video as `video_url`.
- `openai-responses` and `anthropic-messages`: never supported; the declaration
  is ignored.

The model capability check probes image input, WAV audio, and inline MP4 video
independently. A saved result supplies the default for an unspecified
`audio_input` or `video_input` setting when it conclusively supports or rejects
that input. Explicit settings take precedence. A connection error leaves that
input unverified. Hosted video is skipped during settings probes because
uploading a video requires an owning Run.

Sage selects recent Session attachments by model capability, configured request
limits, and a 32 MB aggregate Base64 budget before loading payloads. A short
notice represents unsupported attachments and attachments that exceed these
limits. The Session keeps their original snapshots.

### Chat Completions video URLs

For a Server model using a gateway that reads MP4 URLs from `image_url.url`
(such as gateway 85), select a host-authorized profile:

```yaml
capabilities:
  video_input: true
request:
  extra:
    video_url_format: image_url
    video_storage_profile: gateway-video
```

The Server operator defines profiles in `SAGE_SERVER_VIDEO_STORAGE_PROFILES`.
Each profile contains authorized Server user IDs in `owner_ids` and an
`S3VideoStorageConfig` object in `storage`:

```json
{"gateway-video":{"owner_ids":["user-id"],"storage":{"bucket":"private-video-bucket","region":"ap-southeast-1","prefix":"sage/model-video"}}}
```

SDK hosts can pass a trusted `S3VideoStorageConfig` as the `video_storage`
argument to `create_registered_model_provider`. Model route extras cannot
supply raw storage targets. For existing HTTPS video URLs, set only
`video_url_format`. The standard Server image includes the S3 dependency.
Other SDK installations can use `sage[s3-video]`. Configure the AWS SDK
credential chain for workspace uploads.
Grant `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`, and
`s3:DeleteObjectVersion` under the configured prefix, plus `s3:ListBucket` and
`s3:ListBucketVersions` scoped to that prefix. You can set an HTTPS
`endpoint_url` for S3-compatible storage. Sage checks the storage target with
read-only operations, then records ownership before issuing an upload. Copies
are stored under a per-Run prefix. Session deletion,
including tenant cleanup, removes these copies and their object versions. If
cleanup fails, the Session retains its record so deletion can be retried with
access to the original bucket. When a PUT times out, the Session retains its
record until the exact object can be confirmed. An empty listing does not
resolve a timed-out write. Preview records created before per-object tracking
require storage reconciliation. The bucket lifecycle can expire old copies as
a backstop. The workspace tool accepts files up to 12 MiB each.

Chat Completions also replaces older videos beyond `max_inline_videos`
(default 10) with text references. When the body exceeds `max_request_bytes`,
it then replaces the oldest inline audio and video with text references. For a
gateway that forwards to Gemini, set `max_request_bytes` to `20000000`.
`input_audio` accepts base64 data. For Chat Completions, `analyze_audio`
asks for a workspace file when given a remote URL.

### Gemini video storage

`gemini-generate-content` routes accept the same Server profile without
`video_url_format`. Sage sends hosted videos as signed `fileData.fileUri`
references. User-provided remote media URLs are sent only in the current
inference turn. History keeps the attachment and sends a short omission notice
in later turns. Diagnostics and errors redact Sage-generated URL signatures.

Both protocols return `model.video_storage_failed` only when a video in the
current turn (after the latest model reply) cannot be uploaded. An earlier
video that fails to upload is replaced by a one-line notice, the request is
still sent, and Sage records a `video_storage_omitted` diagnostic event.

## Gemini tool calls through OpenAI compatibility

For a Gemini model using `openai-chat-completions`, Sage retains the documented
`extra_content.google.thought_signature` on each matching tool call across
streamed responses, conversation history, and Session save/restore. No additional
configuration is needed. Signatures remain opaque strings; unrelated extension
fields are not retained. Malformed signature state is rejected, and the existing
8 MiB provider-state limit applies. This handling concerns tool-call signatures;
the native `gemini-generate-content` route has its own continuation handling.
Historical memory pruning preserves complete tool-call groups carrying provider
continuation state, including their results, so it cannot detach a signature from
its call. Ordinary memory calls without provider state are still pruned.

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
