"""OpenUI adapter for the shared output self-check policy."""

import asyncio

from sagents.v2.agent.policy.output_self_check import OutputCheck
from sagents.v2.contracts.conversation import is_user_request
from .openui import openui_blocks
from .openui_checks import probe_tree


class OpenUiOutputChecker:
    def __init__(self, parser):
        self.parser = parser

    async def check(self, context):
        # Only the latest assistant body is a validation target. History is
        # consulted solely for the bounded repair counter, never for source.
        blocks = openui_blocks(context.response.text)
        if not blocks:
            return None
        current_turn = []
        for message in reversed(context.ledger):
            text = "\n".join(getattr(block, "text", "") for block in message.content)
            if is_user_request(message):
                break
            if message.role == "assistant":
                current_turn.append(text)
        # Keep parser IPC serialized inside OpenUiParser; overlap each completed
        # block's CPU probes with other blocks rather than blocking the event loop.
        semaphore = asyncio.Semaphore(4)

        async def check_block(index, block):
            async with semaphore:
                try:
                    if not block["closed"]:
                        raise ValueError("OpenUI fence was not closed")
                    tree = await self.parser.parse(
                        block["code"],
                        complete=True,
                        stream_id=f"completion:{context.run_id}:{context.step_number}:{index}",
                    )
                    failures, probes = await asyncio.to_thread(probe_tree, tree)
                    return (
                        [f"Block {index + 1}: {failure}" for failure in failures],
                        probes,
                    )
                except (ValueError, RuntimeError) as exc:
                    return ([f"Block {index + 1}: {str(exc)[:1200]}"], {})

        async with asyncio.TaskGroup() as group:
            tasks = [
                group.create_task(check_block(index, block))
                for index, block in enumerate(blocks)
            ]
        errors = [error for task in tasks for error in task.result()[0]]
        evidence = [task.result()[1] for task in tasks]
        return OutputCheck(
            errors=errors,
            current_output=True,
            evidence={"outputs": evidence},
            generations=max(1, sum(bool(openui_blocks(text)) for text in current_turn)),
            repair_instruction=(
                "Correct the reported constraints and output one complete replacement OpenUI block. "
                "Preserve the user's requirements. Do not repeat earlier versions or use tools merely to render it."
            ),
        )
