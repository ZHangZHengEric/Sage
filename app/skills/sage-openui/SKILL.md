---
name: sage-openui
description: Present answers as streaming native interactive UI or presentations in Sage Desktop v2. Use when structured visual presentation or user interaction helps accomplish the task.
---

# Sage OpenUI

## Capability boundary

Interactive UI is a built-in answer format. Generate it directly in an assistant message inside a fenced code block whose language is exactly `openui`. The host parses incoming message chunks with the official parser and renders native Flutter Glass components.

Rendering is not a tool operation and has no tool-loading prerequisite. Use tools only for operations independently required by the user's task. Do not infer a file-development workflow from a request for interactive presentation or from earlier conversation patterns. When this Skill is preloaded, its instructions and the system-provided component contract are ready to use.

## Presentation principles

Choose the format that best serves the user's intent, respecting the chat's UI preference and explicit requests. Use interaction when it helps the user explore or supply information. Ordinary questions can remain prose.

Let the UI carry the answer. Avoid repeating its information in ordinary text. Include outside prose only for a necessary conclusion, limitation or next step. Do not add subtitles or field descriptions unless requested.

Make hierarchy reflect the task. Group related content, avoid unnecessary nesting, keep required inputs visible, and place the primary action after its inputs. Use concise labels. The native renderer supplies typography, spacing, glass materials and light/dark colors; stay within its supported visual contract.

## Protocol and interaction

The host supplies current component signatures, positional argument order and limits in system context. [components.md](references/components.md) is the generated reference for the same contract. Use only registered declarative components and supported literals or references; do not invent properties, executable expressions or upstream capabilities.

Define the root first and referenced content afterwards so the structure can appear progressively. Children are arrays even when there is only one child. Use stable, unique field names and action identifiers. Match computations to field types: count checkbox selections explicitly before numeric arithmetic, and use a completion ratio for completion percentages. Bind dependent metrics, charts and progress indicators to the same calculation; formatting does not convert units. Supply correctly typed values within declared limits.

When displayed results depend on editable inputs, express every dependent result and chart series through supported local computations and numeric bindings. Editing an input must update those results immediately; submission is a separate follow-up interaction, never the recalculation mechanism. Computed is already a visible result card; place it directly in the layout. Metric accepts fixed text, not a Computed component reference. Static metrics and literal chart values represent fixed facts, not input-dependent results. Do not approximate an unsupported computation with a result that appears live but does not update correctly. Disclose a capability limitation concisely when the contract cannot express the requested behavior.

Input fields do not require a submission button. Omit submission controls when the task is satisfied by local interaction. Add a button only for a task-required handoff to the assistant, and make that handoff clear in its label. Buttons submit the current form as the next user turn. They do not directly invoke commands, network requests or Agent tools. Finish the message after an input form and wait for the user. Generation, replay and opening a surface must not trigger external actions. Inputs become interactive only after complete validation and run completion.

## Presentations

Use a Deck root for presentations. Keep content concise, organize it into slides within the generated limits, and choose supported layouts and accents to express the hierarchy. Native controls provide navigation, presentation mode and editable PPTX export after validation; these are host capabilities rather than Agent tool workflows.

Upstream: https://github.com/thesysdev/openui (MIT). Sage uses the official parser with its own native renderer and a documented component subset.

## Output self-check

Before finishing, verify that formulas, units and dependencies express the user's request, that editable inputs update every dependent result locally, and that declared input ranges keep those results meaningful. Protocol validity alone does not establish correctness. The host runs deterministic protocol validation and bounded native arithmetic probes through the output self-check pipeline. When it returns concrete defects, correct their underlying cause and emit one complete replacement using the same contract. Do not hide a defect with prose, a frozen result, or an unnecessary model-submission action. Self-check makes no model calls. Passing these bounded checks does not prove that every business assumption or formula matches the user's intent.
