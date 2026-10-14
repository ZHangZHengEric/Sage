"""Legacy user Skill selectors, kept separate from canonical conversation facts."""

from __future__ import annotations

import re

from sagents.v2.contracts.conversation import is_user_request
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model import ModelMessage


SKILL_TAG = re.compile(r"<skill>\s*([^<>]+?)\s*</skill>", re.IGNORECASE)


def requested_skills(messages: tuple[ModelMessage, ...]) -> tuple[str, ...]:
    names: dict[str, None] = {}
    for message in messages:
        if not is_user_request(message):
            continue
        for block in message.content:
            if isinstance(block, TextBlock):
                for match in SKILL_TAG.finditer(block.text):
                    name = match.group(1).strip()
                    if name:
                        names.pop(name, None)
                        names[name] = None
    return tuple(names)


def strip_skill_tags(message: ModelMessage) -> ModelMessage:
    if not is_user_request(message):
        return message
    content = tuple(
        block.model_copy(update={"text": SKILL_TAG.sub("", block.text)})
        if isinstance(block, TextBlock)
        else block
        for block in message.content
    )
    if content == message.content:
        return message
    return message.model_copy(update={"content": content})
