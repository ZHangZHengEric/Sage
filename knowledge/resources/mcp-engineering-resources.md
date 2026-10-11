# MCP Engineering Resources

A practical reading guide for developers building MCP servers or connecting external tools to an agent. Start with the problem you need to solve, then use the linked project's own documentation. Each entry explains its fit and limits. For Sage configuration, use [Tools, Skills and MCP](../../docs/en/MCP_SERVERS.md).

Last source check: **2026-10-11**. These are documentation checks, not compatibility certifications or a benchmark of the projects.

## Choose a starting point

| Your task | Start with | Check before integrating |
| --- | --- | --- |
| Understand a protocol mismatch | MCP specification | The protocol revision actually used by both peers |
| Build your first server | Official server tutorial, then a language SDK | Installed package version and the host's supported transport |
| Expose an existing Python service | Python SDK or Prefect FastMCP | Framework API, lifecycle, and authentication requirements |
| Debug discovery or a tool call | MCP Inspector | The same endpoint, transport, credentials, and arguments as the failing client |
| Deploy a remote server | Transport, authorization, and security references | Network exposure, token audience, least privilege, and consent |
| Trace failures across services | OpenTelemetry MCP conventions | Convention maturity, instrumentation coverage, and sensitive-data handling |

## Versions and Sage integration

Keep three version numbers separate: **Sage framework version**, **MCP protocol revision**, and **language SDK package version**.

At this check, Sage's [requirements](https://github.com/ZHangZHengEric/Sage/blob/main/requirements.txt) pin `mcp==1.28.1` and `fastmcp==3.4.2`. Its [v2 session adapter](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/tool/_mcp_session.py) imports the official SDK's `ClientSession` and transport clients. The [v1 connection pool](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v1/tool/mcp_connection_pool.py) also contains a Prefect `fastmcp.Client` integration. A v1 example does not establish how the v2 bridge works.

The protocol's `latest` pages currently resolve to revision **2026-07-28**. Upstream SDK `main` documentation can describe APIs newer than Sage's pinned packages. Read version-matched documentation before copying examples. This guide does not recommend upgrading Sage's dependencies or claim compatibility with every current protocol feature.

## Protocol and implementation resources

### 1. MCP specification

