# Model inference provider resources

[Knowledge hub](../README.md)

A starting point for finding model inference services and connecting them to Sage: direct APIs from model developers, aggregated routing services, and community-submitted gateways. Choose a service first, then match its API protocol to Sage's `provider` setting.

Sources checked: **2026-10-15**. The entries below describe documented APIs and corresponding Sage settings. Inclusion does not mean a service has passed end-to-end testing with Sage; no live model calls were made for this page.

## Official model providers

These services expose APIs directly from the model developer. Use their documentation to choose a model, obtain an API key, and check feature availability and account limits.

### OpenAI

OpenAI provides model access through Responses and Chat Completions. Choose the protocol supported by your selected model and workload.

- **Resources:** [API comparison](https://developers.openai.com/api/docs/guides/migrate-to-responses) · [Streaming](https://developers.openai.com/api/docs/guides/streaming-responses)
- **Sage:** `openai-responses` for streaming Responses, or `openai-chat-completions` for Chat Completions.
- **API base:** `https://api.openai.com/v1`
- **Credential:** an OpenAI-issued key, referenced through an environment variable such as `OPENAI_API_KEY`.

### Anthropic

Anthropic provides Claude through the Messages API, including streaming. Use Sage's native Messages protocol when connecting directly.

- **Resources:** [API overview](https://platform.claude.com/docs/en/api/overview) · [Messages streaming](https://platform.claude.com/docs/en/build-with-claude/streaming)
- **Sage:** `anthropic-messages`
- **API base:** `https://api.anthropic.com`
- **Credential:** an Anthropic-issued key, for example through `ANTHROPIC_API_KEY`.

### Google Gemini

Google provides a native GenerateContent API and an OpenAI-compatible Chat Completions interface. Select the corresponding Sage protocol and base URL together.

- **Resources:** [GenerateContent and streaming](https://ai.google.dev/api/generate-content) · [OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai)
- **Native Sage configuration:** `gemini-generate-content` with `https://generativelanguage.googleapis.com/v1beta`.
- **OpenAI-compatible Sage configuration:** `openai-chat-completions` with `https://generativelanguage.googleapis.com/v1beta/openai/`.
- **Credential:** a Gemini-issued key, for example through `GEMINI_API_KEY`.

## Aggregated routing services

### OpenRouter

OpenRouter offers access to models through a routing layer. Its model IDs, downstream providers, and routing policies are part of the service configuration; access to a model through OpenRouter is distinct from using that model developer's direct API.

- **Resources:** [API reference](https://openrouter.ai/docs/api_reference/overview) · [Responses API](https://openrouter.ai/docs/api_reference/responses/overview) · [Models](https://openrouter.ai/models)
- **Sage:** `openai-chat-completions` for its Chat Completions path. For a route supporting streaming Responses, the corresponding selector is `openai-responses`; verify the selected route's event support before use.
- **API base:** `https://openrouter.ai/api/v1`
- **Credential:** an OpenRouter-issued key, for example through `OPENROUTER_API_KEY`.

Check the selected model's capabilities, downstream selection and fallback rules, fees, and data policies. For model discovery and limits, see [choosing free models on OpenRouter](openrouter-free-models.md).

## Community-submitted third-party gateways

### A2Agent

[A2Agent](https://a2agent.me/) was submitted in [PR #305](https://github.com/ZHangZHengEric/Sage/pull/305) as an alternative Responses-compatible gateway. Treat that protocol support as unverified in Sage. Obtain the service's current API documentation, model IDs, and connection details before configuring it.

The PR author, `A2agent-ai`, disclosed: “I work with A2Agent.” The author provided no end-to-end compatibility validation and reported that no live model call was made. This page also includes no live A2Agent testing. Inclusion is not an official Sage recommendation or a production-readiness guarantee.

If the selected route supports Sage's streaming Responses requirements, its matching protocol selector is `openai-responses`. Use the neutral example below to identify the configuration fields, and independently check the service's pricing, privacy, and downstream routing policies.

## Match the API protocol

A model's brand does not determine the protocol exposed by a gateway. Use one of Sage v2's four canonical identifiers from the [protocol definitions](../../sagents/v2/model/protocols.py):

| API | Sage `provider` | Request and streaming format |
| --- | --- | --- |
| Chat Completions | `openai-chat-completions` | `POST /chat/completions`; `messages` input and streamed choice deltas, including tool-call fragments. |
| Responses | `openai-responses` | `POST /responses` with `stream: true`; typed input/output items, named delta events, and terminal response events. |
| Anthropic Messages | `anthropic-messages` | Native Messages requests and streaming events. |
| Gemini GenerateContent | `gemini-generate-content` | Native Gemini content requests and streaming responses. |

The OpenAI-style paths above are relative to the API base. Both Chat Completions and Responses can stream, but their request and event formats differ. Chat Completions support or a successful non-streaming Responses request does not establish compatibility with Sage's streaming Responses implementation. Changing `base_url` changes the destination; it does not convert the protocol. `OpenRouter` and `A2Agent` are service names, not additional built-in protocol IDs.

## Connect a service to Sage

This complete v2 manifest uses a fictional destination. Replace the model ID and base URL with values independently verified with your chosen service. `https://gateway.example/v1` is a placeholder and will not provide inference.

```yaml
schema_version: sage/v2
kind: application
metadata: {id: example.gateway-guide, version: 1.0.0, name: Gateway example}
credentials:
  gateway-key: {source: env, key: GATEWAY_API_KEY}
models:
  primary:
    provider: openai-chat-completions
    base_url: https://gateway.example/v1
    credential: gateway-key
    model: your-gateway-model-id
agents:
  main:
    name: Assistant
    instructions: {inline: "Be helpful and concise."}
    models: {primary: primary}
entrypoint: {agent: main}
```

Supply `GATEWAY_API_KEY` in the process environment through your local secret-management mechanism. `source: env` and `key: GATEWAY_API_KEY` tell Sage to resolve that variable; do not paste a token or a literal `${GATEWAY_API_KEY}` into an API-key field and assume it expands. Keep secrets out of committed files, screenshots, and logs.

For a service that supports streaming Responses, use `provider: openai-responses` with its documented base URL and model ID. For a direct official service or OpenRouter, substitute the matching settings and environment-variable name from the sections above. Follow the [executable quick start](../../examples/v2/quickstart.py) and [getting-started guide](../../docs/en/applications/GETTING_STARTED.md) to load and run a manifest. Running an adapted example makes real requests and may incur charges.

**Trust boundary:** Request content and the API key are sent to the configured gateway. Content may include conversation history, tool results, and attachments. Use only a trusted service and a key issued for that service. Do not send an unrelated provider's key to a gateway. Independently check fees, privacy and retention terms, and downstream routing/fallback policies before sending data. HTTPS alone does not establish trustworthy handling.

## Sources and validation

This resource page draws on the linked official API documentation, [Sage's protocol definitions](../../sagents/v2/model/protocols.py), its [Chat Completions](../../sagents/v2/model/plugins/openai_compatible.py) and [Responses](../../sagents/v2/model/plugins/openai_responses.py) implementations, and PR #305's submission and disclosure.

Local checks cover manifest parsing, canonical provider identifiers, configuration fields, internal links, and the diff. They do not establish service compatibility. Live authentication, streaming, tool round trips, multimodal/reasoning features, billing, limits, performance, availability, downstream routing, and privacy enforcement were not tested. Check the exact model and endpoint for the features you need; documentation, availability, and policies can change.
