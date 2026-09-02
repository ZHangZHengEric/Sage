from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


from app.desktop_v2.backend.catalog import (
    DesktopAgentRecord,
    DesktopMcpRecord,
    DesktopModelProviderRecord,
    default_agent_config,
)
from app.desktop_v2.backend.shell_policy import (
    normalize_shell_command,
    shell_policy_summary,
)
from sagents.v2.tool.localization import localize_tool_definition
from app.desktop_v2.backend.package import (
    DESKTOP_COMPONENTS as _DESKTOP_COMPONENTS,
    stable_component_id as _stable_component_id,
)
from sagents.v2.tool.official import OfficialToolRuntime
from sagents.v2.tool.plugins.official import (
    OfficialToolPlugin,
    official_tool_categories,
    official_tool_definitions,
)
from sagents.v2.contracts.common import new_id, utc_now
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.package.manifest.models import (
    ModelLimits,
    ModelRequestDefaults,
    ModelRoute,
)
from sagents.v2.model import (
    model_protocol_descriptor,
)
from sagents.v2.model.protocols import create_registered_model_provider
from sagents.v2.runtime.extensions import (
    ExtensionScope,
    ExtensionScopeContext,
)
from sagents.v2.skill import (
    SkillLoadTool,
)
from sagents.v2.tool import decorated_tool_definition
from sagents.v2.tool import (
    McpServerConfig,
    McpToolPlugin,
    ToolDefinition,
)
from app.desktop_v2.backend.model_probe import probe_model_provider_capabilities
from app.desktop_v2.backend.schemas import (
    AgentCreate,
    AgentSettingsPatch,
    ComponentSelectionRequest,
    DesktopRunRequest as DesktopRunRequest,
    MCPConnectionRequest,
    ModelProviderCreate,
    ModelProviderPatch,
)
from app.desktop_v2.backend.run_lifecycle import (
    DesktopRunResources as _DesktopRunResources,  # noqa: F401 - compatibility export
)
from app.desktop_v2.backend.run_context import (
    AgentRosterContextProvider as AgentRosterContextProvider,
)
from app.desktop_v2.backend.runtime_config import (
    _CONTINUATION_COMPONENT_CHOICES,
    _REASONING_DISABLE_EXTRAS,
    _SKILL_NAME,
    _continuation_component_config,
    _resolved_sandbox_config,
    _tool_selection_component_config,
)
from app.desktop_v2.backend.usage_analytics import (
    _usage_percentile as _usage_percentile,
)

_REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max")
_OUTPUT_TOKEN_FALLBACKS = (
    65_536,
    32_768,
    16_384,
    8_192,
    4_096,
    2_048,
    1_024,
    512,
    256,
    128,
)
def _mcp_source(tool_name: str) -> str:
    del tool_name
    return "MCP Server"


_TOOL_CATEGORY_SOURCES = {
    "code_quality": "代码质量",
    "code_search": "代码检索",
    "files": "文件",
    "image": "图像",
    "interaction": "交互",
    "memory": "记忆",
    "multi_agent": "多智能体",
    "planning": "任务规划",
    "shell": "终端",
    "system": "系统",
    "web": "网页",
}


def _tool_category_source(category: str | None) -> str:
    if not category:
        return "基础工具"
    return _TOOL_CATEGORY_SOURCES.get(category, f"分类: {category}")


def _normalized_assignment_names(values: list[str] | None, *, label: str) -> list[str]:
    """Return deterministic Tool/Skill assignments without blank identities."""

    normalized = [str(value).strip() for value in values or ()]
    if any(not value for value in normalized):
        raise ValueError(f"{label} names cannot be empty")
    return sorted(set(normalized))


