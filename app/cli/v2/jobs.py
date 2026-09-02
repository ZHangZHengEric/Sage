"""CLI 自带的 ``execution.job-runtime``：让官方 shell 工具在通用 builder 路径下可用。

背景（upstream 回归，`cc54b858`）：`SAgentBuilder` 会把 application 级的 JobRuntime 注入每个
Run 的 ``OfficialToolRuntime``，覆盖掉它自带的 ``official.shell`` runner；而 manifest 里配出来的
``sage.job.ephemeral`` 是 ``runners: {}``，于是 ``execute_shell_command`` 一律失败
``job.kind_unsupported``。shell runner 需要"本 Run 的 sandbox + grant issuer"，全局 runtime
天然不知道——这里用 CLI 的 binding provider 按 ``owner_run_id`` 反查来补上。

upstream 修复后（builder 不再覆盖，或共享 runtime 支持按 Run 分派）本模块可整体删除。
"""

from __future__ import annotations

from typing import Protocol

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.jobs import JobCompletion, JobSpec
from sagents.v2.runtime.execution import RunExecutionBinding
from sagents.v2.runtime.execution.jobs import InMemoryJobRuntime
from sagents.v2.runtime.execution.sandbox import OperationIntent, ProcessRequest
from sagents.v2.runtime.extensions import (
    CapabilityOffer,
    ExtensionDescriptor,
    ExtensionRegistration,
    ExtensionScope,
)

CLI_JOB_RUNTIME_PLUGIN = "sage.cli.job-runtime"
JOB_RUNTIME_CAPABILITY = "execution.job-runtime"
SHELL_JOB_KIND = "official.shell"


class RunBindingResolver(Protocol):
    def binding_for_run(self, run_id: str) -> RunExecutionBinding | None: ...


class CliShellJobRuntime(InMemoryJobRuntime):
    """进程内 JobRuntime，``official.shell`` 作业在所属 Run 的沙箱里执行。"""

    def __init__(
        self,
        bindings: RunBindingResolver,
        *,
        max_concurrent_jobs: int = 32,
    ) -> None:
        super().__init__(
            {SHELL_JOB_KIND: self._run_shell}, max_concurrent_jobs=max_concurrent_jobs
        )
        self.bindings = bindings

    async def _run_shell(self, spec: JobSpec, emit, cancel_event) -> JobCompletion:
        del cancel_event
        binding = self.bindings.binding_for_run(spec.owner_run_id)
        if binding is None or binding.closed:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="job.sandbox_unavailable",
                    category=ErrorCategory.VALIDATION,
                    message=(
                        f"no live sandbox binding for run {spec.owner_run_id!r}; "
                        "shell jobs must run inside their own Run"
                    ),
                    safe_to_resume=True,
                )
            )
        # 与 OfficialToolRuntime._run_shell_job 同构：非登录 shell、每次操作签发一次性 grant。
        command = str(spec.payload["command"])
        cwd = str(spec.payload["cwd"])
        env = dict(spec.payload.get("env") or {})
        argv = ("bash", "-c", command)
        request = ProcessRequest(argv=argv, cwd=cwd, env=env)
        intent = OperationIntent(
            operation="process.run",
            run_id=spec.owner_run_id,
            tool_call_id=str(spec.payload["tool_call_id"]),
            sandbox_id=binding.sandbox.ref.sandbox_id,
            path=cwd,
            executable="bash",
            argv=argv,
        )
        grant = binding.grant_issuer.issue(
            ref=binding.sandbox.ref,
            intent=intent,
            allowed_operations=frozenset({intent.operation}),
        )
        result = await binding.sandbox.process.run(request, intent=intent, grant=grant)
        if result.stdout:
            await emit("stdout", result.stdout)
        if result.stderr:
            await emit("stderr", result.stderr)
        return JobCompletion(exit_code=result.exit_code)


def cli_job_runtime_registration(bindings: RunBindingResolver) -> ExtensionRegistration:
    """把 ``CliShellJobRuntime`` 注册为可被 manifest 选择的 ``execution.job-runtime`` 插件。"""

    return ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id=CLI_JOB_RUNTIME_PLUGIN,
            version="0.1.0",
            name="Sage CLI job runtime",
            description=(
                "In-memory job runtime whose official.shell runner executes inside the "
                "owning Run's local workspace sandbox."
            ),
            provides=(
                CapabilityOffer(capability=JOB_RUNTIME_CAPABILITY, api_version="2"),
            ),
            supported_scopes=frozenset({ExtensionScope.PROCESS}),
            config_schema={
                "type": "object",
                "properties": {
                    "max_concurrent_jobs": {"type": "integer", "minimum": 1},
                    # builder 对该 capability 的默认配置带 runners: {}；JSON 里放不了 Python
                    # 可调用对象，这里接受但忽略它。
                    "runners": {"type": "object"},
                },
                "additionalProperties": False,
            },
            capabilities={
                "durable_across_process_restart": False,
                "supports_reconnect": False,
                "supports_suspend": False,
            },
        ),
        factory=lambda context, dependencies: CliShellJobRuntime(
            bindings,
            max_concurrent_jobs=int(context.config.get("max_concurrent_jobs", 32)),
        ),
    )
