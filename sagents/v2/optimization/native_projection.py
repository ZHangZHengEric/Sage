"""Project MCP effects by durable result receipts, preserving immutable items.

Model proposal order is not execution order for a parallel batch. This projection
uses only bound native receipts, never task answers or inferred reward. Replayers
must still validate every observed result against their authoritative environment.
"""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json

from sagents.v2.optimization.contracts import OptimizationObservation
from sagents.v2.tool.plugins.mcp import McpToolPlugin

PROTOCOL = "sage.rsi.native-receipt-projection/v1"


def observation_digest(observation):
    return hashlib.sha256(
        json.dumps(
            observation.model_dump(mode="json"),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def project_mcp_execution_order(
    observation: OptimizationObservation,
) -> OptimizationObservation:
    """Reorder call *slots* within a step/server; keep every envelope unchanged.

    Missing, conflicting or truncated proof is a no-op. The resulting order is a
    receipt-derived candidate projection, not a certification of linearization:
    the unchanged benchmark replay remains the authority on causal consistency.
    """
    evidence = observation.evidence
    items = evidence.get("final_items")
    run_id = evidence.get("run_id")
    if (
        not isinstance(items, list)
        or not run_id
        or evidence.get("runtime_events_truncated")
    ):
        return observation
    calls, results, proposed, receipts = {}, {}, {}, defaultdict(list)
    for index, envelope in enumerate(items):
        data = envelope.get("data", {})
        kind, identity = data.get("kind"), data.get("tool_call_id")
        if kind == "tool_call":
            if identity in calls:
                return observation
            calls[identity] = (index, envelope)
        elif kind == "tool_result":
            if identity in results:
                return observation
            results[identity] = envelope
    for event in evidence.get("runtime_events", ()):
        if event.get("run_id") != run_id:
            continue
        data = event.get("data", {})
        if event.get("type") == "tool.call.proposed":
            identity = data.get("tool_call_id")
            if identity in proposed:
                return observation
            proposed[identity] = event
        elif event.get("type") == "tool.call.succeeded":
            receipts[data.get("tool_call_id")].append(event)
    groups = defaultdict(list)
    for identity, (index, envelope) in calls.items():
        result = results.get(identity, {})
        metadata = result.get("data", {}).get("metadata", {})
        server, remote = metadata.get("mcp_server"), metadata.get("mcp_tool")
        if not server or not remote or envelope.get("step_id") is None:
            continue
        if envelope["data"].get("tool_name") != McpToolPlugin._public_name(
            server, remote
        ):
            continue
        groups[(envelope["step_id"], server)].append((identity, index, envelope))
    projected, changes = list(items), []
    for (step_id, server), group in groups.items():
        if len(group) < 2:
            continue
        verified = []
        for identity, index, envelope in group:
            proposal, result = proposed.get(identity), results.get(identity)
            receipt = receipts.get(identity, ())
            if not proposal or not result or len(receipt) != 1:
                break
            receipt = receipt[0]
            start, end = proposal["data"], receipt["data"]
            if (
                any(
                    value.get("run_id") != run_id or value.get("step_id") != step_id
                    for value in (envelope, result, proposal, receipt)
                )
                or start.get("arguments") != envelope["data"].get("arguments")
                or start.get("tool_name") != envelope["data"].get("tool_name")
                or not start.get("operation_id")
                or start["operation_id"] != end.get("operation_id")
                or end.get("state") != "completed"
                or end.get("error")
                or end.get("result_item_id") != result.get("item_id")
                or not isinstance(result.get("item_id"), str)
                or not isinstance(receipt.get("event_id"), str)
                or result["data"].get("error")
                or result["data"].get("metadata", {}).get("mcp_result_received")
                is not True
                or not isinstance(receipt.get("run_sequence"), int)
            ):
                break
            verified.append((receipt["run_sequence"], index, envelope, receipt))
        if len(verified) != len(group) or len({v[0] for v in verified}) != len(group):
            continue
        ordering_basis = "native_receipt_order"
        effect_orders = [
            results[value[2]["data"]["tool_call_id"]]["data"]["metadata"]
            .get("mcp_meta", {})
            .get("sage_rsi_effect_order")
            for value in verified
        ]
        if any(value is not None for value in effect_orders):
            if (
                not all(
                    isinstance(value, dict)
                    and value.get("protocol") == "sage.rsi.mcp-effect-order/v1"
                    and isinstance(value.get("sequence"), int)
                    and not isinstance(value["sequence"], bool)
                    and value["sequence"] > 0
                    and isinstance(value.get("case_instance"), str)
                    and value["case_instance"]
                    for value in effect_orders
                )
                or len({value["case_instance"] for value in effect_orders}) != 1
                or len({value["sequence"] for value in effect_orders}) != len(verified)
            ):
                continue
            ordered = [
                value
                for _, value in sorted(
                    zip(effect_orders, verified, strict=True),
                    key=lambda pair: pair[0]["sequence"],
                )
            ]
            ordering_basis = "server_effect_sequence"
        else:
            ordered = sorted(verified, key=lambda value: value[0])
        before = [identity for identity, _, _ in group]
        after = [v[2]["data"]["tool_call_id"] for v in ordered]
        if before == after:
            continue
        for slot, value in zip(sorted(v[1] for v in verified), ordered, strict=True):
            projected[slot] = value[2]
        changes.append(
            {
                "step_id": step_id,
                "server": server,
                "ordering_basis": ordering_basis,
                "proposal_order": before,
                "receipt_order": after,
                "receipt_event_ids": [v[3]["event_id"] for v in ordered],
            }
        )
    if not changes:
        return observation
    return observation.model_copy(
        update={
            "evidence": {
                **evidence,
                "final_items": projected,
                "execution_projection": {
                    "protocol": PROTOCOL,
                    "source_observation_hash": observation_digest(observation),
                    "steps": changes,
                },
            }
        }
    )