[Official specification](https://modelcontextprotocol.io/specification/2026-07-28)

- **Problem solved:** Defines protocol messages, capabilities, and requirements that implementations must agree on.
- **Choose it when:** A client and server disagree about behavior, or you are deciding which features to implement.
- **Tradeoff:** Normative requirements are more detailed than a getting-started guide. Read the revision matching your integration.
- **Sage connection:** Use it to investigate interoperability; protocol documentation alone cannot establish Sage feature support.
- **Last checked:** 2026-10-11.

### 2. Official MCP Python SDK

[Repository and documentation entry point](https://github.com/modelcontextprotocol/python-sdk) · [v1 to v2 migration guide](https://py.sdk.modelcontextprotocol.io/migration/)

- **Problem solved:** Implements Python clients, servers, and transport handling.
- **Choose it when:** You want the protocol project's Python implementation or need to understand Sage's SDK calls.
- **Tradeoff:** Match imports and examples to the installed major version. Current upstream documentation uses `MCPServer`; SDK v1 examples use `mcp.server.fastmcp.FastMCP`.
- **Sage connection:** Sage v2's bridge uses this package. “Sage v2” does not mean “Python SDK v2.”
- **Last checked:** 2026-10-11.

### 3. Official MCP TypeScript SDK

[Repository and versioned documentation links](https://github.com/modelcontextprotocol/typescript-sdk)

- **Problem solved:** Provides TypeScript server/client libraries, transport support, and authentication helpers.
- **Choose it when:** Your service or integration is built in TypeScript.
- **Tradeoff:** Upstream v2 documentation uses split server/client packages; v1 examples use `@modelcontextprotocol/sdk`. Follow the appropriate documentation branch.
- **Sage connection:** An independent server-building option. A TypeScript server still needs a transport and protocol revision compatible with the Sage host you deploy.
- **Last checked:** 2026-10-11.

### 4. Prefect FastMCP

[Official FastMCP documentation](https://gofastmcp.com/getting-started/welcome)

- **Problem solved:** A Python framework for declaring servers and connecting clients, with schema generation and framework-level lifecycle support.
- **Choose it when:** Its higher-level API fits your service and you want its framework conventions.
- **Tradeoff:** The standalone `fastmcp` package is distinct from SDK v1's `mcp.server.fastmcp`. Its documentation follows `main` and explicitly warns that some features may precede stable releases.
- **Sage connection:** Relevant to the v1 client path and independently authored servers; it is not the implementation of Sage v2's session adapter.
- **Last checked:** 2026-10-11.

### 5. Official server-building tutorial

[Build an MCP server](https://modelcontextprotocol.io/docs/2026-07-28/develop/build-server)

- **Problem solved:** Walks from tool implementation to connecting a host, using a small weather service.
- **Choose it when:** You need an end-to-end first example before designing your own server.
- **Tradeoff:** The tutorial's host setup is not a Sage configuration recipe. Current Python examples target newer SDK APIs. For stdio, send diagnostic logs to stderr so stdout remains the protocol channel.
- **Sage connection:** Apply the server concepts, then follow Sage's own connection instructions and dependency constraints.
- **Last checked:** 2026-10-11.

## Testing and operational boundaries

### 6. MCP Inspector

[Official Inspector guide](https://modelcontextprotocol.io/docs/2026-07-28/tools/inspector)

- **Problem solved:** Tests and debugs MCP servers independently of an agent's model-driven workflow, with graphical and command-line clients.
- **Choose it when:** You need to inspect discovery or reproduce a specific tool call directly.
- **Tradeoff:** A successful Inspector call does not test Sage's policy or the model's tool selection. Calls can have real effects; use test data and review secret storage before providing credentials.
- **Sage connection:** Helps separate server/transport failures from host integration failures.
- **Last checked:** 2026-10-11.

### 7. MCP transport specifications

[Transport overview](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports) · [Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)

- **Problem solved:** Explains how stdio and HTTP carry protocol messages and the security requirements for HTTP endpoints.
- **Choose it when:** Selecting a local subprocess or remote deployment, or debugging framing and connection behavior.
- **Tradeoff:** Transport support varies by host and revision. Streamable HTTP can use SSE responses; this does not make it the older standalone SSE transport. Validate origins and avoid unnecessarily exposing local listeners.
- **Sage connection:** Current Server accepts `sse` and `streamable_http` and rejects tenant stdio commands; Desktop may use stdio. See [Sage's host-specific guide](../../docs/en/MCP_SERVERS.md).
- **Last checked:** 2026-10-11.

### 8. MCP authorization specification

[Official authorization specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)

- **Problem solved:** Defines HTTP authorization roles and flows for access to protected MCP servers.
- **Choose it when:** Implementing a protected remote service or a client's authorization support.
- **Tradeoff:** This is not an authorization-server implementation or a general stdio credential recipe. OAuth access scopes and a host's tool-execution permissions are separate controls.
- **Sage connection:** Sage's documented `api_key` bridge adds a Bearer token. That configuration does not by itself establish complete OAuth discovery or interactive authorization support.
- **Last checked:** 2026-10-11.

### 9. MCP security best practices

[Official security guidance](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices)

- **Problem solved:** Explains attacks and mitigations including confused-deputy behavior, token passthrough, SSRF, and compromised local servers.
- **Choose it when:** Reviewing a proxy, network boundary, credential flow, or untrusted server installation.
- **Tradeoff:** Apply the guidance to your threat model; reading the checklist does not audit a deployment. A human approval prompt cannot compensate for excessive process or network privileges.
- **Sage connection:** Review the host, remote service, and underlying resource permissions together.
- **Last checked:** 2026-10-11.

### 10. OpenTelemetry MCP semantic conventions

[Maintained MCP conventions](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/mcp.md)

- **Problem solved:** Defines MCP-oriented spans, metrics, and attributes for instrumentation.
- **Choose it when:** You need consistent operation-level telemetry across a client and server.
- **Tradeoff:** Marked **Development** at this check. Some examples reference older protocol revisions; assess version fit. Argument/result capture is opt-in and may expose sensitive content. This is an instrumentation specification, not an evaluation suite.
- **Sage connection:** A reference for future instrumentation work; inclusion does not claim that Sage already emits these conventions.
- **Last checked:** 2026-10-11.

## Keep approval and enforcement separate

Treat these as distinct checks:

1. **Remote access:** Is the credential valid for this service, resource, and operation? Use the authorization and security references above.
2. **Host permission:** Is this actor allowed to invoke this tool? Sage's [MCP bridge](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/tool/plugins/mcp.py) marks external tools as `WRITE`, requires `tool.external_side_effect`, and sets `requires_approval=True`.
3. **Human decision:** Does the configured approval flow present the intended tool and arguments? Sage's default `CONFIGURED` policy asks after scope checks; host strategy and approval memory can change the interaction. See [Sage authorization guidance](../../docs/en/MCP_SERVERS.md).
4. **Resource boundary:** Does the process or remote service enforce the actual filesystem, network, and tenant limits? Approval does not create isolation. Sage’s local-workspace sandbox does not isolate host Python plugins or MCP services. See [Sage's local sandbox security model](../../docs/en/architecture/sagents-v2-local-sandbox-security.md).

Tool descriptions and annotations are untrusted inputs unless their source is trusted. The [MCP specification](https://modelcontextprotocol.io/specification/2026-07-28) calls for consent and access controls but states that the protocol cannot enforce those principles itself.

## A small integration checklist

The following is a suggested review procedure, not a compatibility test report:

- Record the host, server, SDK, and protocol versions alongside the transport.
- Discover tools and review the actual names, schemas, and expected effects.
- Exercise one bounded call with test data, then test an invalid argument and denied access.
- Check what happens on timeout or cancellation. Sage's [bridge](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/tool/plugins/mcp.py) treats a missing call result as an uncertain side effect; reconcile remote state before retrying a possible write.
- Verify cleanup and credential revocation separately. Closing a client session does not prove that remote work stopped.
- Evaluate task outcomes separately from connection success: did the right tool run, with the intended arguments, and produce a verifiable result?

## Selection and maintenance criteria

Resources belong here when they have a clear engineering use, an identifiable official owner, accessible primary documentation, and an explicit relationship to the integration problem. Check versions, security guidance, release status, and links when updating an entry. Remove or qualify entries whose ownership, maintenance, or claims can no longer be verified.

The ordering follows an implementation workflow. Inclusion is not an endorsement, a security certification, or a claim that a project is required by Sage. There are no paid placements, affiliate links, or reciprocal-link requirements.

## Continue with Sage

- [Tools, Skills and MCP](../../docs/en/MCP_SERVERS.md)
- [Desktop setup](../../docs/en/applications/DESKTOP.md)
- [Server setup](../../docs/en/applications/WEB.md)
- [Troubleshooting](../../docs/en/TROUBLESHOOTING.md)

[Knowledge hub](../README.md)
