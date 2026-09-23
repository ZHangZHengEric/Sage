"""Process-local execution port. Use cases bind models and track tasks through this."""

from __future__ import annotations


class ProcessExecution:
    def __init__(self, host) -> None:
        self._host = host

    def driving(self, run_id: str) -> bool:
        return run_id in self._host._drives

    def adopt(self, run_id: str, task) -> None:
        self._host._drives[run_id] = task
        self._host._track(task)

    def release(self, run_id: str) -> None:
        self._host._drives.pop(run_id, None)

    def bind_model(self, session_id: str, user_id: str) -> bool:
        models = self._host._host_models
        if models is None:
            return False
        models.bind_session_user(session_id, user_id)
        return True

    def unbind_model(self, session_id: str) -> None:
        models = self._host._host_models
        if models is not None:
            models.unbind_session_user(session_id)

    def has_model(self, catalog) -> bool:
        return self._host._has_configured_model(catalog)

    def model_missing_message(self) -> str:
        return self._host._model_missing_message()

    def sagents_logger(self):
        return self._host._sagents_logger()

    @property
    def fallback_model(self):
        return self._host._fallback_model

    @property
    def model_pool(self):
        return self._host._host_models

    async def acquire_model(self, user_id: str, record):
        models = self._host._host_models
        if models is None:
            raise RuntimeError("model pool is not started")
        return await models.acquire_model(user_id, record)

    @property
    def sandbox_provider(self):
        return self._host._sandbox_provider

    @property
    def sandbox_grant_issuer(self):
        return self._host._sandbox_grant_issuer
