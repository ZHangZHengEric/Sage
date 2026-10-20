"""Signed filesystem authorization shared by Skill workspace policies."""

from __future__ import annotations

import asyncio

from sagents.v2.runtime.execution.sandbox import OperationIntent


class SandboxSkillWorkspaceBase:
    def __init__(self, sandbox, issuer):
        self.sandbox, self.issuer = sandbox, issuer
        self._lock = asyncio.Lock()
        self._sequence = 0

    def _authorization(self, operation, path, run_id):
        self._sequence += 1
        intent = OperationIntent(
            operation=operation.value, run_id=run_id,
            sandbox_id=self.sandbox.ref.sandbox_id,
            tool_call_id=f"skill_materialize_{self._sequence}", path=path,
        )
        return {"intent": intent, "grant": self.issuer.issue(
            ref=self.sandbox.ref, intent=intent,
            allowed_operations=frozenset({operation.value}),
        )}
