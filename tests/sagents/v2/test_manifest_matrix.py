from __future__ import annotations


import pytest

from sagents.v2.runtime.credentials.contracts import CredentialRef
from sagents.v2.runtime.credentials.providers import (
    EnvironmentCredentialProvider,
    MappingCredentialProvider,
)
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.principals import (
    ActorRef,
    PrincipalType,
    RequestContext,
)
from sagents.v2.package.manifest.loader import SageManifestLoader
from sagents.v2.package.manifest.resolver import CompositionResolver


VALID = """
schema_version: sage/v1
kind: application
metadata:
  id: com.example.coder
  version: 1.0.0
  name: Coder
credentials:
  primary-key:
    source: env
    key: TEST_MODEL_KEY
models:
  primary:
    provider: openai-compatible
    base_url: https://models.example.com/v1
    credential: primary-key
    model: test-model
    request:
      max_output_tokens: 2048
    limits:
      context_window: 128000
runtime:
  preset: standard
  scheduler:
    max_concurrent_runs: 8
    max_concurrent_runs_per_tenant: 2
plugins:
  - id: acme.model.private-gateway
policies:
  budgets:
    max_steps: 12
    input_tokens: 10000
    output_tokens: 2000
    total_tokens: 5000
    wall_time_seconds: 60
agents:
  main:
    name: Main
    instructions:
      inline: Be concise.
    models:
      primary: primary
    entrypoint:
      type: loop
      loop: react
      config:
        max_steps: 8
    tools: [read_file, write_file]
    skills: [testing]
entrypoint:
  agent: main
interfaces:
  native: {enabled: true}
  ag_ui: {enabled: true}
tests:
  scenarios: []
environments:
  development:
    runtime:
      scheduler:
        max_concurrent_runs: 2
"""


CONTEXT = RequestContext(
    actor=ActorRef(principal_id="user_1", principal_type=PrincipalType.USER)
)


def test_valid_single_file_resolves_to_secret_free_immutable_specs():
    manifest = SageManifestLoader().loads(VALID)
    resolved = CompositionResolver().resolve(manifest)
    assert resolved.package_id == "com.example.coder"
    assert resolved.entrypoint_agent == "main"
    assert resolved.agents["main"].instructions == "Be concise."
    assert resolved.agents["main"].max_steps == 8
    assert resolved.policy_ceilings["main"].max_steps == 8
    assert resolved.policy_ceilings["main"].max_total_tokens == 5000
    assert resolved.model_routes["primary"]["model"] == "test-model"
    assert resolved.plugins[0].id == "acme.model.private-gateway"
    assert resolved.runtime.scheduler.max_concurrent_runs == 8
    assert "TEST_MODEL_KEY" not in str(resolved.model_routes)
    assert resolved.manifest_hash.startswith("sha256:")


@pytest.mark.parametrize("secret_field", ["api_key", "api_keys", "token", "password"])
def test_plaintext_secret_fields_are_rejected_by_strict_schema(secret_field):
    content = VALID.replace(
        "    model: test-model",
        f"    model: test-model\n    {secret_field}: do-not-allow",
    )
    with pytest.raises(SageV2Error) as invalid:
        SageManifestLoader().loads(content)
    assert invalid.value.info.code == "manifest.schema_invalid"
    assert secret_field in invalid.value.info.message


@pytest.mark.parametrize(
    "base_url",
    [
        "https://user:secret@models.example.com/v1",
        "https://models.example.com/v1?api_key=secret",
        "ftp://models.example.com/v1",
        "/relative/v1",
    ],
)
def test_model_base_url_cannot_smuggle_credentials(base_url):
    content = VALID.replace("https://models.example.com/v1", base_url)
    with pytest.raises(SageV2Error) as invalid:
        SageManifestLoader().loads(content)
    assert invalid.value.info.code == "manifest.schema_invalid"


@pytest.mark.parametrize(
    ("replacement", "error_code"),
    [
        ("credential: missing-key", "manifest.credential_not_found"),
        ("primary: missing-model", "manifest.model_not_found"),
        ("subagents: [missing-agent]", "manifest.subagent_not_found"),
        ("agent: missing-agent", "manifest.agent_not_found"),
    ],
)
def test_reference_validation_matrix(replacement, error_code):
    if replacement.startswith("credential"):
        content = VALID.replace("credential: primary-key", replacement)
    elif replacement.startswith("primary"):
        content = VALID.replace("primary: primary", replacement)
    elif replacement.startswith("subagents"):
        content = VALID.replace(
            "    tools: [read_file, write_file]",
            f"    tools: [read_file, write_file]\n    {replacement}",
        )
    else:
        content = VALID.replace("agent: main", replacement)
    manifest = SageManifestLoader().loads(content)
    with pytest.raises(SageV2Error) as invalid:
        CompositionResolver().resolve(manifest)
    assert invalid.value.info.code == error_code


def test_environment_overlay_only_changes_allowed_domains():
    manifest = SageManifestLoader().loads(VALID, environment="development")
    assert manifest.runtime.scheduler.max_concurrent_runs == 2
    assert manifest.metadata.id == "com.example.coder"

    forbidden = VALID.replace(
        "    runtime:\n      scheduler:\n        max_concurrent_runs: 2",
        "    metadata:\n      id: com.attacker.changed",
    )
    with pytest.raises(SageV2Error) as denied:
        SageManifestLoader().loads(forbidden, environment="development")
    assert denied.value.info.code == "manifest.environment_forbidden_override"


