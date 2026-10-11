# Choosing free models on OpenRouter

[Knowledge hub](../README.md)

Documentation manually checked: **2026-10-11**. This is a decision guide, not a model catalog or a promise of future availability. No inference requests, account checks, or performance tests were run.

## Choose the kind of selection you need

- **A particular model:** find its exact listed `:free` ID. A free variant is a separate catalog entry with its own pricing, context window, and endpoints. Adding `:free` to an arbitrary model ID does not create free access; the variant must exist. Use the free entry's details rather than assuming the paid entry's capabilities apply. [Free variant documentation](https://openrouter.ai/docs/guides/routing/model-variants/free)
- **An interchangeable model for an experiment:** `openrouter/free` is a router, not a fixed model. It filters available free models for the request's required capabilities and randomly selects one. The response's `model` field identifies what actually answered. Record that ID when comparing results; repeated requests need not use the same model. [Free router documentation](https://openrouter.ai/docs/guides/routing/routers/free-router)

Start discovery with the [OpenRouter models page with a zero-price filter](https://openrouter.ai/models?max_price=0). Confirm the filter is active in the page and open the candidate's details before choosing it. This guide does not reproduce or certify the page's current results.

## Decision checklist

1. **Match the task.** Check the exact entry's input and output modalities, context window, output limit, and supported parameters. Tool calling, image input, and structured output are separate requirements. A related model's support is not enough. [Models documentation](https://openrouter.ai/docs/guides/overview/models)
2. **Check the whole price.** Zero `prompt` and `completion` prices establish only those token prices. Inspect applicable request, image, search, reasoning, cache, and conditional pricing fields, plus any separately enabled services. Do not turn a two-field zero-price check into a guarantee that every operation is free. [Pricing schema](https://openrouter.ai/docs/guides/overview/models)
3. **Check access and capacity.** Free does not mean account-free or key-free API access: the documented API flow uses an API key. Free-model request limits and account conditions still matter; a negative account balance can block free requests. Consult the live limits documentation and your own account before planning a workload. [Free router usage](https://openrouter.ai/docs/guides/routing/routers/free-router), [limits documentation](https://openrouter.ai/docs/api_reference/limits)
4. **Read `null` in context.** It is not a universal promise of unlimited use. For example, a null key credit limit means no cap at that particular key-limit layer; account, organizational, and request-rate restrictions can still apply. A model's `per_request_limits: null` does not override account-wide limits. [Key limits](https://openrouter.ai/docs/api_reference/limits), [model schema](https://openrouter.ai/docs/guides/overview/models)
5. **Review data handling.** Providers have their own training, logging, and retention policies. OpenRouter documents separate training-routing settings for free and paid models. Opting out of provider training is not the same as establishing a retention policy, and it does not determine OpenRouter's own handling. Check the actual provider and any third-party tools before sending private data. [Provider logging documentation](https://openrouter.ai/docs/guides/privacy/provider-logging)
6. **Decide what happens when it fails.** Free-model availability and latency can vary. For experiments, tolerate a pause or retry. For repeatable evaluations, select a specific listed variant and record it. For production, decide acceptable outages and costs explicitly rather than silently switching to a paid fallback. [Free router limitations](https://openrouter.ai/docs/guides/routing/routers/free-router)

## Discovery has a modality default

The Models API defaults to models that produce text. To discover across output types, use the documented `output_modalities=all` parameter, or specify the output modality you need. A default response is therefore not a complete cross-modality inventory. This filtering concerns output capability; inspect input modalities separately. [Models query parameters](https://openrouter.ai/docs/guides/overview/models)

Before adoption, revisit the linked official sources and record your chosen ID, review date, required features, privacy decision, and failure behavior. Keep credentials out of repository notes. Availability, limits, pricing, and policies can change after this manual review.
