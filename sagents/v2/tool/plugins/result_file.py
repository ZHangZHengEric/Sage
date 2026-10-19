"""Bound large textual Tool outputs without discarding their complete result."""

import hashlib
import json

from sagents.v2.contracts.items import JsonBlock, TextBlock
from sagents.v2.tool.decorated import ToolInvocation
from sagents.v2.tool.contracts import ToolCall, ToolExecutionResult
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.runtime.observability.logs import get_logger

LOGGER = get_logger(__name__)


class FileToolResultProcessor:
    plugin_id = "sage.tool.result-processor.file"
    name = "Tool result file offload"
    description = "Saves oversized Tool results in the bound workspace and returns a bounded preview."

    def __init__(self, *, max_inline_characters: int = 12_000):
        if type(max_inline_characters) is not int or max_inline_characters < 1:
            raise ValueError("max_inline_characters must be a positive integer")
        self.max_inline_characters = max_inline_characters

    async def process(
        self, result: ToolExecutionResult, *, call: ToolCall,
        context: RequestContext, runtime=None,
    ) -> ToolExecutionResult:
        if result.metadata.get("result_offloaded"):
            return result
        text = "\n".join(
            block.text if isinstance(block, TextBlock)
            else json.dumps(block.value, ensure_ascii=False)
            for block in result.content if isinstance(block, (TextBlock, JsonBlock))
        )
        if len(text) <= self.max_inline_characters:
            return result
        logger = LOGGER.bind(run_id=call.owner_run_id, tool_call_id=call.tool_call_id)
        if runtime is None:
            logger.warning("tool.result.offload_unavailable", "No bound workspace for Tool result offload",
                           attributes={"original_characters": len(text)})
            return result
        # Hash both identity and content: parallel calls, retries and tenants
        # cannot collide or inject paths. All I/O uses signed sandbox grants.
        full = result.model_dump_json(indent=2)
        digest = hashlib.sha256((call.owner_run_id + "\0" + call.tool_call_id + "\0" + full).encode()).hexdigest()
        relative_path = f".sage/tool-results/{digest}.json"
        try:
            path = await runtime.write_text(relative_path, full, ToolInvocation(call, context))
        except Exception:
            # Execution already happened. Never turn a storage error into a
            # failed Tool call that the Agent might execute again, or discard
            # the original output. The normal durable result remains intact.
            logger.warning("tool.result.offload_failed", "Could not save Tool result; preserving complete result",
                           attributes={"original_characters": len(text)})
            return result
        notice = (
            f"[Tool result {'failed' if result.error else 'succeeded'}; full output saved]\n"
            f"Original characters: {len(text)}. Full result: {path}\n"
            "Read selected line ranges or extract needed fields with shell; avoid reading the whole file.\n"
            "The preview above may end inside a value.\n"
        )
        preview = text[:self.max_inline_characters] + "\n\n" + notice
        media = tuple(b for b in result.content if not isinstance(b, (TextBlock, JsonBlock)))
        logger.info("tool.result.offloaded", "Saved oversized Tool result",
                    attributes={"original_characters": len(text), "inline_characters": len(preview),
                                "preview_characters": min(len(text), self.max_inline_characters),
                                "max_inline_characters": self.max_inline_characters})
        return result.model_copy(update={
            "content": (TextBlock(text=preview), *media),
            "metadata": {**result.metadata, "result_offloaded": True,
                         "context_reference": {"path": path, "original_characters": len(text)}},
        })
