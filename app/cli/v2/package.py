"""为 CLI 组装 SAgents v2 的 Agent package（``sage.yaml`` 的进程内等价物）。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sagents.v2.agent.presets.catalog import BUILTIN_AGENT_PRESETS
from sagents.v2.package.manifest.loader import SageManifestLoader
from sagents.v2.package.manifest.root import SageManifest
from sagents.v2.package.manifest.runtime import CapabilitySelection
from sagents.v2.package.presets.factory import BuiltinPackageFactory
from sagents.v2.tool.contracts import SideEffectLevel
from sagents.v2.tool.plugins.official import official_tool_definitions

DEFAULT_PRESET = "coder"
# 与 v1 CLI 共用同一个 API key 环境变量，避免用户维护两套配置。
DEFAULT_CREDENTIAL_ENV = "SAGE_DEFAULT_LLM_API_KEY"
OFFICIAL_TOOL_PLUGIN = "sage.tool.official"
# CLI 默认让模型看到 preset 的全部工具：确定性、无额外模型调用。
DIRECT_TOOL_SELECTION_PLUGIN = "sage.tool-selection.direct"
# 单机重启恢复：进程崩溃后残留的孤儿 Run 在下次启动时被标为 execution.worker_restarted，
# 否则 SERIAL 会话会被那个非终态 Run 永久占住、无法 resume。
FILESYSTEM_SCHEDULER_PLUGIN = "sage.scheduler.filesystem"
SCHEDULER_CAPABILITY = "execution.scheduler"
# 孤儿 Run 的恢复靠 worker 租约过期后重新入队；CLI 是单机交互工具，租约短一点让
# 崩溃后的 resume 只需等几秒（dispatcher 每 lease/3 续一次租）。
CLI_SCHEDULER_LEASE_SECONDS = 5.0


@dataclass(frozen=True)
class CliModelSettings:
    """从 CLI 配置解析出的模型路由参数（不含密钥本身）。"""

    model: str
    base_url: str | None = None
    credential_env: str = DEFAULT_CREDENTIAL_ENV
    context_window: int | None = None
    max_output_tokens: int | None = None


def available_presets() -> tuple[str, ...]:
    """CLI 可直接运行的内置 preset（仅 loop 型入口，flow 型另行接入）。"""

    return tuple(
        sorted(
            preset_id
            for preset_id, preset in BUILTIN_AGENT_PRESETS.items()
            if preset.entrypoint.type == "loop"
        )
    )


def build_preset_package(
    preset: str,
    model: CliModelSettings,
    *,
    package_id: str | None = None,
    scheduler_root: str | Path | None = None,
) -> SageManifest:
    """基于内置 preset 生成一个可直接 build 的 package。

    ``scheduler_root`` 给出时选用 filesystem scheduler（单写者、崩溃可恢复）；
    为 None 则用运行时默认的 ephemeral scheduler。
    """

    if preset not in available_presets():
        raise ValueError(
            f"unknown v2 preset {preset!r}; available: {', '.join(available_presets())}"
        )
    manifest = BuiltinPackageFactory.create(
        preset,
        package_id=package_id or f"sage.cli.{preset}",
        model=model.model,
        base_url=model.base_url,
        credential_env=model.credential_env,
        context_window=model.context_window,
        max_output_tokens=model.max_output_tokens,
    )
    capabilities = {
        **manifest.runtime.capabilities,
        "tool.catalog": CapabilitySelection(
            plugin=OFFICIAL_TOOL_PLUGIN, name="official"
        ),
        "tool.selection-policy": CapabilitySelection(
            plugin=DIRECT_TOOL_SELECTION_PLUGIN
        ),
    }
    if scheduler_root is not None:
        capabilities[SCHEDULER_CAPABILITY] = CapabilitySelection(
            plugin=FILESYSTEM_SCHEDULER_PLUGIN,
            config={
                "root": str(Path(scheduler_root).expanduser()),
                "lease_seconds": CLI_SCHEDULER_LEASE_SECONDS,
            },
        )
    return manifest.model_copy(
        update={
            "runtime": manifest.runtime.model_copy(
                update={"capabilities": capabilities}
            )
        }
    )


def without_filesystem_scheduler(manifest: SageManifest) -> SageManifest:
    """退回 ephemeral scheduler（另一个进程正占着 filesystem scheduler 的写锁时）。"""

    capabilities = dict(manifest.runtime.capabilities)
    selection = capabilities.get(SCHEDULER_CAPABILITY)
    plugins = (
        {s.plugin for s in selection}
        if isinstance(selection, tuple)
        else {selection.plugin} if selection is not None else set()
    )
    if FILESYSTEM_SCHEDULER_PLUGIN not in plugins:
        return manifest
    capabilities.pop(SCHEDULER_CAPABILITY)
    return manifest.model_copy(
        update={
            "runtime": manifest.runtime.model_copy(
                update={"capabilities": capabilities}
            )
        }
    )


def load_package(path: str | Path) -> SageManifest:
    """加载用户自带的 ``sage.yaml``；其 runtime 配置原样尊重。"""

    return SageManifestLoader().load(Path(path).expanduser())


def plan_visible_tools(package: SageManifest, agent_id: str) -> tuple[str, ...]:
    """plan 模式下对模型可见的工具：agent 自己的工具里只留无副作用/只读/plan_safe 的。

    写类工具在 plan 模式本来就会被策略拒绝，但让模型根本看不到它们更省一轮
    "调用 → 被拒"。``goal_submit`` 由 Runtime 按模式单独授予，不在此列表里。
    非官方工具（用户 package 里的）无从判断副作用等级，一律隐藏。
    """

    definitions = {tool.name: tool for tool in official_tool_definitions()}
    visible: list[str] = []
    for name in package.agents[agent_id].tools:
        definition = definitions.get(name)
        if definition is None:
            continue
        if definition.plan_safe or definition.side_effect_level in {
            SideEffectLevel.NONE,
            SideEffectLevel.READ,
        }:
            visible.append(name)
    return tuple(visible)

