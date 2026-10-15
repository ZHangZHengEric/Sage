# Model inference providers and third-party gateways

[Knowledge hub](../README.md)

Sources and Sage configuration manually checked: **2026-10-15**. This guide was written from the official documentation linked below, the current Sage v2 source, and the disclosure in [PR #305](https://github.com/ZHangZHengEric/Sage/pull/305). It is not a compatibility certification. No live model calls or end-to-end service compatibility tests were performed for this guide.

## Distinguish the service from the protocol

- **Official model providers:** OpenAI, Anthropic, and Google offer their own model APIs. Consult their documentation for the selected model and endpoint.
- **Aggregated routing services:** OpenRouter provides access to models through a routing layer. The router, selected downstream provider, and model each impose constraints.
- **Community-submitted third-party gateways:** A2Agent is discussed separately below because it was submitted by an affiliated contributor. Inclusion is not an official Sage recommendation or a production-readiness guarantee.

A model's brand does not select its wire protocol. A gateway serving a model may expose a different API from the model developer's native API. Vendor documentation establishes what a service documents, not what has passed testing through Sage.

## Official model providers

The settings below map documented APIs to Sage's implementations. Base URLs are reference values, not evidence of a successful call. Use a model ID available to your account and a key issued by the service receiving the request.

| Service | Official documentation and applicable protocol | Sage v2 configuration |
| --- | --- | --- |
| OpenAI | [Responses and Chat Completions comparison](https://developers.openai.com/api/docs/guides/migrate-to-responses); [streaming guide](https://developers.openai.com/api/docs/guides/streaming-responses) | `provider: openai-responses` for streaming Responses, or `provider: openai-chat-completions` for Chat Completions; `base_url: https://api.openai.com/v1`; credential environment variable such as `OPENAI_API_KEY`. |
| Anthropic | [Claude API overview](https://platform.claude.com/docs/en/api/overview); [Messages streaming](https://platform.claude.com/docs/en/build-with-claude/streaming) | `provider: anthropic-messages`; `base_url: https://api.anthropic.com`; environment variable such as `ANTHROPIC_API_KEY`. This implementation uses the Messages protocol, not OpenAI Responses. |
| Google Gemini | [Native GenerateContent and streaming API](https://ai.google.dev/api/generate-content); [OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai) | Native: `provider: gemini-generate-content`, `base_url: https://generativelanguage.googleapis.com/v1beta`. Google's documented OpenAI-compatible Chat Completions path instead maps to `provider: openai-chat-completions`, `base_url: https://generativelanguage.googleapis.com/v1beta/openai/`. Use a Gemini-issued key, for example via `GEMINI_API_KEY`. |

In each case, use the environment credential declaration shown below with the corresponding variable name. A native endpoint and an OpenAI-compatible endpoint are not interchangeable. Feature availability, including tools, reasoning, images, and structured output, must be checked for the exact model, endpoint, and Sage implementation.

## Aggregated routing services: OpenRouter

OpenRouter documents an [OpenAI-compatible API](https://openrouter.ai/docs/api_reference/overview) and a separate [Responses API](https://openrouter.ai/docs/api_reference/responses/overview). For its Chat Completions path, set `provider: openai-chat-completions` and `base_url: https://openrouter.ai/api/v1`. Use an OpenRouter-issued key through an environment credential such as `OPENROUTER_API_KEY` and the exact model ID listed by OpenRouter.

For a route explicitly documented to support streaming Responses, the corresponding Sage selector is `openai-responses` with the same base URL. This is a protocol mapping, not a tested OpenRouter/Sage compatibility claim. Verify the required event stream and model features before adopting it.

Check account limits, downstream selection and fallback rules, pricing, and data policies independently. A successful request to one downstream provider does not validate another route. See also [choosing free models on OpenRouter](openrouter-free-models.md); this guide does not promise free access or continuing availability.

## Chat Completions versus streaming Responses

| Behavior | Chat Completions | Streaming Responses |
| --- | --- | --- |
| Sage provider | `openai-chat-completions` | `openai-responses` |
| Request endpoint relative to the API base | `POST /chat/completions` | `POST /responses` |
| Request and stream shape | `messages`; streamed choice deltas, including tool-call fragments | Typed input/output items and named events for text, tool arguments, and completion |
| What a gateway must support | The streamed Chat Completions contract used by Sage | Responses requests with `stream: true`, the relevant item/delta events, and terminal events |

Both protocols can stream; streaming text alone does not establish Responses compatibility. A service that accepts a non-streaming Responses request, or only Chat Completions, has not thereby demonstrated support for Sage's streaming Responses path. Changing `base_url` selects a destination, not a protocol conversion.

The [Sage protocol definitions](../../sagents/v2/model/protocols.py) declare these four canonical `provider` values:

- `openai-chat-completions`
- `openai-responses`
- `anthropic-messages`
- `gemini-generate-content`

Use these exact values in new configurations. Service names such as `OpenRouter` and `A2Agent` are not additional built-in protocol IDs. The [Chat Completions implementation](../../sagents/v2/model/plugins/openai_compatible.py) and [Responses implementation](../../sagents/v2/model/plugins/openai_responses.py) are separate. Sage's Responses implementation requests streaming, processes typed events, and detects a stream that ends without a terminal response event. Its default `store: false` is a request setting, not a guarantee about a gateway's retention policy.

## Configure a gateway in Sage

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

For a verified streaming Responses route, change only the protocol selector in this example to `provider: openai-responses` and use that route's documented base URL and model ID. For a direct official service or OpenRouter, substitute the matching settings and environment-variable name from the sections above. Follow the [executable quick start](../../examples/sagents_v2_quickstart.py) and [getting-started guide](../../docs/en/applications/GETTING_STARTED.md) to load and run a manifest. Running an adapted example makes real requests and may incur charges.

**Trust boundary:** Request content and the API key are sent to the configured gateway. Content may include conversation history, tool results, and attachments. Use only a trusted service and a key issued for that service. Do not send an unrelated provider's key to a gateway. Independently check fees, privacy and retention terms, and downstream routing/fallback policies before sending data. HTTPS alone does not establish trustworthy handling.

## Community-submitted third-party gateways: A2Agent

[PR #305](https://github.com/ZHangZHengEric/Sage/pull/305) proposed A2Agent as an alternative Responses-compatible destination. Its author, `A2agent-ai`, disclosed: “I work with A2Agent.” The author did not provide end-to-end compatibility validation and reported that no live model call was made. The PR's formatting check is not evidence of model API compatibility.

This guide also performed no live A2Agent call or end-to-end test. Treat the proposed protocol support as unverified in Sage. Before use, obtain the service's current API documentation and independently verify the exact model, authentication, base URL, streaming Responses events, tool calling, errors, and completion behavior required by your workload. The fictional gateway configuration above illustrates the configuration fields without embedding the submitted service's address.

This community entry is not an official Sage endorsement, a production-availability guarantee, or a trial-credit offer. The contributor's affiliation and the absence of validation remain relevant even if the service publishes API documentation.

## Verification scope

For this documentation change, validation covers Sage source inspection, parsing the example with `SageManifestLoader`, checking the protocol selectors and configuration fields locally, and checking documentation links and the diff. These checks make no inference requests. Official documentation links were manually reviewed on the date above; they can change.

Not tested here: account access, authentication against any service, live streaming, tool execution round trips, multimodal or reasoning behavior, quotas, billing, latency, availability, downstream routing, or privacy-policy enforcement. Before relying on any destination, validate the exact configuration and required features with data you are authorized to send, and record the test date, model, route, and limits.
