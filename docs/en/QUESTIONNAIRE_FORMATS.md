---
layout: default
title: Questionnaire Formats
nav_order: 8.5
description: "YAML and XML+JSON protocols for Sage Inline Questionnaires"
lang: en
ref: questionnaire-formats
---

{% include lang_switcher.html %}

# Questionnaire Formats Supported by Sage

Sage Self-check supports two Inline Questionnaire encodings:

1. fenced YAML
2. an XML element containing a JSON object

Both encodings are supported formats. XML+JSON is not deprecated and has no migration deadline.

An Inline Questionnaire is a text protocol inside an assistant message. It is separate from the `questionnaire` tool used by Sage Server Web, which has its own session, submission API, and UI card and does not use the inline tags described here.

## Registered Questionnaire Names

Both encodings use these five registered names:

| Name | Typical use |
| --- | --- |
| `yiii-questionnaire` | Yiii integration |
| `movo-questionnaire` | Movo and Sage Desktop compatibility flows |
| `ling-questionnaire` | Ling integration |
| `sage-questionnaire` | Sage namespace |
| `questionnaire` | Generic format without a product prefix |

Unknown prefixes such as `foo-questionnaire` are not registered protocol names. Self-check requires the response to be rewritten with one of the names above.

Response tags append `-response` to a registered name, for example `yiii-questionnaire-response` and `questionnaire-response`. Responses continue to use XML+JSON rather than fenced YAML.

## Fenced YAML

Fenced YAML is intended for direct model or human authoring. A non-empty ordinary-prose explanation must appear before the questionnaire; the questionnaire block cannot be the whole reply.

The current facts and the decision boundary have been summarized.

```yiii-questionnaire
title: "Project confirmation"
questions:
  - type: single_choice
    text: "How should the next step proceed?"
    options:
      - "Continue"
      - "Revise"
    default: "Continue"
    allow_other: true
  - type: multi_choice
    text: "Which parts need revision?"
    options:
      - "Content"
      - "Style"
    default: []
  - type: free_text
    text: "What other constraints apply?"
    default: ""
```

The fence name may be replaced with any registered name. Opening and closing fences must each occupy their own line, and the closing fence cannot be shorter than the opening fence.

### Top-Level Fields

- `title`: required non-empty string.
- `questions`: required non-empty array.
- `id`, `subtitle`, field descriptions, and all other extra fields are forbidden.

### Question Rules

Every question must contain `type`, a non-empty `text`, and `default`.

| `type` | `options` | `default` | `allow_other` |
| --- | --- | --- | --- |
| `single_choice` | Required non-empty string array | Must equal one option | Optional boolean |
| `multi_choice` | Required non-empty string array | String array whose values are all listed options | Optional boolean |
| `free_text` | Forbidden | String, which may be empty | Forbidden |

The fenced payload must use block-style YAML. JSON objects, XML, nested code fences, and unknown fields fail Self-check.

## XML+JSON

XML+JSON is intended for existing generators, stored conversations, and clients that still depend on this protocol. It remains supported.

```xml
<yiii-questionnaire>{"title":"Project confirmation","questions":[{"type":"single_choice","text":"How should the next step proceed?","options":["Continue","Revise"],"default":"Continue"}]}</yiii-questionnaire>
```

The opening and closing elements must use the same registered name, and their content must be a JSON object. Self-check preserves the existing compatibility rules for each alias: `yiii-questionnaire` continues to validate its title, question types, and defaults, while the other aliases retain existing extension fields and `{value, label}` option objects.

XML+JSON is not automatically converted to YAML. A repair may remain XML+JSON or rewrite the same questionnaire name as fenced YAML.

## Response Format

Inline Questionnaire responses continue to use XML+JSON:

```xml
<yiii-questionnaire-response>{"id":"q_demo","title":"Project confirmation","answers":[{"index":0,"type":"single_choice","question":"How should the next step proceed?","answer":"Continue","answers":["Continue"]}]}</yiii-questionnaire-response>
```

The submitting client defines the detailed answer fields. Self-check requires a top-level `answers` array.

## Self-check Behavior

Self-check inspects only the latest non-empty assistant reply after the current user message.

- Valid fenced YAML and valid XML+JSON both pass.
- An invalid questionnaire creates a user-hidden runtime diagnostic and requires the model to emit the complete questionnaire again.
- `self_check_required_structured_tags` retains the required questionnaire name so a repair cannot omit the questionnaire and return explanation text alone.
- A repair may switch encodings while retaining the same name, such as replacing invalid YAML with valid XML+JSON.
- An unknown prefix requires any registered name and is not persisted as an impossible repair requirement.

Self-check does not infer whether prose is asking a question from punctuation or natural-language keywords. Whether a questionnaire is required remains the responsibility of the Agent Prompt, Skill, and business workflow.

## Client Rendering Support

Passing Self-check means the runtime protocol is valid. It does not guarantee that every client renders the encoding as an interactive card.

| Client | Fenced YAML | XML+JSON | `questionnaire` tool call |
| --- | --- | --- | --- |
| Sage Desktop | Not currently rendered as an inline card | `movo`, `ling`, `sage`, and unprefixed | Not handled by this inline renderer |
| Sage Server Web | Not currently rendered as an inline card | Not currently rendered as an inline card | Supported |
| Yiii Flutter | `yiii-questionnaire` | All five registered names | Not handled by this inline renderer |

Before generating a questionnaire, confirm that the target client supports the selected encoding and name. Self-check support alone does not imply display or submission support in that client.

## Common Errors

### Sending Only the Questionnaire Block

Fenced YAML requires ordinary prose before the block. Message-wrapping requirements for XML+JSON are defined by the relevant Agent Prompt and client contract.

### A Single-Choice Default Outside Its Options

```yaml
type: single_choice
text: "How should the next step proceed?"
options:
  - "Continue"
  - "Revise"
default: "Later"
```

Change `default` to `Continue` or `Revise`.

### Putting JSON Inside the YAML Fence

The fence named `yiii-questionnaire` must contain block-style YAML. Use the matching XML+JSON format when JSON is required.
