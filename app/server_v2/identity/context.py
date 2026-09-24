"""Identity and tool scope policy for server requests."""

from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext, TraceContext

from app.server_v2.identity.keys import ApiKeyRecord

TOOL_SCOPES = (
    "tool.read",
    "tool.write",
    "tool.internal",
    "tool.external_side_effect",
    "skill.load",
    "workspace.read",
    "workspace.write",
    "workspace.delete",
    "process.run",
)


class RequestContexts:
    def __init__(self, language: str) -> None:
        self.language = language

    def for_user(
        self, user_id: str, *, correlation_id: str | None = None
    ) -> RequestContext:
        return RequestContext(
            actor=ActorRef(
                principal_id=user_id,
                principal_type=PrincipalType.USER,
                tenant_id=user_id,
                scopes=TOOL_SCOPES,
            ),
            trace=TraceContext(correlation_id=correlation_id),
            language=self.language,
        )

    def for_a2a_key(
        self, key: ApiKeyRecord, *, correlation_id: str | None = None
    ) -> RequestContext:
        # The owner remains principal so their keys share thread access.
        return RequestContext(
            actor=ActorRef(
                principal_id=key.owner_user_id,
                principal_type=PrincipalType.USER,
                tenant_id=key.owner_user_id,
                delegated_by=key.key_id,
                scopes=(*key.scopes, *TOOL_SCOPES),
            ),
            trace=TraceContext(correlation_id=correlation_id),
            language=self.language,
        )
