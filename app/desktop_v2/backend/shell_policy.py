"""Desktop adapter from the established shell policy to V2 tool decisions."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sagents.utils.sandbox.policy import SandboxPolicyGateway
from sagents.v2.agent.policy import (
    ToolOperationAssessment,
    ToolPolicyAction,
    ToolPolicyContext,
)
from sagents.v2.tool import SideEffectLevel


AUTO_EXECUTE_KEYWORDS = (
    "cat / ls / rg / grep / sed",
    "pytest / flutter test / npm test",
    "build / ordinary scripts",
    "workspace > / >>",
    "pip / npm / pnpm / yarn / bun install",
    "brew / apt / dnf / yum / apk install",
    "git push (non-force)",
    "relative rm -rf",
    "chmod / chown / kill / pkill",
)
APPROVAL_KEYWORDS = (
    "git reset --hard",
    "git clean",
    "git branch -d / git tag -d",
    "git push --delete / :branch",
    "recursive delete outside allowlist",
    "permission or process change outside allowlist",
    "suspicious > / >> target",
    "unparseable shell command",
)
BLOCKED_KEYWORDS = (
    "sudo / su / systemctl / service",
    "reboot / shutdown / poweroff / halt",
    "dd / fdisk / parted / mkfs / wipefs",
    "useradd / userdel / usermod / passwd",
    "rm -rf / / rm -rf ~",
    "curl|sh / wget|bash",
    "git push --force main / master",
)


class ShellCommandOperationAssessor:
    """Classify shell commands while treating structured tools as non-dangerous."""

    def __init__(
        self,
        command_policy: dict[str, Any] | None = None,
        approved_commands: Iterable[str] = (),
    ) -> None:
        self._gateway = SandboxPolicyGateway(
            approval_mode="on-request",
            command_policy=command_policy,
        )
        self._approved_commands = {
            normalized
            for value in approved_commands
            if (normalized := normalize_shell_command(value))
        }

    @property
    def approved_commands(self) -> tuple[str, ...]:
        return tuple(sorted(self._approved_commands))

    def approve_command(self, command: str) -> str:
        normalized = normalize_shell_command(command)
        if not normalized:
            raise ValueError("approved shell command cannot be empty")
        self._approved_commands.add(normalized)
        return normalized

    def __call__(self, context: ToolPolicyContext) -> ToolOperationAssessment:
        if (
            context.definition.name == "goal_submit"
            and context.invocation_mode == "plan"
        ):
            return ToolOperationAssessment(
                action=ToolPolicyAction.REQUIRE_INTERACTION,
                reason="the submitted Plan requires explicit user approval",
                category="plan_approval",
                side_effect_level=SideEffectLevel.NONE,
            )
        if context.definition.name != "execute_shell_command":
            return ToolOperationAssessment(
                action=ToolPolicyAction.ALLOW,
                reason="non-shell tools do not participate in dangerous-command review",
                category="non_shell_tool",
                side_effect_level=context.definition.side_effect_level,
            )

        command = context.call.arguments.get("command")
        decision = self._gateway.evaluate_shell_command(
            command if isinstance(command, str) else ""
        )
        normalized_command = normalize_shell_command(command)
        if decision.action != "deny" and normalized_command in self._approved_commands:
            return ToolOperationAssessment(
                action=ToolPolicyAction.ALLOW,
                reason="command was approved and remembered by the user",
                category="user_approved_command",
                side_effect_level=SideEffectLevel.WRITE,
            )
        action = {
            "allow": ToolPolicyAction.ALLOW,
            "ask": ToolPolicyAction.REQUIRE_INTERACTION,
            "deny": ToolPolicyAction.DENY,
        }[decision.action]
        return ToolOperationAssessment(
            action=action,
            reason=decision.reason,
            category=decision.category,
            side_effect_level=(
                SideEffectLevel.WRITE
                if action != ToolPolicyAction.DENY
                else SideEffectLevel.IRREVERSIBLE
            ),
            persistent_approval_allowed=action == ToolPolicyAction.REQUIRE_INTERACTION,
        )


def normalize_shell_command(command: object) -> str:
    return command.strip() if isinstance(command, str) else ""


def shell_policy_summary(approved_commands: Iterable[str] = ()) -> dict[str, list[str]]:
    return {
        "auto_execute_keywords": list(AUTO_EXECUTE_KEYWORDS),
        "approval_keywords": list(APPROVAL_KEYWORDS),
        "blocked_keywords": list(BLOCKED_KEYWORDS),
        "user_approved_commands": sorted(
            {
                normalized
                for value in approved_commands
                if (normalized := normalize_shell_command(value))
            }
        ),
    }


__all__ = [
    "APPROVAL_KEYWORDS",
    "AUTO_EXECUTE_KEYWORDS",
    "BLOCKED_KEYWORDS",
    "ShellCommandOperationAssessor",
    "normalize_shell_command",
    "shell_policy_summary",
]
