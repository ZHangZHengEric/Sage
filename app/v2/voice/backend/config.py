"""Voice-only settings, kept in a private file in Application Support."""

import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    field_validator,
    model_validator,
)
from sagents.v2.contracts.common import ToolName

from .tools import SAGE_TOOL_NAMES
from .voice_pipeline.tool_speech import TARGETED_TOOL_SPEECH, canonical_tool_name


class ToolSpeechOverride(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    enabled: bool = True
    zh: str = Field(default="", max_length=100)
    en: str = Field(default="", max_length=100)


class VoiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    model_base_url: str
    model: str
    model_api_key: SecretStr
    system_prompt: str = Field(default="", max_length=12000)
    reasoning_effort: (
        Literal["none", "minimal", "low", "medium", "high", "xhigh"] | None
    ) = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int | None = Field(default=None, gt=0)
    speech_provider: Literal["qwen_audio", "volcengine"]
    speech_api_key: SecretStr
    voice: str = ""
    workspace_id: str = ""
    enabled_tools: tuple[ToolName, ...] = ()
    tool_speech: dict[ToolName, ToolSpeechOverride] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def migrate_local_tools(cls, value):
        if not isinstance(value, dict) or "local_tools" not in value:
            return value
        values = dict(value)
        values.pop("local_tools")
        return values

    @field_validator("enabled_tools")
    @classmethod
    def validate_enabled_tools(cls, names):
        # Older Voice versions could save this private tool alongside Sage tools.
        enabled = set(names) - {"get_local_time"}
        unknown = enabled - SAGE_TOOL_NAMES
        if unknown:
            raise ValueError(
                "Tools unavailable in Voice: " + ", ".join(sorted(unknown))
            )
        return tuple(sorted(enabled))

    @field_validator("tool_speech")
    @classmethod
    def check_tool_speech(cls, rules):
        normalized = {}
        for name, rule in rules.items():
            if name == "get_local_time":
                continue
            canonical = canonical_tool_name(name)
            for text in (rule.zh, rule.en):
                remainder = text.replace("{target}", "")
                if "{" in remainder or "}" in remainder:
                    raise ValueError(f"{name} 的播报只支持 {{target}} 占位符。")
                if "{target}" in text and canonical not in TARGETED_TOOL_SPEECH:
                    raise ValueError(f"{name} 的参数不可用于播报，请移除 {{target}}。")
            # Preserve an explicit canonical setting when an older file has both.
            if name == canonical or canonical not in normalized:
                normalized[canonical] = rule
        return normalized

    @field_validator("model_base_url")
    @classmethod
    def check_url(cls, value):
        url = HttpUrl(value)
        if url.username or url.password or url.query or url.fragment:
            raise ValueError(
                "Enter a model API base URL without credentials or query parameters"
            )
        return value.rstrip("/")

    @field_validator("model")
    @classmethod
    def required_model(cls, value):
        if not value:
            raise ValueError("Enter a model name")
        return value

    @field_validator("model_api_key", "speech_api_key")
    @classmethod
    def required_key(cls, value):
        if not value.get_secret_value().strip():
            raise ValueError("Enter the API key")
        return SecretStr(value.get_secret_value().strip())

    def fields(self):
        return self.model_dump() | {
            "model_api_key": self.model_api_key.get_secret_value(),
            "speech_api_key": self.speech_api_key.get_secret_value(),
        }

    def model_request(self):
        return self.model_dump(
            include={"reasoning_effort", "temperature", "max_output_tokens"},
            exclude_none=True,
        )


def save_config(path: Path, config: VoiceConfig):
    import json

    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, prefix=".settings-", delete=False, encoding="utf-8"
    ) as file:
        temporary = Path(file.name)
        try:
            json.dump(config.fields(), file, ensure_ascii=False)
            file.close()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