class DesktopCatalogServiceMixin:
    """Agent, Skill, Tool, model, MCP, and component administration."""

    async def list_agents(self, user_id: str) -> list[dict[str, Any]]:
        await self._initialize_user(user_id)
        values = await self.catalog.list_agents(user_id)
        return [
            {
                "id": value.agent_id,
                "name": value.name,
                "is_default": value.is_default,
                "tool_count": len(value.config.get("availableTools") or []),
                "skill_count": len(value.config.get("availableSkills") or []),
            }
            for value in values
        ]

    async def create_agent(self, request: AgentCreate, user_id: str) -> dict[str, Any]:
        """Create a usable Agent with no inherited configuration or runtime state."""

        await self._initialize_user(user_id)
        name = request.name.strip()
        if not name:
            raise ValueError("agent name cannot be empty")
        providers = await self.catalog.list_model_providers(user_id)
        provider = next((value for value in providers if value.is_default), None)
        provider = provider or (providers[0] if providers else None)
        config = default_agent_config(
            model_provider_id=provider.id if provider is not None else "model_main"
        )
        config["name"] = name
        created = DesktopAgentRecord(
            agent_id=new_id("agent"),
            user_id=user_id,
            name=name,
            config=config,
        )
        await self.catalog.save_agent(created)
        return await self.get_agent_settings(created.agent_id, user_id)

    async def list_skills(self, agent_id: str, user_id: str) -> list[dict[str, Any]]:
        agent = await self._agent(agent_id, user_id)
        allowed = set(agent.config.get("availableSkills") or [])
        values = self._skill_provider().descriptors()
        names = sorted(allowed if allowed else values)
        return [
            self._skill_summary(name, values[name])
            for name in names
            if name in values and _SKILL_NAME.fullmatch(name)
        ]

    async def list_skill_catalog(self, user_id: str) -> list[dict[str, Any]]:
        del user_id
        values = self._skill_provider().descriptors()
        return [
            self._skill_summary(name, values[name])
            for name in sorted(values)
            if _SKILL_NAME.fullmatch(name)
        ]

    async def get_skill_content(self, skill_name: str, user_id: str) -> str:
        del user_id
        if not _SKILL_NAME.fullmatch(skill_name):
            raise ValueError("invalid skill name")
        try:
            root = self._skill_provider()._skill_root(skill_name)
        except SageV2Error as exc:
            raise ValueError(f"Skill not found: {skill_name}") from exc

        skill_file = (root / "SKILL.md").resolve()
        if root not in skill_file.parents or not skill_file.is_file():
            raise ValueError("Skill folder does not contain SKILL.md")
        try:
            return await asyncio.to_thread(skill_file.read_text, encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("SKILL.md must be UTF-8 encoded") from exc

    async def import_skill_folder(
        self,
        folder_path: str,
        user_id: str,
    ) -> dict[str, Any]:
        normalized = Path(folder_path).expanduser().resolve()
        if not normalized.is_dir():
            raise ValueError("Skill folder does not exist")
        if not (normalized / "SKILL.md").is_file():
            raise ValueError("Skill folder must contain SKILL.md")
        skill_name = self._skill_name(normalized / "SKILL.md")
        if not skill_name:
            raise ValueError("SKILL.md must define a valid name")
        target = (self.skill_root / skill_name).resolve()
        if target.parent != self.skill_root.resolve():
            raise ValueError("invalid Skill name")
        if target.exists():
            raise ValueError(f"Skill already exists: {skill_name}")
        await asyncio.to_thread(shutil.copytree, normalized, target)
        return {"success_count": 1, "imported_names": [skill_name]}

    async def delete_skill(self, skill_name: str, user_id: str) -> dict[str, Any]:
        target = self._imported_skill_root(skill_name)
        if target is None:
            raise ValueError(f"Imported Skill not found: {skill_name}")

        await asyncio.to_thread(shutil.rmtree, target)
        for agent in await self.catalog.list_agents(user_id):
            available = list(agent.config.get("availableSkills") or [])
            if skill_name not in available:
                continue
            config = {
                **agent.config,
                "availableSkills": [name for name in available if name != skill_name],
            }
            await self.catalog.save_agent(agent.model_copy(update={"config": config}))
        return {"deleted_name": skill_name}

    async def list_tools(
        self, user_id: str, language: str | None = None
    ) -> list[dict[str, Any]]:
        categories = {
            **official_tool_categories(),
            "load_skill": "system",
        }
        definitions = []
        for value in self._native_tool_definitions():
            localized = localize_tool_definition(value, language)
            definitions.append(
                {
                    **localized.model_dump(mode="json"),
                    "type": "basic",
                    "category": categories.get(value.name),
                    "source": _tool_category_source(categories.get(value.name)),
                }
            )
        await self._initialize_user(user_id)
        for connection in await self.catalog.list_mcp(user_id):
            if connection.disabled:
                continue
            bridge = McpToolPlugin((self._mcp_config(connection),))
            try:
                discovered = await bridge.list_tools(run_id="desktop-tool-catalog")
            except SageV2Error:
                # One unavailable external server must not hide native tools or
                # prevent another connection from being configured.
                continue
            definitions.extend(
                {
                    **value.model_dump(mode="json"),
                    "type": "mcp",
                    "source": _mcp_source(value.name),
                }
                for value in discovered
            )
        return definitions

    def _official_tools(self, runtime: OfficialToolRuntime) -> OfficialToolPlugin:
        return OfficialToolPlugin(
            ExtensionScopeContext(
                scope=ExtensionScope.AGENT,
                scope_id="desktop-v2-official-tools",
                config={"runtime": runtime},
            )
        )

    def _native_tool_definitions(self) -> tuple[ToolDefinition, ...]:
        definitions = official_tool_definitions()
        load_skill = decorated_tool_definition(SkillLoadTool.execute)
        return (*definitions, *((load_skill,) if load_skill is not None else ()))

    async def _mcp_plugin(self, user_id: str) -> McpToolPlugin:
        await self._initialize_user(user_id)
        values = await self.catalog.list_mcp(user_id)
        return McpToolPlugin(
            tuple(self._mcp_config(value) for value in values if not value.disabled)
        )

    def _mcp_config(self, value: DesktopMcpRecord) -> McpServerConfig:
        streamable_url = value.streamable_http_url
        api_key = value.api_key
        if value.kind == "anytool":
            port = self.sidecar_port or 8080
            streamable_url = f"http://127.0.0.1:{port}/api/mcp/anytool/{value.name}"
            # The built-in AnyTool endpoint is served by the authenticated
            # Desktop sidecar. Its short-lived launch capability belongs to the
            # running process and must never be read from or persisted to the
            # user-editable MCP catalog.
            api_key = self.sidecar_auth_token
        return McpServerConfig(
            name=value.name,
            protocol=value.protocol,
            url=(
                streamable_url if value.protocol == "streamable_http" else value.sse_url
            ),
            api_key=api_key,
            command=value.command,
            args=value.args,
            env=value.env,
        )

    async def list_model_providers(self, user_id: str) -> list[dict[str, Any]]:
        await self._initialize_user(user_id)
        values = await self.catalog.list_model_providers(user_id)
        return [
            {
                "id": value.id,
                "name": value.name,
                "protocol": value.protocol,
                "model": value.model,
                "base_url": value.base_url,
                "api_key_configured": bool(value.api_key),
                "supports_multimodal": value.supports_multimodal,
                "supports_structured_output": bool(value.supports_structured_output),
                "supports_tool_calling": bool(value.supports_tool_calling),
                "is_default": value.is_default,
                "max_tokens": value.max_tokens,
                "temperature": value.temperature,
                "top_p": value.top_p,
                "max_model_len": value.max_model_len,
                "compatibility_profile": (
                    value.compatibility_profile.model_dump(mode="json")
                    if value.compatibility_profile is not None
                    else None
                ),
            }
            for value in values
        ]

    async def reveal_model_provider_api_key(
        self, provider_id: str, user_id: str
    ) -> dict[str, str]:
        provider = await self.catalog.get_model_provider(provider_id, user_id)
        if provider is None:
            raise ValueError("model provider is not configured for this Desktop user")
        if not provider.api_key:
            raise ValueError("model provider has no API key")
        return {"api_key": provider.api_key}

    async def delete_model_provider(
        self, provider_id: str, user_id: str
    ) -> list[dict[str, Any]]:
        provider = await self.catalog.get_model_provider(provider_id, user_id)
        if provider is None:
            raise ValueError("Provider not found")
        if provider.is_default:
            values = await self.catalog.list_model_providers(provider.user_id)
            replacement = next(
                (value for value in values if value.id != provider_id), None
            )
            if replacement is None:
                raise ValueError("Cannot delete the only model provider")
            replacement.is_default = True
            await self.catalog.save_model_provider(
                replacement.model_copy(update={"is_default": True})
            )
        await self.catalog.delete_model_provider(provider_id, user_id)
        return await self.list_model_providers(user_id)

    async def create_model_provider(
        self, request: ModelProviderCreate, user_id: str
    ) -> dict[str, Any]:
        await self._initialize_user(user_id)
        keys = [value.strip() for value in request.api_keys if value.strip()]
        if len(keys) > 1:
            raise ValueError("Desktop model providers accept one API key")
        existing = await self.catalog.list_model_providers(user_id)
        make_default = request.is_default or not existing
        if make_default:
            for value in existing:
                if value.is_default:
                    await self.catalog.save_model_provider(
                        value.model_copy(update={"is_default": False})
                    )
        candidate = DesktopModelProviderRecord(
            id=new_id("model"),
            user_id=user_id,
            name=request.name.strip(),
            protocol=request.protocol,
            model=request.model.strip(),
            base_url=request.base_url.strip(),
            api_key=keys[0] if keys else "",
            supports_multimodal=request.supports_multimodal,
            supports_structured_output=request.supports_structured_output,
            supports_tool_calling=request.supports_tool_calling,
            is_default=make_default,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            top_p=request.top_p,
            max_model_len=request.max_model_len,
            compatibility_profile=request.compatibility_profile,
        )
        self._validate_model_route(candidate)
        self._validate_model_compatibility_profile(candidate)
        await self.catalog.save_model_provider(candidate)
        values = await self.list_model_providers(user_id)
        return next(value for value in values if value["id"] == candidate.id)

    async def verify_model_provider_capabilities(
        self,
        request: ModelProviderCreate | ModelProviderPatch,
        user_id: str,
        *,
        provider_id: str | None = None,
    ) -> dict[str, Any]:
        """Probe a draft route without persisting it to the Desktop catalog."""

        if provider_id is None:
            if not isinstance(request, ModelProviderCreate):
                raise ValueError("New model capability checks require a complete route")
            keys = [value.strip() for value in request.api_keys if value.strip()]
            if len(keys) > 1:
                raise ValueError("Desktop model providers accept one API key")
            candidate = DesktopModelProviderRecord(
                id=new_id("model_probe"),
                user_id=user_id,
                name=request.name.strip(),
                protocol=request.protocol,
                model=request.model.strip(),
                base_url=request.base_url.strip(),
                api_key=keys[0] if keys else "",
                supports_multimodal=request.supports_multimodal,
                supports_structured_output=request.supports_structured_output,
                supports_tool_calling=request.supports_tool_calling,
                is_default=False,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                top_p=request.top_p,
                max_model_len=request.max_model_len,
            )
        else:
            provider = await self.catalog.get_model_provider(provider_id, user_id)
            if provider is None:
                raise ValueError("Provider not found")
            if not isinstance(request, ModelProviderPatch):
                raise ValueError("Existing model capability checks require a patch")
            updates = request.model_dump(exclude_unset=True, exclude={"api_keys"})
            if "compatibility_profile" in request.model_fields_set:
                updates["compatibility_profile"] = request.compatibility_profile
            if request.api_keys is not None:
                keys = [value.strip() for value in request.api_keys if value.strip()]
                if len(keys) > 1:
                    raise ValueError("Desktop model providers accept one API key")
                updates["api_key"] = keys[0] if keys else ""
            candidate = provider.model_copy(update=updates)

        self._validate_model_route(candidate)
        if not candidate.api_key:
            raise ValueError("An API key is required for capability validation")
        return await self._probe_model_provider_capabilities(candidate)

    async def patch_model_provider(
        self, provider_id: str, patch: ModelProviderPatch, user_id: str
    ) -> dict[str, Any]:
        provider = await self.catalog.get_model_provider(provider_id, user_id)
        if provider is None:
            raise ValueError("Provider not found")
        updates = patch.model_dump(exclude_unset=True, exclude={"api_keys"})
        if "compatibility_profile" in patch.model_fields_set:
            updates["compatibility_profile"] = patch.compatibility_profile
        route_fields = {
            "protocol",
            "model",
            "base_url",
            "api_key",
            "max_tokens",
            "max_model_len",
            "temperature",
            "top_p",
            "supports_multimodal",
            "supports_structured_output",
            "supports_tool_calling",
        }
        if (
            route_fields.intersection(updates)
            and "compatibility_profile" not in updates
        ):
            updates["compatibility_profile"] = None
        if patch.api_keys is not None:
            keys = [value.strip() for value in patch.api_keys if value.strip()]
            if len(keys) > 1:
                raise ValueError("Desktop model providers accept one API key")
            updates["api_key"] = keys[0] if keys else ""
            if "compatibility_profile" not in updates:
                updates["compatibility_profile"] = None
        updates["updated_at"] = utc_now()
        candidate = provider.model_copy(update=updates)
        self._validate_model_route(candidate)
        self._validate_model_compatibility_profile(candidate)
        if candidate.is_default and not provider.is_default:
            for value in await self.catalog.list_model_providers(user_id):
                if value.id != provider_id and value.is_default:
                    await self.catalog.save_model_provider(
                        value.model_copy(update={"is_default": False})
                    )
        await self.catalog.save_model_provider(candidate)
        values = await self.list_model_providers(user_id)
        return next(value for value in values if value["id"] == provider_id)

    @staticmethod
    def _validate_model_route(provider: DesktopModelProviderRecord) -> None:
        """Validate a saved route without making a network request."""

        if provider.max_tokens > provider.max_model_len:
            raise ValueError("max_tokens cannot exceed max_model_len")
        route = ModelRoute(
            provider=provider.protocol,
            base_url=provider.base_url,
            credential="desktop_model",
            model=provider.model,
            request=ModelRequestDefaults(
                max_output_tokens=provider.max_tokens,
                temperature=provider.temperature,
                top_p=provider.top_p,
            ),
            limits=ModelLimits(
                context_window=provider.max_model_len,
                max_output_tokens=provider.max_tokens,
            ),
        )
        model_protocol_descriptor(route.provider)

    @staticmethod
    def _model_compatibility_fingerprint(
        provider: DesktopModelProviderRecord,
    ) -> str:
        payload = {
            "protocol": provider.protocol,
            "base_url": provider.base_url.rstrip("/"),
            "model": provider.model,
            "max_tokens": provider.max_tokens,
            "max_model_len": provider.max_model_len,
            "temperature": provider.temperature,
            "top_p": provider.top_p,
            "credential_sha256": hashlib.sha256(
                provider.api_key.encode("utf-8")
            ).hexdigest(),
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    @classmethod
    def _validate_model_compatibility_profile(
        cls,
        provider: DesktopModelProviderRecord,
    ) -> None:
        profile = provider.compatibility_profile
        if profile is None:
            return
        expected = cls._model_compatibility_fingerprint(provider)
        if profile.route_fingerprint != expected:
            raise ValueError(
                "model compatibility verification does not match the saved route"
            )
        if (
            provider.protocol == "openai-chat-completions"
            and profile.max_output_tokens_field is None
        ):
            raise ValueError(
                "OpenAI Chat Completions compatibility requires an output token field"
            )
        if (
            provider.protocol != "openai-chat-completions"
            and profile.max_output_tokens_field is not None
        ):
            raise ValueError(
                "output token field compatibility only applies to Chat Completions"
            )
        if profile.schema_version >= 2:
            if profile.effective_max_output_tokens is None:
                raise ValueError(
                    "model compatibility verification requires an effective output limit"
                )
            if profile.effective_max_output_tokens > provider.max_tokens:
                raise ValueError(
                    "effective output limit cannot exceed the configured output limit"
                )
            overlap = set(profile.supported_reasoning_efforts).intersection(
                profile.unsupported_reasoning_efforts
            )
            if overlap:
                raise ValueError(
                    "reasoning effort compatibility results cannot overlap"
                )

    async def _probe_model_provider_capabilities(
        self, provider: DesktopModelProviderRecord,
    ) -> dict[str, Any]:
        return await probe_model_provider_capabilities(
            provider,
            provider_factory=create_registered_model_provider,
            compatibility_fingerprint=self._model_compatibility_fingerprint,
            output_token_fallbacks=_OUTPUT_TOKEN_FALLBACKS,
            reasoning_disable_extras=_REASONING_DISABLE_EXTRAS,
            reasoning_efforts=_REASONING_EFFORTS,
        )

    async def get_agent_settings(self, agent_id: str, user_id: str) -> dict[str, Any]:
        agent = await self._agent(agent_id, user_id)
        config = dict(agent.config or {})
        deep_thinking, thinking_level = self._thinking_config(agent)
        runtime_variables = config.get("runtimeVariables")
        if runtime_variables is None:
            runtime_variables = config.get("systemContext")
        if runtime_variables is None:
            runtime_variables = config.get("system_context")
        if not isinstance(runtime_variables, dict):
            runtime_variables = {}
        return {
            "id": agent.agent_id,
            "name": agent.name,
            "description": config.get("description") or "",
            "system_prefix": config.get("systemPrefix")
            or config.get("system_prefix")
            or "",
            "runtime_variables": runtime_variables,
            "system_context": runtime_variables,
            "llm_provider_id": config.get("llm_provider_id"),
            "fast_llm_provider_id": config.get("fast_llm_provider_id"),
            "agent_mode": config.get("agentMode")
            or config.get("agent_mode")
            or "simple",
            "sub_agent_selection_mode": config.get("subAgentSelectionMode")
            or config.get("sub_agent_selection_mode")
            or "auto_all",
            "available_sub_agent_ids": list(
                config.get("availableSubAgentIds")
                or config.get("available_sub_agent_ids")
                or []
            ),
            "max_loop_count": int(
                config.get("maxLoopCount") or config.get("max_loop_count") or 100
            ),
            "deep_thinking": deep_thinking,
            "thinking_level": thinking_level,
            "available_tools": list(config.get("availableTools") or []),
            "available_skills": list(config.get("availableSkills") or []),
            "approved_shell_commands": list(config.get("approvedShellCommands") or []),
            "shell_policy": shell_policy_summary(
                config.get("approvedShellCommands") or ()
            ),
            "is_default": agent.is_default,
            "updated_at": agent.updated_at.isoformat() if agent.updated_at else None,
        }

    async def patch_agent_settings(
        self,
        agent_id: str,
        patch: AgentSettingsPatch,
        user_id: str,
    ) -> dict[str, Any]:
        agent = await self._agent(agent_id, user_id)
        config = dict(agent.config or {})
        fields = patch.model_fields_set
        updates: dict[str, Any] = {}
        if "name" in fields:
            name = str(patch.name or "").strip()
            if not name:
                raise ValueError("agent name cannot be empty")
            updates["name"] = name
            config["name"] = name
        mapping = {
            "description": "description",
            "system_prefix": "systemPrefix",
            "system_context": "systemContext",
            "runtime_variables": "systemContext",
            "llm_provider_id": "llm_provider_id",
            "fast_llm_provider_id": "fast_llm_provider_id",
            "agent_mode": "agentMode",
            "sub_agent_selection_mode": "subAgentSelectionMode",
            "available_sub_agent_ids": "availableSubAgentIds",
            "max_loop_count": "maxLoopCount",
            "deep_thinking": "deepThinking",
            "thinking_level": "thinkingLevel",
            "available_tools": "availableTools",
            "available_skills": "availableSkills",
            "approved_shell_commands": "approvedShellCommands",
        }
        for field, target in mapping.items():
            if field in fields:
                config[target] = getattr(patch, field)
        if "available_tools" in fields:
            selected_tools = _normalized_assignment_names(
                patch.available_tools, label="tool"
            )
            known = {value["name"] for value in await self.list_tools(user_id)}
            # Keep previously assigned external tools removable even when their
            # MCP server is temporarily unavailable during discovery.
            known.update(agent.config.get("availableTools") or ())
            unknown = set(selected_tools) - known
            if unknown:
                raise ValueError(f"unknown tools: {', '.join(sorted(unknown))}")
            config["availableTools"] = selected_tools
        if "available_sub_agent_ids" in fields:
            selected_agents = _normalized_assignment_names(
                patch.available_sub_agent_ids, label="sub-agent"
            )
            if agent_id in selected_agents:
                raise ValueError("an agent cannot include itself as a sub-agent")
            known_agents = {
                value.agent_id for value in await self.catalog.list_agents(user_id)
            }
            unknown = set(selected_agents) - known_agents
            if unknown:
                raise ValueError(f"unknown sub-agents: {', '.join(sorted(unknown))}")
            config["availableSubAgentIds"] = selected_agents
        if "available_skills" in fields:
            selected_skills = _normalized_assignment_names(
                patch.available_skills, label="skill"
            )
            known = {value["name"] for value in await self.list_skill_catalog(user_id)}
            known.update(agent.config.get("availableSkills") or ())
            unknown = set(selected_skills) - known
            if unknown:
                raise ValueError(f"unknown skills: {', '.join(sorted(unknown))}")
            config["availableSkills"] = selected_skills
        if "approved_shell_commands" in fields:
            config["approvedShellCommands"] = sorted(
                {
                    normalized
                    for value in patch.approved_shell_commands or ()
                    if (normalized := normalize_shell_command(value))
                }
            )
        updates.update({"config": config, "updated_at": utc_now()})
        await self.catalog.save_agent(agent.model_copy(update=updates))
        return await self.get_agent_settings(agent_id, user_id)

    async def delete_agent(self, agent_id: str, user_id: str) -> list[dict[str, Any]]:
        agent = await self._agent(agent_id, user_id)
        values = await self.catalog.list_agents(user_id)
        replacement = next(
            (value for value in values if value.agent_id != agent_id), None
        )
        if replacement is None:
            raise ValueError("Cannot delete the only agent")
        if agent.is_default:
            await self.catalog.save_agent(
                replacement.model_copy(update={"is_default": True})
            )
        await self.catalog.delete_agent(agent_id, user_id)

        settings = await self.get_settings()
        if settings.default_agent_id == agent_id:
            await self.save_settings(
                settings.model_copy(update={"default_agent_id": replacement.agent_id})
            )
        return await self.list_agents(user_id)

    async def list_mcp_connections(self, user_id: str) -> list[dict[str, Any]]:
        await self._initialize_user(user_id)
        values = await self.catalog.list_mcp(user_id)
        result = []
        for value in values:
            tool_count = 0
            connection_error = ""
            if not value.disabled:
                bridge = McpToolPlugin((self._mcp_config(value),))
                try:
                    tool_count = len(
                        await bridge.list_tools(run_id="desktop-mcp-catalog")
                    )
                except SageV2Error as exc:
                    connection_error = exc.info.message
            result.append(
                {
                    **value.model_dump(
                        mode="json",
                        exclude={"api_key", "user_id", "tools", "simulator"},
                    ),
                    "api_key_configured": bool(value.api_key),
                    "tool_count": tool_count,
                    "connection_error": connection_error,
                }
            )
        return result

    async def add_mcp_connection(
        self, request: MCPConnectionRequest, user_id: str
    ) -> dict[str, Any]:
        if request.protocol == "stdio" and not str(request.command or "").strip():
            raise ValueError("stdio connection requires command")
        if request.protocol == "sse" and not str(request.sse_url or "").strip():
            raise ValueError("sse connection requires URL")
        if (
            request.protocol == "streamable_http"
            and not str(request.streamable_http_url or "").strip()
        ):
            raise ValueError("streamable HTTP connection requires URL")
        await self.catalog.save_mcp(
            DesktopMcpRecord(
                user_id=user_id,
                name=request.name.strip(),
                protocol=request.protocol,
                streamable_http_url=request.streamable_http_url,
                sse_url=request.sse_url,
                api_key=request.api_key,
                command=request.command,
                args=tuple(request.args),
                env=request.env,
            )
        )
        values = await self.list_mcp_connections(user_id)
        return next(value for value in values if value["name"] == request.name.strip())

    async def set_mcp_connection_enabled(
        self, server_name: str, enabled: bool, user_id: str
    ) -> dict[str, Any]:
        record = next(
            (
                value
                for value in await self.catalog.list_mcp(user_id)
                if value.name == server_name
            ),
            None,
        )
        if record is None:
            raise ValueError("MCP connection not found")
        await self.catalog.save_mcp(record.model_copy(update={"disabled": not enabled}))
        values = await self.list_mcp_connections(user_id)
        return next(value for value in values if value["name"] == server_name)

    async def component_inventory(self, user_id: str) -> list[dict[str, Any]]:
        del user_id
        settings = await self.get_settings()
        result = []
        process_active = {
            "context.summary-store": self.summary_store_plugin_id,
            "memory.provider": self.memory_plugin_id,
            "session-memory.provider": self.session_memory_plugin_id,
            "observability.diagnostic-sink": self.diagnostic_plugin_id,
            "observability.log-sink": self.log_plugin_id,
            "session.store": self.session_plugin_id,
        }
        for capability, component_spec in _DESKTOP_COMPONENTS.items():
            default_plugin_id = str(component_spec["default"])
            plugins = []
            for registration in self.extensions.registrations():
                descriptor = registration.descriptor
                if capability not in {
                    offer.capability for offer in descriptor.provides
                }:
                    continue
                if (
                    capability == "agent.continuation-policy"
                    and descriptor.plugin_id not in _CONTINUATION_COMPONENT_CHOICES
                ):
                    continue
                plugins.append(
                    {
                        "plugin_id": descriptor.plugin_id,
                        "name": descriptor.name,
                        "value": descriptor.description,
                        "available": descriptor.availability.available,
                        "built_in": descriptor.built_in,
                        "dependencies": [
                            dependency.capability
                            for dependency in descriptor.dependencies
                            if not dependency.optional
                        ],
                        "config_schema": descriptor.config_schema,
                    }
                )
            if capability == "agent.continuation-policy":
                order = {
                    plugin_id: index
                    for index, plugin_id in enumerate(_CONTINUATION_COMPONENT_CHOICES)
                }
                plugins.sort(key=lambda value: order[value["plugin_id"]])
            user_selectable = component_spec["selection_mode"] == "user"
            host_run_config = capability == "execution.sandbox"
            selected = (
                settings.component_selections.get(capability, default_plugin_id)
                if user_selectable or host_run_config
                else default_plugin_id
            )
            selected = _stable_component_id(capability, selected)
            active_plugin_id = process_active.get(capability, selected)
            apply_mode = str(component_spec["apply_mode"])
            result.append(
                {
                    "component": {
                        "component_id": capability,
                        "name": capability,
                        "value": capability,
                        "selection_mode": component_spec["selection_mode"],
                        "apply_mode": apply_mode,
                        "scope": component_spec["scope"],
                    },
                    "plugins": plugins,
                    "active": {
                        "plugin_id": active_plugin_id,
                        "selected_plugin_id": selected,
                        "source": (
                            "user"
                            if user_selectable
                            and capability in settings.component_selections
                            else "host"
                            if host_run_config
                            and capability in settings.component_selections
                            else "default"
                        ),
                        "config": (
                            {
                                "format_version": self.log_sink.format_version,
                                "path": str(getattr(self.log_sink, "path", "")),
                                "min_level": str(
                                    getattr(
                                        getattr(self.log_sink, "min_level", ""),
                                        "value",
                                        getattr(self.log_sink, "min_level", ""),
                                    )
                                ),
                                "max_bytes": getattr(self.log_sink, "max_bytes", None),
                                "backup_count": getattr(
                                    self.log_sink, "backup_count", None
                                ),
                            }
                            if capability == "observability.log-sink"
                            else {
                                "path": str(self.runtime_root / "memory"),
                                "recall": self.memory_plugin_id != "sage.memory.noop",
                                "auto_write": self.memory_plugin_id
                                != "sage.memory.noop",
                                "scope_mode": "agent",
                            }
                            if capability == "memory.provider"
                            else {
                                "path": str(self.runtime_root / "session-memory"),
                                "derived_from": "session.events",
                            }
                            if capability == "session-memory.provider"
                            else {
                                "path": str(getattr(self.diagnostics, "root", "")),
                                "format_version": getattr(
                                    self.diagnostics, "format_version", ""
                                ),
                            }
                            if capability == "observability.diagnostic-sink"
                            else {
                                "path": str(self.runtime_root / "sessions"),
                                "authoritative": True,
                            }
                            if capability == "session.store"
                            else _continuation_component_config(active_plugin_id)
                            if capability == "agent.continuation-policy"
                            else _tool_selection_component_config(
                                selected, settings.component_configs.get(capability)
                            )
                            if capability == "tool.selection-policy"
                            else _resolved_sandbox_config(settings)[1]
                            if capability == "execution.sandbox"
                            else {}
                        ),
                        "pending_restart": (
                            user_selectable
                            and apply_mode == "restart"
                            and selected != active_plugin_id
                        ),
                    },
                }
            )
        return result

    async def select_component(
        self,
        component_id: str,
        request: ComponentSelectionRequest,
        user_id: str,
    ) -> dict[str, Any]:
        del user_id
        component_spec = _DESKTOP_COMPONENTS.get(component_id)
        if component_spec is None or component_spec["selection_mode"] != "user":
            raise ValueError(f"component {component_id!r} is not user configurable")
        if (
            component_id == "agent.continuation-policy"
            and request.plugin_id not in _CONTINUATION_COMPONENT_CHOICES
        ):
            raise ValueError(
                f"completion policy {request.plugin_id!r} is not user selectable"
            )
        registration = self.extensions.get(request.plugin_id)
        capabilities = {offer.capability for offer in registration.descriptor.provides}
        if component_id not in capabilities:
            raise ValueError(
                f"extension {request.plugin_id!r} does not provide {component_id!r}"
            )
        settings = await self.get_settings()
        normalized_config = dict(request.config)
        if component_id == "tool.selection-policy":
            normalized_config = _tool_selection_component_config(
                request.plugin_id, request.config
            )
        choices = dict(settings.component_selections)
        choices[component_id] = request.plugin_id
        configs = dict(settings.component_configs)
        configs[component_id] = normalized_config
        await self.save_settings(
            settings.model_copy(
                update={
                    "component_selections": choices,
                    "component_configs": configs,
                }
            )
        )
        return {
            "component_id": component_id,
            "plugin_id": request.plugin_id,
            "config": normalized_config,
            "pending_restart": (
                component_spec["apply_mode"] == "restart"
                and request.plugin_id
                != {
                    "memory.provider": self.memory_plugin_id,
                    "session-memory.provider": self.session_memory_plugin_id,
                    "observability.log-sink": self.log_plugin_id,
                }.get(component_id, request.plugin_id)
            ),
        }
