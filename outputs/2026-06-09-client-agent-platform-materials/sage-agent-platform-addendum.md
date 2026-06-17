# Sage Agent Platform Addendum for 某某 Discussion

Source deck read: `/Users/zhangzheng/Downloads/AI Agent.pptx`

Recommended placement: insert after the current CMB scenario pages and before the final “Voice & Digital” expansion page.

## Chapter Title

From Use Cases to an Enterprise Agent Platform

### Talk track

现有 PPT 已经讲清楚了 CMB 的客户沟通、RM Copilot、AI Xiaozhao、CRM 嵌入和 IM 外呼线索筛选。新增章节建议把叙事往上抽象：这些不是单点 demo，而是由 Sage 支撑的一套可复用 Agent 平台能力。

## Slide 1

### Title

Sage turns agent pilots into repeatable banking products

### Main message

Most agent pilots stop at a single scenario. Sage is designed to turn successful scenarios into reusable, governed, multi-channel agent products.

### Slide copy

- One platform for customer service, RM assistance, sales activation, operations and internal productivity
- Reusable agent capabilities: planning, execution, memory, tools, skills, sub-agents and self-check
- Built for multi-channel deployment across CRM, IM, web, desktop, browser and workflow automation
- Designed to evolve from “AI assistant” to “AI workforce” without rebuilding the stack

### Visual suggestion

Use a bridge diagram:

`Pilot use case -> Reusable capability layer -> Multi-scenario agent products`

### Speaker note

这一页不要讲技术细节，核心是让高管理解：我们不是只做一个聊天机器人，而是把每个试点沉淀成后续场景可复用的能力。

## Slide 2

### Title

A full execution loop, not just a chat interface

### Main message

Sage agents can plan, act, verify and deliver outputs, which makes them suitable for complex banking workflows where answers alone are not enough.

### Slide copy

- Plan: decompose complex requests into executable steps
- Act: call tools, retrieve knowledge, operate files, trigger workflows and interact with external systems
- Verify: self-check results, recover from errors and keep progress visible
- Deliver: produce artifacts, update systems, send messages and hand off to human teams

### Visual suggestion

Circular loop:

`Plan -> Execute -> Observe -> Self-check -> Deliver`

Put “Human-in-the-loop control” in the center.

### Speaker note

银行里的 Agent 不能只回答“建议怎么做”，更关键的是能不能稳定完成一个过程，比如整理客户信息、生成话术、触达客户、收集反馈、把结果回写到系统。

## Slide 3

### Title

Tool-rich agents with controlled expansion

### Main message

Sage supports a large tool ecosystem while keeping each agent session focused, permission-aware and manageable.

### Slide copy

- Unified tool layer for built-in tools, MCP servers, browser automation, search, image generation, questionnaire flows and IM delivery
- Skills package business know-how as reusable workflows, not scattered prompts
- Tool suggestion selects the most relevant tools for the current task
- Runtime tool expansion lets the agent request additional allowed tools only when needed
- Session-level whitelist keeps expansion inside the agent’s configured permission boundary

### Visual suggestion

Two-layer diagram:

Top: “Agent task context”

Middle: “Tool suggestion + runtime expansion”

Bottom: “Approved capability pool: Banking APIs / CRM / Knowledge Base / Search / IM / Browser / Documents”

### Speaker note

这里可以讲你提到的小亮点：工具很多不是问题，关键是不能一股脑塞给模型。Sage 会先选择当前最相关的工具；如果任务中途需要更多工具，Agent 可以发起扩展，但只能在已授权的范围里扩展。

## Slide 4

### Title

Skills make banking scenarios reusable

### Main message

Sage separates platform capability from scenario knowledge, so new banking products can be assembled faster and maintained more safely.

### Slide copy

