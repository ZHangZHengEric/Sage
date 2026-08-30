---
layout: default
title: Questionnaire Delivery Methods
nav_order: 8.5
description: "Protocols, lifecycle, and client integration for Sage Inline Questionnaires and questionnaire_async"
lang: en
ref: questionnaire-formats
---

{% include lang_switcher.html %}

# Questionnaire Delivery Methods in Sage

This document covers the questionnaire methods that Sage currently supports without blocking a runtime thread while waiting for an answer:

1. Inline Questionnaires in assistant text;
2. the `questionnaire_async` tool.

The former synchronous `questionnaire` tool has been removed from the Tool catalog; historical messages remain renderable for compatibility.

## Overview

| Method | Transport | Primary use | Renderer | How the answer returns |
| --- | --- | --- | --- | --- |
| fenced YAML | assistant `content` | Newly generated generic Inline Questionnaires | Client parses message content | `<questionnaire-response>` JSON in the next user message |
| XML+JSON | assistant `content` | Runtime recovery questionnaires and stored Sage conversations | Client parses message content | Matching `*-questionnaire-response` JSON |
| `questionnaire_async` | assistant tool call + tool result | Runtime validation and normalization before ending the current execution turn | Client correlates the tool call and result | `<questionnaire-response>` JSON in the next user message |

## Inline Questionnaire

An Inline Questionnaire is a text protocol inside an assistant message, not a tool call. A client must detect protocol blocks before ordinary Markdown rendering and preserve the original order of text surrounding each block.

### Canonical format for new messages

New code emits unprefixed `questionnaire` fenced YAML. A non-empty ordinary-prose explanation must precede the questionnaire.

````markdown
The maximum loop count for this turn (50) has been reached, so the task is paused.

```questionnaire
title: Task paused
questions:
  - type: single_choice
    text: Continue the current task?
    options:
      - Continue
    default: Continue
```
````

Protocol boundaries:

- the canonical opening fence occupies its own line and is named exactly `questionnaire`; Sage compatibility reads also accept `sage-questionnaire`;
- the opening fence uses at least three backticks;
- the closing fence occupies its own line and is not shorter than the opening fence;
- the payload is block-style YAML, not JSON;
- nested code fences are forbidden;
- a fenced questionnaire cannot be the entire assistant message.

Questionnaire examples inside ordinary fenced code, inline code spans, or four-space indented code blocks remain Markdown code and do not activate an interactive questionnaire.

### fenced YAML fields

Only these top-level fields are allowed:

```yaml
title: non-empty string
questions: non-empty array
```

Do not add top-level `id`, `ui_text`, `timeout_seconds`, `subtitle`, or description fields.

Every question contains `type`, non-empty `text`, and `default`.

| `type` | `options` | `default` | `allow_other` |
| --- | --- | --- | --- |
| `single_choice` | Required non-empty string array | Must equal one option | Optional boolean |
| `multi_choice` | Required non-empty string array | String array whose values all occur in `options` | Optional boolean |
| `free_text` | Forbidden | String, which may be empty | Forbidden |

Strict fenced YAML does not accept aliases such as `multiple_choice` or `text`, and it does not accept `{value, label}` option objects.

### Inline response protocol

The request uses Markdown + YAML, but the response remains JSON inside an XML-style element. An unprefixed request has an unprefixed response:

```xml
<questionnaire-response>{"type":"questionnaire_response","questionnaire_id":"MESSAGE_ID_q1","status":"submitted","answers":[{"question_id":"q1","question":"Continue the current task?","type":"single_choice","answer":"Continue","value":"Continue","label":"Continue"}]}</questionnaire-response>
```

The client generates repeatable questionnaire and question identifiers:

- derive the questionnaire ID from `message_id` and the protocol-block ordinal;
- fenced YAML has no question `id`, so assign `q1`, `q2`, and so on;
- IDs must remain stable when the same message is rendered again;
- `status` is currently `submitted`;
- the top-level `answers` field is an array.

Sage Desktop emits `answer`, `value`, and `label` for single choice; `answer`, `values`, and `labels` for multiple choice; and a string `answer` for free text.

### XML+JSON and alias boundaries

The Sage Runtime still uses unprefixed XML+JSON for repeat-execution recovery so that stable question IDs and localized UI text remain available:

```xml
<questionnaire>{"title":"Execution path is repeating","questions":[{"id":"loop_recovery_action","type":"free_text","text":"Please describe how you want me to proceed","default":""}]}</questionnaire>
```

Sage Desktop and Server Web render only these request names and their matching `-response` names:

| Name | Sage client status |
| --- | --- |
| `questionnaire` | Canonical name |
| `sage-questionnaire` | Sage namespace read compatibility |

`yiii-questionnaire`, `movo-questionnaire`, and `ling-questionnaire` remain ordinary Markdown in Sage clients and are not parsed as interactive questionnaires.

Sage Self-check still reads five registered names:

| Name | Status |
| --- | --- |
| `questionnaire` | Canonical name for new messages |
| `yiii-questionnaire` | Backend registration for Yiii's own client |
| `movo-questionnaire` | Backend registration for Movo's own client |
| `ling-questionnaire` | Backend registration for Ling's own client |
| `sage-questionnaire` | Sage namespace read compatibility |

Example:

```xml
<sage-questionnaire>{"title":"Project confirmation","questions":[{"type":"single_choice","text":"How should the next step proceed?","options":["Continue","Revise"],"default":"Continue"}]}</sage-questionnaire>
```

Opening and closing elements use the same name. A response appends `-response` to the request name, and both element names must match exactly. Unknown names such as `foo-questionnaire` and `questionnaire-response-extra` are not registered.

