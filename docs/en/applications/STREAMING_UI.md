---
layout: default
title: Streaming UI in Sage
nav_order: 8
lang: en
ref: v2-applications-STREAMING_UI
parent: Applications
---

{% include lang_switcher.html %}

# Streaming UI: from an answer to an interface

Sage Desktop 2.1 lets an Agent answer with a native interface that appears as it generates: a calculator with editable inputs, a comparison with charts, a checklist with local progress, or a presentation with slides. You ask for the result in ordinary language. You do not need to mention a protocol or ask the Agent to build an application.

The integration uses the official [OpenUI](https://github.com/thesysdev/openui) parser and Sage's own Flutter Glass renderer. OpenUI is MIT-licensed. Sage provides a registered subset of 31 component types; it does not embed the upstream Web renderer or implement the OpenUI Cloud Reports API.

## Turn it on and try it

Open the composer's **+** menu and enable **Prefer interactive UI**. For future chats, use **Settings → General → Interactive UI on by default**. The default starts off; existing chats retain their own preference. Enabling it preloads the built-in Skill and the component contract into the Agent's context. Rendering requires no tool call.

Try these requests:

- “Make a coffee shop calculator: 100 cups per day, price 25, cost 8 per cup, monthly fixed costs 20,000, and 30 operating days. Let me change the inputs and update revenue, costs, profit and margin immediately without submitting.”
- “Compare three plans: free for one person, 99 per month for five people, and 299 for twenty. Show a table and charts for total and per-person cost.”
- “Make a four-week checklist with three tasks per week, weekly tabs and a completion count that updates as I check items.”
- “Create a four-slide coffee shop pitch: cover, market opportunity, financial assumptions and launch plan. Include a chart and keep the slide text concise.”

The preference guides the answer format; it does not force every ordinary question into a form. Tools can still be used when the task independently needs research or file operations.

## How streaming reaches the screen

The Agent writes a fenced `openui` block in its assistant message. The block contains a declarative root and references to registered components. As text chunks arrive, the host passes the growing source to the official parser and maps its intermediate tree to native Flutter widgets. Forward references allow the shell to appear before all content is available.

This is incremental rendering during generation, not an “open a UI” tool invocation at the end. Actual token cadence depends on the provider's chunking and the host's frame scheduling. A provider that sends several tokens together produces a chunk update, not one screen redraw per token.

Sage controls fonts, spacing, input boundaries, Glass materials and light/dark colors. The Agent chooses the component structure, grouping and content within that contract; it does not supply arbitrary CSS or executable JavaScript. For the current signatures and implementation boundary, see the [integration reference](https://github.com/ZHangZHengEric/Sage/blob/main/app/v2/desktop/README.md#openui).

## Local interaction and assistant follow-up

A calculator should recalculate locally. `Computed` binds supported operations to input values, and dependent metrics, charts and progress indicators use those bindings. A correctly bound coffee calculator updates monthly profit from 31,000 to 82,000 when daily volume changes from 100 to 200 with the other assumptions above unchanged. It does not need a new model response.

Checking a task, switching tabs, expanding a section or inspecting a chart is also local. A submission button has a different role: it sends selected values back as the next user turn for an explicit assistant follow-up. It is not a substitute for local arithmetic. Unsupported formulas must be disclosed instead of showing a fixed number as if it were reactive.

## Validation, revisions and the sidebar

An intermediate preview can be incomplete while output is streaming. Final output goes through the shared output self-check pipeline before run completion: official parser and component validation, dependency checks and native arithmetic probes at defaults and selected input boundaries. Self-check uses rules and parsing only; it makes no model requests. Independent validators run concurrently and report errors together. Each block must be parsed before its numeric probes run; shared parser IPC remains serialized to prevent crossed responses. Only the latest assistant response body is inspected for OpenUI blocks. Ordinary text bypasses these checks; historical messages, reasoning and tool results are not validation targets. History is used only to count repair attempts. Concrete defects go back to the generating model for a complete replacement, with at most three UI-bearing generations per turn. The probes do not exhaust all input combinations or infer the intended business formula; passing them does not guarantee pixel-level layout or business-semantic correctness. A model response can still remain invalid; a read-only preview is not a successfully completed interface.

When a later UI replaces an earlier draft in the same run, the latest draft stays in the conversation body. Earlier versions become one-line entries in the Process Panel, with sidebar access for inspection. **Open in sidebar** provides more room for the current interface and shares its local input state with the conversation view.

## Presentations and editable export

A presentation uses a `Deck` root containing slides. The native 16:9 preview appears during generation. In the sidebar, slide thumbnails provide navigation beside the current slide; presentation controls support fullscreen viewing. After validation, the host exports the same document to editable PPTX without asking the Agent to write a file through a tool.

Slides support text, metrics, tables and literal-data charts within explicit content limits. PPTX import, freeform slide editing, animations and arbitrary Web components are outside this release's scope. Native preview and PPTX use a shared layout specification, although fonts and rendering can vary between PowerPoint and Keynote.

## Availability and useful checks

The feature belongs to Desktop 2.1; it is not a promise that every Sage host renders OpenUI. Desktop installers include Node.js and the parser bundle. Source runs require Node.js 22+ in addition to the Desktop setup described in the [Desktop guide](DESKTOP.md).

When trying an interface, check both its appearance and its behavior: change an input, switch a tab, hover a chart, inspect a replaced draft, and open an exported deck. Generation, validation, local interaction and export are separate checks. Model quality helps, but a valid-looking preview alone does not establish that all four work.

See the [2.1.0 release notes](https://github.com/ZHangZHengEric/Sage/blob/main/release_notes/v2.1.0.md) for package contents and compatibility limits.