- Skills capture domain procedures, templates, scripts and assets
- Scenario logic can be upgraded without changing the core agent runtime
- Sub-agents can specialize by role: RM assistant, compliance reviewer, campaign operator, knowledge researcher
- Reusable skills reduce duplication across branches, channels and business lines

### Visual suggestion

Show a “skill library” feeding multiple agents:

`KYC skill / product recommendation skill / customer follow-up skill / compliance check skill / campaign reporting skill`

### Speaker note

对银行客户很重要的一点是：业务规则和流程经常变。我们不希望每次都重写 Agent。Skill 的价值是把业务动作沉淀成可维护的资产。

## Slide 5

### Title

Enterprise-grade stability and control

### Main message

Sage is designed for production operations where reliability, visibility and governance matter as much as model intelligence.

### Slide copy

- Sandboxed execution options for safer file, command and workflow operations
- Visual Workbench makes agent actions, files, tool outputs and generated artifacts inspectable
- Memory supports session continuity, user-level continuity and workspace retrieval
- Observability and progress feedback help teams inspect execution and improve operations
- Shared service architecture supports web, desktop, CLI and extension deployment

### Visual suggestion

Three columns:

`Safety` / `Visibility` / `Continuity`

Under each column use 2 short bullets.

### Speaker note

这一页是给 IT 和风控的人吃定心丸。不要只说“我们有大模型”，要说平台如何让 Agent 的执行过程可见、可控、可复盘。

## Slide 6

### Title

Why Sage can outperform single-scenario agent competitors

### Main message

Sage’s advantage is not one model or one workflow. It is the compounding effect of reusable tools, skills, memory, orchestration and product surfaces.

### Slide copy

| Dimension | Typical agent solution | Sage-based agent platform |
| --- | --- | --- |
| Scenario coverage | Built for one workflow | Reusable across customer service, RM, sales, operations and back office |
| Tool access | Fixed integrations | Unified tools + MCP + runtime expansion within permissions |
| Business logic | Prompt-heavy | Skills as maintainable workflow packages |
| Complex tasks | Single assistant loop | Planning, sub-agents, self-check and delivery loop |
| Operations | Hard to inspect | Workbench, progress, artifacts and observability |
| Deployment | One channel | Web, desktop, CLI, browser extension, IM and embedded surfaces |

### Speaker note

这一页可以作为竞品差异总结。重点不要攻击竞品，而是强调“单场景 Agent”和“平台型 Agent 产品”的差异。

## Optional Slide 7

### Title

From CMB experience to 某某 opportunities

### Main message

The same platform pattern can be mapped to 某某’s priority domains, starting from high-value, low-risk workflows and scaling into multi-agent operations.

### Slide copy

- Retail banking: next-best-action assistant for relationship managers
- Contact center: case recognition, response drafting and escalation support
- Wealth management: customer profile briefing, product education and follow-up planning
- Marketing and sales: campaign outreach, intent qualification and lead routing
- Operations: document processing, exception handling and internal workflow automation
- IT and transformation: agent factory for controlled experimentation and reuse

### Speaker note

这页适合现场讨论时用。建议把它放成互动页：让客户高管选择他们最想先看的 2-3 个场景，然后我们再往下展开。

## Recommended one-page executive framing

Sage is not positioned as another chatbot layer. It is an enterprise agent platform that converts successful use cases into reusable capabilities. Its differentiation comes from a complete execution loop, large but controlled tool access, skill-based scenario reuse, multi-agent orchestration, visible workbench operations, and multi-channel deployment. For a bank like 某某, this means agent initiatives can start from concrete front-office scenarios, then scale into a governed platform for customer engagement, sales activation, operations and internal productivity.

## Short version for the meeting

If the client asks “what is different about your agent platform?”, answer:

Sage lets us build agents that do more than chat. They can plan, use the right tools, expand capabilities within permission boundaries, delegate to sub-agents, remember context, verify results and deliver artifacts across channels. This is why we can move from a single CMB-style use case to a broader banking agent platform for 某某.