def test_unknown_environment_and_duplicate_yaml_key_are_rejected():
    with pytest.raises(SageV2Error) as missing:
        SageManifestLoader().loads(VALID, environment="production")
    assert missing.value.info.code == "manifest.environment_not_found"

    duplicate = VALID.replace("  version: 1.0.0", "  version: 1.0.0\n  version: 2.0.0")
    with pytest.raises(SageV2Error) as invalid:
        SageManifestLoader().loads(duplicate)
    assert invalid.value.info.code == "manifest.yaml_invalid"


def test_duplicate_plugin_declarations_are_rejected():
    duplicate = VALID.replace(
        "  - id: acme.model.private-gateway",
        "  - id: acme.model.private-gateway\n  - id: acme.model.private-gateway",
    )
    with pytest.raises(SageV2Error) as invalid:
        SageManifestLoader().loads(duplicate)
    assert invalid.value.info.code == "manifest.schema_invalid"
    assert "unique ids" in invalid.value.info.message


def test_instruction_file_is_resolved_inside_package(tmp_path):
    (tmp_path / "prompt.md").write_text("Loaded prompt", encoding="utf-8")
    content = VALID.replace("inline: Be concise.", "path: prompt.md")
    (tmp_path / "sage.yaml").write_text(content, encoding="utf-8")
    manifest = SageManifestLoader().load(tmp_path / "sage.yaml")
    assert manifest.agents["main"].instructions.inline == "Loaded prompt"
    assert manifest.agents["main"].instructions.path is None


def test_instruction_path_escape_and_wrong_entry_filename_are_rejected(tmp_path):
    outside = tmp_path.parent / "outside-prompt.md"
    outside.write_text("secret", encoding="utf-8")
    content = VALID.replace("inline: Be concise.", "path: ../outside-prompt.md")
    (tmp_path / "sage.yaml").write_text(content, encoding="utf-8")
    with pytest.raises(SageV2Error) as escaped:
        SageManifestLoader().load(tmp_path / "sage.yaml")
    assert escaped.value.info.code == "manifest.resource_outside_package"
    (tmp_path / "agent.yml").write_text(VALID, encoding="utf-8")
    with pytest.raises(SageV2Error) as filename:
        SageManifestLoader().load(tmp_path / "agent.yml")
    assert filename.value.info.code == "manifest.invalid_filename"


def test_run_override_can_narrow_but_not_expand_policy_ceiling():
    resolved = CompositionResolver().resolve(SageManifestLoader().loads(VALID))
    resolver = CompositionResolver()
    narrowed = resolver.resolve_run_config(
        resolved,
        "main",
        tools=("read_file",),
        max_steps=4,
        max_output_tokens=1024,
        max_total_tokens=4000,
        deadline_seconds=30,
    )
    assert narrowed.max_steps == 4
    assert narrowed.max_output_tokens == 1024
    assert narrowed.max_total_tokens == 4000
    assert narrowed.deadline_seconds == 30
    assert narrowed.enabled_tools == ("read_file",)
    assert narrowed.enabled_skills == ("testing",)
    assert narrowed.metadata["enabled_tools"] == ["read_file"]
    assert narrowed.metadata["enabled_skills"] == ["testing"]

    with pytest.raises(SageV2Error) as tool:
        resolver.resolve_run_config(resolved, "main", tools=("shell",))
    assert tool.value.info.code == "manifest.tool_override_denied"
    with pytest.raises(SageV2Error) as skill:
        resolver.resolve_run_config(resolved, "main", skills=("unknown-skill",))
    assert skill.value.info.code == "manifest.skill_override_denied"
    with pytest.raises(SageV2Error) as steps:
        resolver.resolve_run_config(resolved, "main", max_steps=9)
    assert steps.value.info.code == "manifest.budget_override_denied"
    with pytest.raises(SageV2Error) as model:
        resolver.resolve_run_config(
            resolved, "main", model_bindings={"primary": "unknown-route"}
        )
    assert model.value.info.code == "manifest.model_override_denied"
    with pytest.raises(SageV2Error) as output_budget:
        resolver.resolve_run_config(resolved, "main", max_output_tokens=2001)
    assert output_budget.value.info.code == "manifest.budget_override_denied"
    with pytest.raises(SageV2Error) as total_budget:
        resolver.resolve_run_config(resolved, "main", max_total_tokens=5001)
    assert total_budget.value.info.code == "manifest.budget_override_denied"
    defaults = resolver.resolve_run_config(resolved, "main")
    assert defaults.max_output_tokens == 2000
    assert defaults.max_total_tokens == 5000
    assert defaults.deadline_seconds == 60


@pytest.mark.asyncio
async def test_credential_providers_resolve_only_at_boundary_and_mask_repr():
    manifest = SageManifestLoader().loads(VALID)
    provider = EnvironmentCredentialProvider(
        manifest.credentials, {"TEST_MODEL_KEY": "super-secret-value"}
    )
    material = await provider.resolve(
        CredentialRef(credential_id="primary-key", purpose="model_inference"),
        CONTEXT,
    )
    assert material.secret.get_secret_value() == "super-secret-value"
    assert "super-secret-value" not in repr(material)
    assert "super-secret-value" not in material.model_dump_json()

    host = MappingCredentialProvider({"host-key": "host-secret"})
    host_material = await host.resolve(
        CredentialRef(credential_id="host-key", purpose="sandbox"), CONTEXT
    )
    assert host_material.source == "host"


@pytest.mark.asyncio
async def test_missing_credential_is_typed_and_never_returns_empty_secret():
    provider = EnvironmentCredentialProvider(
        SageManifestLoader().loads(VALID).credentials, {}
    )
    with pytest.raises(SageV2Error) as unavailable:
        await provider.resolve(
            CredentialRef(credential_id="primary-key", purpose="model_inference"),
            CONTEXT,
        )
    assert unavailable.value.info.code == "credential.unavailable"
