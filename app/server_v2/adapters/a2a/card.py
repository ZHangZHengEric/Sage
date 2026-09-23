from __future__ import annotations

from a2a.types.a2a_pb2 import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentProvider,
    AgentSkill,
    HTTPAuthSecurityScheme,
    SecurityRequirement,
    SecurityScheme,
)

from app.server_v2.domain.catalog import AgentRecord

# The JSON-RPC binding name and the protocol revision this server implements.
PROTOCOL_VERSION = "1.0"
JSONRPC_BINDING = "JSONRPC"
RPC_PATH = "/a2a/v1"
SECURITY_SCHEME = "bearer"

_INPUT_MODES = ("text/plain",)
_OUTPUT_MODES = ("text/plain",)


def agent_card(
    agent: AgentRecord,
    *,
    base_url: str,
    streaming: bool = False,
) -> AgentCard:
    """Describe one catalog Agent as an A2A Agent Card.

    The card is per-Agent rather than per-server: a Sage host carries many
    tenants' Agents, and a client holding one API key may only see the one its
    key is bound to. That is why there is no anonymous
    ``/.well-known/agent-card.json`` with a single global identity — the card
    route is authenticated and answers with the key's Agent.
    """

    card = AgentCard(
        name=agent.name or agent.id,
        description=agent.description,
        version=PROTOCOL_VERSION,
        provider=AgentProvider(organization="Sage"),
        capabilities=AgentCapabilities(
            streaming=streaming,
            push_notifications=False,
            extended_agent_card=False,
        ),
        default_input_modes=list(_INPUT_MODES),
        default_output_modes=list(_OUTPUT_MODES),
    )
    card.supported_interfaces.append(
        AgentInterface(
            url=f"{base_url.rstrip('/')}{RPC_PATH}",
            protocol_binding=JSONRPC_BINDING,
            protocol_version=PROTOCOL_VERSION,
        )
    )
    card.security_schemes[SECURITY_SCHEME].CopyFrom(
        SecurityScheme(
            http_auth_security_scheme=HTTPAuthSecurityScheme(
                scheme="bearer",
                bearer_format="Sage API key",
                description="An API key minted at /api/keys, sent as a bearer token.",
            )
        )
    )
    requirement = SecurityRequirement()
    requirement.schemes[SECURITY_SCHEME].list.extend(["a2a:invoke"])
    card.security_requirements.append(requirement)
    card.skills.append(_skill(agent))
    return card


def _skill(agent: AgentRecord) -> AgentSkill:
    """Publish the Agent itself as one skill.

    A2A skills are advertised capabilities a caller selects between; Sage
    skills are internal prompt modules the Agent composes on its own. Mapping
    one onto the other would invite a client to address something it cannot
    invoke, so the card advertises the single thing a caller can actually ask
    for: the Agent.
    """

    return AgentSkill(
        id=agent.id,
        name=agent.name or agent.id,
        description=agent.description or f"Converse with {agent.name or agent.id}.",
        tags=["sage"],
        input_modes=list(_INPUT_MODES),
        output_modes=list(_OUTPUT_MODES),
    )
