# Sage v2 composition implementation

The public host interface is `SAgentBuilder.register`, `build(runtime, models)`,
`SAgentApplication.load_agent`, the standard entrypoint and `close`.
[SDK guide](../README.md) documents configuration and ownership.

| Module | Responsibility |
| --- | --- |
| `configuration.py` | Serializable application choices plus explicit registrations returned by managed-host factories |
| `bootstrap.py` | App process capabilities, authoritative store, dispatcher and recovery resolver; no placeholder Agent |
| `loaded_agents.py` | Serialized publication of immutable Agent revisions and authorized recovery |
| `agent_graph.py` | Explicit one-Agent package graph, direct Team members and ordinary delegate boundaries |
| `revision_store.py` | Atomic persistent snapshots of resolved Agent revisions |
| `resolution.py` | Manifest resolution, trust and selection rules |
| `providers.py` | Dependency resolution and identity-aware scope borrowing through ExtensionHost |
| `assembler.py` | SDK-owned Agent/Flow assembly and actual Run capability creation |
| `agent_components.py` | Standard context and continuation dependency order |
| `bound_tools.py` | Official tools from the actual Run execution environment |
| `drivers.py` | Internal lazy binding after actual Run allocation; cleanup of independent owned resources |
| `contracts.py` | Inspectable final provider selections and dependencies |
| `identity.py` | Canonical configuration and registered implementation identity |
| `defaults.py` | Explicit effective defaults frozen into revisions |

Hosts implement capability protocols. They do not construct these internal
classes, replace execution attributes or provide a Driver. Process objects pass
through registration factories and declared dependencies. Runtime selects one
mechanism for both built-in and custom implementations.

Each App owns its scopes and dispatcher. Shared host objects are borrowed.
Creation failure rolls back owned resources; cancellation and App shutdown wait
for in-flight assembly to settle. Run cleanup attempts independent resources even
if one close fails and retries only failed cleanup. Shared sandbox resources use
separate Run leases. Durable execution recovery remains in the execution runtime;
resource cleanup alone does not authorize replaying side effects.
