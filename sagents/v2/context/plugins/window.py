"""API-triggered window reduction without token counting."""

from __future__ import annotations

import hashlib
from collections import OrderedDict

from sagents.v2.context.contracts import ContextProjection
from sagents.v2.context.partition import conversation_units, current_turn_boundary
from sagents.v2.contracts.conversation import is_user_request
from sagents.v2.model.recovery import recovery_error


def _digest(messages):
    digest = hashlib.sha256()
    for message in messages:
        digest.update(message.model_dump_json().encode())
    return "sha256:" + digest.hexdigest()


class WindowContextReducer:
    plugin_id = "sage.context.reducer.window"
    name = "Window context reducer"
    description = "Drops complete historical units only when explicitly requested."

    def __init__(self):
        self._prefixes = OrderedDict()

    async def reduce(self, messages, budget=None, *, scope=None):
        systems = tuple(m for m in messages if m.role in {"system", "developer"})
        payload = tuple(m for m in messages if m.role not in {"system", "developer"})
        key = scope.context_key if scope else None
        covered, digest = self._prefixes.get(key, (0, None))
        if covered > len(payload) or digest != _digest(payload[:covered]):
            covered = 0
        remaining = payload[covered:]
        request = next((m for m in reversed(payload) if is_user_request(m)), None)
        anchor = (
            (request,)
            if request is not None and not any(m is request for m in remaining)
            else ()
        )
        current = (*systems, *anchor, *remaining)
        force = bool(scope and scope.force) or bool(
            budget and budget.max_messages and len(current) > budget.max_messages
        )
        if force:
            units = conversation_units(remaining)
            boundary = current_turn_boundary(units)
            if not boundary and len(units) > 2:
                boundary = len(units) - 1
            if not boundary:
                raise recovery_error(
                    "context.no_reducible_history",
                    "No historical conversation remains to reduce",
                )
            count = max(1, (boundary + 1) // 2)
            dropped_count = sum(len(unit) for unit in units[:count])
            covered += dropped_count
            remaining = payload[covered:]
            anchor = (
                (request,)
                if request is not None and not any(m is request for m in remaining)
                else ()
            )
            current = (*systems, *anchor, *remaining)
            if key is not None:
                self._prefixes[key] = (covered, _digest(payload[:covered]))
                self._prefixes.move_to_end(key)
                while len(self._prefixes) > 128:
                    self._prefixes.popitem(last=False)
        historical = payload[:covered]
        return ContextProjection(
            messages=current,
            historical_messages=historical,
            dropped_digest=_digest(historical) if historical else None,
            source_message_count=len(messages),
            dropped_message_count=covered,
            strategy="window" if covered else "none",
        )
