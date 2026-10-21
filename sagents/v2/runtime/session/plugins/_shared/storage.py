"""Shared capability publication and artifact view for Session storage plugins."""

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error


class SessionArtifactStore:
    def __init__(self, session_store, run_id=None):
        self.session_store = session_store
        self.run_id = run_id

    def for_run(self, run_id):
        return type(self)(self.session_store, run_id)

    async def _scope(self):
        if self.run_id is None:
            raise RuntimeError("Session artifact storage requires a Run binding")
        if not all(
            callable(getattr(self.session_store, name, None))
            for name in (
                "get_run_context",
                "put_attachment",
                "get_attachment",
            )
        ):
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="session.attachments_unsupported",
                    category=ErrorCategory.VALIDATION,
                    message="The selected SessionStore plugin does not support session attachments.",
                    safe_to_resume=True,
                )
            )
        run = await self.session_store.get_run(self.run_id)
        context = await self.session_store.get_run_context(self.run_id)
        return run.session_id, context

    async def put(self, *, artifact_id, media_type, content, metadata=None):
        session_id, context = await self._scope()
        return await self.session_store.put_attachment(
            session_id,
            artifact_id=artifact_id,
            media_type=media_type,
            content=content,
            metadata=metadata,
            context=context,
        )

    async def get(self, artifact_id):
        session_id, context = await self._scope()
        return await self.session_store.get_attachment(
            session_id, artifact_id, context=context
        )

    async def delete(self, artifact_id):
        raise NotImplementedError(
            "Session attachments are retained until their owning session is deleted."
        )


SESSION_STORAGE_CAPABILITIES = ("session.store", "derived-state.store", "artifact.store")


def session_storage_providers(store):
    return {
        "session.store": store,
        "derived-state.store": store,
        "artifact.store": SessionArtifactStore(store),
    }