Backend registration does not define the Sage client compatibility surface. Other product clients may reuse Sage's parser and card implementation, but should register only the unprefixed name and their own product namespace.

### Self-check

Self-check inspects the latest non-empty assistant reply after the current user message:

- valid fenced YAML and valid XML+JSON pass;
- an invalid questionnaire creates a user-hidden diagnostic and requires the model to emit the complete questionnaire again;
- a repair may switch encodings while retaining a registered name;
- Self-check validates the protocol but does not prove that a target client renders it;
- Self-check does not infer questionnaire requirements from question marks or natural language.

### Client requirements

1. Scan for protocol blocks before Markdown normalization and rendering.
2. Parse YAML safely without custom types.
3. Preserve message order when producing Markdown, questionnaire, and response segments.
4. Fall back to the original text on parse failure; never drop it silently.
5. Enable submission only for the latest non-read-only assistant message.
6. Lock the form after submission and retain a readable answer in the user message.
7. Do not rewrite `questionnaire` based on a product name.
8. Light and dark themes are presentation concerns, not transport fields.

Sage Desktop and Server Web reference implementation:

- parser and response builder: [inlineQuestionnaire.js](../../app/desktop/ui/src/utils/inlineQuestionnaire.js)
- segmented renderer: [InlineQuestionnaireRenderer.vue](../../app/desktop/ui/src/components/chat/InlineQuestionnaireRenderer.vue)
- interactive card: [InlineQuestionnaireCard.vue](../../app/desktop/ui/src/components/chat/InlineQuestionnaireCard.vue)
- protocol tests: [inlineQuestionnaire.spec.js](../../app/desktop/ui/src/utils/__tests__/inlineQuestionnaire.spec.js)

Server Web provides the same parser, renderer, card, and protocol tests under `app/server/web`; both Sage clients keep identical aliases and strict validation rules.

## `questionnaire_async`

`questionnaire_async` immediately validates questionnaire arguments. It does not wait for user submission, poll a backend, or create a separate submission session.

### Arguments

```json
{
  "title": "Continue execution",
  "questions": [
    {
      "id": "action",
      "type": "single_choice",
      "text": "Continue the current task?",
      "options": [
        {"value": "continue", "label": "Continue"}
      ],
      "default": "continue",
      "allow_other": false
    }
  ]
}
```

`title` is optional. `questions` is a required non-empty array.

| Input field | Rule |
| --- | --- |
| `id` | Optional; defaults to `q1`, `q2`; cannot be duplicated |
| `type` | `single_choice`, `multiple_choice`, `multi_choice`, `text`, or `free_text` |
| `text` / `title` | At least one is non-empty; normalized to `text` |
| `options` | Required for choice questions; strings and `{value, label}` objects are accepted |
| `default` | Optional; must match the normalized type and option values |
| `allow_other` | Optional boolean |

Normalization:

- `multiple_choice` → `multi_choice`;
- `text` → `free_text`;
- a string option → `{value: text, label: text}`;
- missing defaults become an empty string for single choice/free text and an empty array for multiple choice.

### Success result

```json
{
  "success": true,
  "status": "awaiting_user_input",
  "validation_passed": true,
  "title": "Continue execution",
  "question_count": 1,
  "questions": [
    {
      "id": "action",
      "type": "single_choice",
      "text": "Continue the current task?",
      "options": [
        {"value": "continue", "label": "Continue"}
      ],
      "default": "continue",
      "allow_other": false
    }
  ],
  "should_end": true,
  "message": "Questionnaire started and waiting for user input, with 1 questions."
}
```

After success, SimpleAgent ends the current execution turn. Sage clients read the normalized `title` and `questions` from the tool result, render the same questionnaire card, and wrap the answer in an unprefixed `<questionnaire-response>`; that user message starts the next execution turn.

### Validation failure

A failure uses the standard tool-error shape:

```json
{
  "success": false,
  "status": "error",
  "error_code": "INVALID_ARGUMENT",
  "validation_passed": false,
  "errors": [
    {
      "code": "questionnaire.start.default_type_invalid",
      "path": "questions[1].default",
      "message": "localized error message",
      "details": {}
    }
  ]
}
```

A client correlates the assistant tool call `id` with the tool result `tool_call_id`. Only normalized `questions` from a successful result should become an interactive form. A failed result should expose the argument error and must not open a submittable questionnaire.

### Answer boundary

The current Runtime defines no dedicated submission endpoint, polling flow, timeout, or server-enforced answer envelope for `questionnaire_async`. Sage Desktop and Server Web always send generic `<questionnaire-response>` JSON and use `displayContent` for the readable answer; the Runtime processes it as the next user message.

Reference implementation:

- argument validation and normalization: [questionnaire_tool.py](../../sagents/tool/impl/questionnaire_tool.py)
- stopping the current turn after success: [simple_agent.py](../../sagents/agent/simple_agent.py)
- tool tests: [test_questionnaire_tool.py](../../tests/sagents/tool/impl/test_questionnaire_tool.py)

## Choosing a method

| Requirement | Recommended method |
| --- | --- |
| Place a questionnaire at a specific location in assistant prose | fenced YAML Inline Questionnaire |
| Read stored Sage questionnaire messages | Unprefixed or `sage-` XML+JSON compatibility reader |
| Let the model construct tool arguments and have the Runtime normalize them | `questionnaire_async` |
| A non-Sage client has no tool-call questionnaire renderer | fenced YAML Inline Questionnaire |

Do not conflate Self-check support, tool-argument validation, and client rendering. Self-check, `questionnaire_async`, and each client own those responsibilities separately.
