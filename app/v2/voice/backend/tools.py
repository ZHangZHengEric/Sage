"""Sage built-in tool catalog for Voice."""

from sagents.v2.tool.localization import localize_tool_definition
from sagents.v2.tool.plugins.official import official_tool_definitions

from .voice_pipeline.tool_speech import default_tool_speech_settings


SAGE_TOOL_NAMES = frozenset(tool.name for tool in official_tool_definitions())


def voice_tool_catalog():
    speech = default_tool_speech_settings()
    catalog = []
    for definition in official_tool_definitions():
        localized = localize_tool_definition(definition, "zh")
        catalog.append(
            {
                "name": definition.name,
                "description": {
                    "en": definition.description,
                    "zh": localized.description,
                },
                "input_schema": {
                    "en": definition.input_schema,
                    "zh": localized.input_schema,
                },
                "speech": speech.get(definition.name, {}),
            }
        )
    return catalog
