"""Sandbox policy gateway for command execution.

The gateway classifies actions before they reach a concrete sandbox provider.
It deliberately does not decide which sandbox type to use; it only answers
whether an operation is safe to run immediately, should require confirmation,
or must be denied.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from typing import Any, Literal, Optional


PolicyAction = Literal["allow", "ask", "deny"]
ApprovalMode = Literal["untrusted", "on-request", "never"]

DEFAULT_APPROVAL_MODE: ApprovalMode = "never"
APPROVAL_MODE_ENV_VARS = ("SAGE_APPROVAL_MODE", "SAGE_SANDBOX_APPROVAL_MODE")
SUPPORTED_APPROVAL_MODES = ("untrusted", "on-request", "never")


def normalize_approval_mode(value: Optional[str]) -> Optional[ApprovalMode]:
    normalized = (value or "").strip().lower().replace("_", "-")
    if normalized == "unless-trusted":
        normalized = "untrusted"
    if normalized in SUPPORTED_APPROVAL_MODES:
        return normalized  # pyright: ignore[reportReturnType]
    return None


def approval_mode_from_env(
    default: ApprovalMode = DEFAULT_APPROVAL_MODE,
) -> ApprovalMode:
    for name in APPROVAL_MODE_ENV_VARS:
        mode = normalize_approval_mode(os.environ.get(name))
        if mode is not None:
            return mode
    return default


@dataclass(frozen=True)
class SandboxPolicyDecision:
    action: PolicyAction
    category: str
    reason: str
    next_step: Optional[str] = None

    @property
    def allowed(self) -> bool:
        return self.action == "allow"


@dataclass(frozen=True)
class CommandPolicyRule:
    action: PolicyAction
    match: dict[str, Any]
    category: str = "runtime_policy"
    reason: str = "matched runtime command policy"
    next_step: Optional[str] = None


@dataclass(frozen=True)
class CommandPolicyConfig:
    rules: tuple[CommandPolicyRule, ...] = ()
    default_action: Optional[PolicyAction] = None
    default_category: str = "runtime_policy_default"
    default_reason: str = "no runtime command policy rule matched"


DEFAULT_COMMAND_POLICY = CommandPolicyConfig(
    rules=(
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["python", "-m", "pip", "install"]},
            category="default_dependency_install",
            reason="default policy allows Python package installation",
        ),
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["python3", "-m", "pip", "install"]},
            category="default_dependency_install",
            reason="default policy allows Python package installation",
        ),
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["pip", "install"]},
            category="default_dependency_install",
            reason="default policy allows Python package installation",
        ),
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["pip3", "install"]},
            category="default_dependency_install",
            reason="default policy allows Python package installation",
        ),
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["npm", "install"]},
            category="default_dependency_install",
            reason="default policy allows JavaScript package installation",
        ),
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["npm", "i"]},
            category="default_dependency_install",
            reason="default policy allows JavaScript package installation",
        ),
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["npm", "add"]},
            category="default_dependency_install",
            reason="default policy allows JavaScript package installation",
        ),
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["pnpm", "install"]},
            category="default_dependency_install",
            reason="default policy allows JavaScript package installation",
        ),
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["pnpm", "i"]},
            category="default_dependency_install",
            reason="default policy allows JavaScript package installation",
        ),
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["pnpm", "add"]},
            category="default_dependency_install",
            reason="default policy allows JavaScript package installation",
        ),
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["yarn", "install"]},
            category="default_dependency_install",
            reason="default policy allows JavaScript package installation",
        ),
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["yarn", "add"]},
            category="default_dependency_install",
            reason="default policy allows JavaScript package installation",
        ),
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["bun", "install"]},
            category="default_dependency_install",
            reason="default policy allows JavaScript package installation",
        ),
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["bun", "add"]},
            category="default_dependency_install",
            reason="default policy allows JavaScript package installation",
        ),
        CommandPolicyRule(
            action="allow",
            match={
                "pattern": (
                    r"^git\s+push\b(?!.*(?:^|\s)(?:-f|--force(?:\b|=)|"
                    r"--force-with-lease(?:\b|=)))"
                )
            },
            category="default_git_remote_write",
            reason="default policy allows non-forced git push",
        ),
        CommandPolicyRule(
            action="allow",
            match={
                "pattern": (
                    r"^rm\s+-[A-Za-z]*r[A-Za-z]*f?[A-Za-z]*\s+(\./)?"
                    r"(build|dist|target|node_modules|\.pytest_cache|\.mypy_cache|"
                    r"\.ruff_cache)(\s|/|$)"
                )
            },
            category="default_workspace_cleanup",
            reason="default policy allows common local build/cache cleanup",
        ),
        CommandPolicyRule(
            action="allow",
            match={
                "pattern": (
                    r"^rm\s+-[A-Za-z]*r[A-Za-z]*f?[A-Za-z]*\s+"
                    r"(?!/|~)(?!.*(?:^|\s)(?:/|~))(?:\.{0,2}/)?[^\s]+"
                )
            },
            category="default_relative_recursive_delete",
            reason="default policy allows recursive deletion of relative paths",
        ),
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["chmod"]},
            category="default_permission_change",
            reason="default policy allows chmod",
        ),
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["chown"]},
            category="default_permission_change",
            reason="default policy allows chown",
        ),
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["kill"]},
            category="default_process_control",
            reason="default policy allows process termination commands",
        ),
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["killall"]},
            category="default_process_control",
            reason="default policy allows process termination commands",
        ),
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["pkill"]},
            category="default_process_control",
            reason="default policy allows process termination commands",
        ),
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["brew", "install"]},
            category="default_dependency_install",
            reason="default policy allows package manager installation",
        ),
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["brew", "reinstall"]},
            category="default_dependency_install",
            reason="default policy allows package manager installation",
        ),
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["apt", "install"]},
            category="default_dependency_install",
            reason="default policy allows package manager installation",
        ),
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["apt-get", "install"]},
            category="default_dependency_install",
            reason="default policy allows package manager installation",
        ),
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["dnf", "install"]},
            category="default_dependency_install",
            reason="default policy allows package manager installation",
        ),
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["yum", "install"]},
            category="default_dependency_install",
            reason="default policy allows package manager installation",
        ),
        CommandPolicyRule(
            action="allow",
            match={"argv_prefix": ["apk", "add"]},
            category="default_dependency_install",
            reason="default policy allows package manager installation",
        ),
    )
)


def normalize_command_policy(value: Any) -> Optional[CommandPolicyConfig]:
    if value is None:
        return None
    if not isinstance(value, dict):
        return None

    rules = []
    for item in value.get("rules") or []:
        if not isinstance(item, dict):
            continue
        action = _normalize_policy_action(item.get("action"))
        match = item.get("match")
        if action is None or not isinstance(match, dict):
            continue
        category = _nonempty_string(item.get("category")) or "runtime_policy"
        reason = _nonempty_string(item.get("reason")) or (
            f"matched runtime command policy rule: {category}"
        )
        rules.append(
            CommandPolicyRule(
                action=action,
                match=match,
                category=category,
                reason=reason,
                next_step=_nonempty_string(item.get("next_step")),
            )
        )

    default_action = _normalize_policy_action(value.get("default_action"))
    default_category = (
        _nonempty_string(value.get("default_category")) or "runtime_policy_default"
    )
    default_reason = (
        _nonempty_string(value.get("default_reason"))
        or "no runtime command policy rule matched"
    )
    return CommandPolicyConfig(
        rules=tuple(rules),
        default_action=default_action,
        default_category=default_category,
        default_reason=default_reason,
    )


def _normalize_policy_action(value: Any) -> Optional[PolicyAction]:
    normalized = (str(value or "")).strip().lower()
    if normalized in {"allow", "ask", "deny"}:
        return normalized  # pyright: ignore[reportReturnType]
    return None


def _nonempty_string(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


class SandboxPolicyGateway:
    """Classify shell commands with a small, explicit policy surface."""

    KNOWN_SAFE_COMMANDS = {
        "cat",
        "date",
        "du",
        "env",
        "grep",
        "head",
        "ls",
        "pwd",
        "rg",
        "sed",
        "tail",
        "test",
        "true",
        "uname",
        "wc",
        "whoami",
    }
    KNOWN_SAFE_GIT_SUBCOMMANDS = {
        "branch",
        "diff",
        "log",
        "ls-files",
        "remote",
        "rev-parse",
        "show",
        "status",
    }

    DANGEROUS_COMMANDS = {
        "at",
        "batch",
        "crontab",
        "dd",
        "fdisk",
        "format",
        "halt",
        "init",
        "insmod",
        "mkfs",
        "modprobe",
        "parted",
        "passwd",
        "poweroff",
        "reboot",
        "rmmod",
        "service",
        "shutdown",
        "su",
        "sudo",
        "systemctl",
        "useradd",
        "userdel",
        "usermod",
        "visudo",
        "wipefs",
    }

    DENY_SUBSTRINGS = (
        "rm -rf /",
        "rm -rf /*",
        "rm -rf ~",
        ":() { :|:& };:",
        "mkfs.",
        "chmod 777 /",
        "chown -r root",
        "mv / ",
        "mv /* ",
        "> /dev/sda",
        "> /dev/sdb",
        "> /dev/nvme",
    )

    _PIPE_EXEC_RE = re.compile(
        r"\b(curl|wget|fetch)\b[^|;&]+?\|\s*(sudo\s+)?(ba)?sh\b",
        re.IGNORECASE,
    )
    _STDOUT_REDIRECT_RE = re.compile(r"(^|[^\d])>>?(?![&])")
    _STDOUT_REDIRECT_TARGET_RE = re.compile(r"(^|[^\d])>>?(?![&])\s*(\S+)")
    _SEGMENT_SPLIT_RE = re.compile(r"[|;&]+")

    def __init__(self, approval_mode: Optional[str] = None, command_policy: Any = None):
        self.approval_mode = (
            normalize_approval_mode(approval_mode) or approval_mode_from_env()
        )
        self.command_policy = (
            normalize_command_policy(command_policy)
            if command_policy is not None
            else DEFAULT_COMMAND_POLICY
        )

    def evaluate_shell_command(
        self, command: str, sandbox_mode: Optional[str] = None
    ) -> SandboxPolicyDecision:
        command = (command or "").strip()
        if not command:
            return SandboxPolicyDecision(
                action="deny",
                category="invalid_command",
                reason="command is empty",
                next_step="Provide a concrete shell command.",
            )

        lowered = command.lower()
        parts = self._parse_command(command)

        for substring in self.DENY_SUBSTRINGS:
            if substring in lowered:
                return SandboxPolicyDecision(
                    action="deny",
                    category="destructive_system_operation",
                    reason=f"command contains blocked pattern {substring!r}",
                    next_step="Use a narrower command, or ask the user to run this manually.",
                )

        if self._PIPE_EXEC_RE.search(command):
            return SandboxPolicyDecision(
                action="deny",
                category="download_exec",
                reason="download-and-execute shell pipelines are blocked",
                next_step="Download the script, inspect it, then run explicit commands if needed.",
            )

        segments = [s.strip() for s in self._SEGMENT_SPLIT_RE.split(command)]
        nonempty_segments = [segment for segment in segments if segment]
        for segment in segments:
            decision = self._evaluate_segment(segment, sandbox_mode=sandbox_mode)
            if decision.action == "deny":
                return decision

        if len(nonempty_segments) <= 1:
            configured_decision = self._evaluate_configured_policy(command, parts)
            if configured_decision is not None:
                return self._apply_approval_mode(configured_decision)

        for segment in segments:
            decision = self._evaluate_segment(segment, sandbox_mode=sandbox_mode)
            if decision.action != "allow":
                return self._apply_approval_mode(decision)

        if self._STDOUT_REDIRECT_RE.search(command):
            if self._stdout_redirection_targets_allowed(command):
                return SandboxPolicyDecision(
                    action="allow",
                    category="shell_redirection",
                    reason="ordinary stdout redirection is executable in the sandbox",
                )
            return self._apply_approval_mode(
                SandboxPolicyDecision(
                    action="ask",
                    category="shell_redirection",
                    reason="stdout redirection target may be unsafe",
                    next_step="Use a workspace-scoped file path for stdout redirection.",
                )
            )

        if self.approval_mode == "untrusted" and not self._is_known_safe_command(
            segments
        ):
            return SandboxPolicyDecision(
                action="ask",
                category="untrusted_command",
                reason="approval mode untrusted only auto-runs known safe read-only commands",
                next_step="Confirm this command before running it, or use a read-only probe command.",
            )

        return SandboxPolicyDecision(
            action="allow",
            category="default_allow",
            reason="no sandbox policy rule matched",
        )

    def _evaluate_configured_policy(
        self, command: str, parts: Optional[list[str]]
    ) -> Optional[SandboxPolicyDecision]:
        policy = self.command_policy
        if policy is None:
            return None

        for rule in policy.rules:
            if self._rule_matches(rule.match, command, parts):
                return SandboxPolicyDecision(
                    action=rule.action,
                    category=rule.category,
                    reason=rule.reason,
                    next_step=rule.next_step,
                )

        if policy.default_action is None:
            return None
        return SandboxPolicyDecision(
            action=policy.default_action,
            category=policy.default_category,
            reason=policy.default_reason,
        )

    def _rule_matches(
        self, matcher: dict[str, Any], command: str, parts: Optional[list[str]]
    ) -> bool:
        exact_command = _nonempty_string(matcher.get("command"))
        if exact_command is not None and command == exact_command:
            return True

        argv = self._string_list(matcher.get("argv"))
        if argv is not None and parts == argv:
            return True

        argv_prefix = self._string_list(matcher.get("argv_prefix"))
        if argv_prefix is not None and parts is not None:
            if (
                len(parts) >= len(argv_prefix)
                and parts[: len(argv_prefix)] == argv_prefix
            ):
                return True

        pattern = _nonempty_string(matcher.get("pattern"))
        if pattern is not None:
            try:
                if re.search(pattern, command):
                    return True
            except re.error:
                return False

        return False

    def _stdout_redirection_targets_allowed(self, command: str) -> bool:
        matches = list(self._STDOUT_REDIRECT_TARGET_RE.finditer(command))
        if not matches:
            return False
        for match in matches:
            target = match.group(2).strip("'\"").lower()
            if target.startswith(("/dev/sd", "/dev/nvme")):
                return False
        return True

    @staticmethod
    def _parse_command(command: str) -> Optional[list[str]]:
        try:
            return shlex.split(command)
        except ValueError:
            return None

    @staticmethod
    def _string_list(value: Any) -> Optional[list[str]]:
        if not isinstance(value, list):
            return None
        result = []
        for item in value:
            if not isinstance(item, str):
                return None
            result.append(item)
        return result

    def _evaluate_segment(
        self, segment: str, sandbox_mode: Optional[str] = None
    ) -> SandboxPolicyDecision:
        try:
            parts = shlex.split(segment)
        except ValueError:
            return SandboxPolicyDecision(
                action="ask",
                category="shell_parse",
                reason="command segment could not be parsed safely",
                next_step="Rewrite the command with explicit quoting.",
            )
        if not parts:
            return SandboxPolicyDecision(
                action="allow", category="empty_segment", reason="empty segment"
            )

        base = parts[0].split("/")[-1].lower()
        if base in self.DANGEROUS_COMMANDS or base.startswith("mkfs."):
            return SandboxPolicyDecision(
                action="deny",
                category="destructive_system_operation",
                reason=f"{base} is blocked by sandbox policy",
                next_step="Use a non-privileged, workspace-scoped command instead.",
            )

        git_decision = self._evaluate_git(parts)
        if git_decision.action != "allow":
            return git_decision

        package_decision = self._evaluate_package_manager(parts)
        if package_decision.action != "allow":
            return package_decision

        filesystem_decision = self._evaluate_destructive_filesystem(parts)
        if filesystem_decision.action != "allow":
            return filesystem_decision

        process_decision = self._evaluate_process_control(parts)
        if process_decision.action != "allow":
            return process_decision

        return SandboxPolicyDecision(
            action="allow",
            category="segment_allow",
            reason=f"{base} did not match a policy rule",
        )

    def _apply_approval_mode(
        self, decision: SandboxPolicyDecision
    ) -> SandboxPolicyDecision:
        if decision.action != "ask" or self.approval_mode != "never":
            return decision
        return SandboxPolicyDecision(
            action="deny",
            category=f"{decision.category}_approval_disabled",
            reason=(
                f"{decision.reason}; approval mode never disallows confirmation prompts"
            ),
            next_step="Use a safer command or change approval mode before retrying.",
        )

    def _is_known_safe_command(self, segments: list[str]) -> bool:
        for segment in segments:
            try:
                parts = shlex.split(segment)
            except ValueError:
                return False
            if not parts:
                continue
            base = parts[0].split("/")[-1].lower()
            args = [p.lower() for p in parts[1:]]
            if base == "git":
                if not args or args[0] not in self.KNOWN_SAFE_GIT_SUBCOMMANDS:
                    return False
                continue
            if base == "find" and not any(arg in {"-delete", "-exec"} for arg in args):
                continue
            if base not in self.KNOWN_SAFE_COMMANDS:
                return False
        return True

    def _evaluate_git(self, parts: list[str]) -> SandboxPolicyDecision:
        if not parts or parts[0].split("/")[-1].lower() != "git":
            return self._allow()
        subcommand = parts[1].lower() if len(parts) > 1 else ""

        if subcommand == "push":
            lower_parts = [p.lower() for p in parts]
            protected = {"main", "master"}
            forced = any(
                p in {"-f", "--force"} or p.startswith("--force-with-lease")
                for p in lower_parts
            )
            if forced and protected.intersection(lower_parts):
                return SandboxPolicyDecision(
                    action="deny",
                    category="git_force_push_protected",
                    reason="force-pushing a protected branch is blocked",
                    next_step="Ask the user to run the force-push manually if it is intentional.",
                )
            return SandboxPolicyDecision(
                action="ask",
                category="git_remote_write",
                reason="git push changes a remote repository",
                next_step="Confirm the remote, branch, and commit range before running git push.",
            )

        if subcommand == "reset" and "--hard" in [p.lower() for p in parts[2:]]:
            return SandboxPolicyDecision(
                action="ask",
                category="git_worktree_destructive",
                reason="git reset --hard can discard local work",
                next_step="Confirm the target ref and inspect git status before resetting.",
            )

        if subcommand == "clean":
            return SandboxPolicyDecision(
                action="ask",
                category="git_worktree_destructive",
                reason="git clean can delete untracked files",
                next_step="Run git clean -nd first, then ask for confirmation if deletion is required.",
            )

        if subcommand in {"branch", "tag"} and "-d" in [p.lower() for p in parts[2:]]:
            return SandboxPolicyDecision(
                action="ask",
                category="git_ref_delete",
                reason=f"git {subcommand} deletion requires confirmation",
                next_step="Confirm the ref name before deleting it.",
            )

        return self._allow()

    def _evaluate_package_manager(self, parts: list[str]) -> SandboxPolicyDecision:
        if not parts:
            return self._allow()
        base = parts[0].split("/")[-1].lower()
        args = [p.lower() for p in parts[1:]]

        if base in {"pip", "pip3"} and args[:1] == ["install"]:
            return self._package_ask("pip install")

        if base in {"python", "python3"} and len(args) >= 3:
            if args[0] == "-m" and args[1] == "pip" and args[2] == "install":
                return self._package_ask("python -m pip install")

        if base == "npm" and args and args[0] in {"install", "i", "add"}:
            return self._package_ask("npm install")
        if base == "pnpm" and args and args[0] in {"install", "i", "add"}:
            return self._package_ask("pnpm install")
        if base == "yarn" and args and args[0] in {"add", "install"}:
            return self._package_ask("yarn install")
        if base == "bun" and args and args[0] in {"add", "install"}:
            return self._package_ask("bun install")

        if base in {"brew", "apt", "apt-get", "dnf", "yum", "apk"}:
            if args and args[0] in {"install", "upgrade", "remove", "add", "del"}:
                return self._package_ask(f"{base} {args[0]}")

        return self._allow()

    def _evaluate_destructive_filesystem(
        self, parts: list[str]
    ) -> SandboxPolicyDecision:
        base = parts[0].split("/")[-1].lower() if parts else ""
        args = [p.lower() for p in parts[1:]]

        if base == "rm" and any(("r" in p and p.startswith("-")) for p in args):
            return SandboxPolicyDecision(
                action="ask",
                category="filesystem_delete",
                reason="recursive deletion requires confirmation",
                next_step="Confirm the path and prefer moving files aside before deletion.",
            )

        if base in {"chmod", "chown"}:
            return SandboxPolicyDecision(
                action="ask",
                category="permission_change",
                reason=f"{base} changes file permissions or ownership",
                next_step="Confirm the exact path and mode/owner before applying it.",
            )

        return self._allow()

    def _evaluate_process_control(self, parts: list[str]) -> SandboxPolicyDecision:
        base = parts[0].split("/")[-1].lower() if parts else ""
        if base in {"kill", "killall", "pkill"}:
            return SandboxPolicyDecision(
                action="ask",
                category="process_control",
                reason=f"{base} can terminate unrelated processes",
                next_step="Confirm the target process before terminating it.",
            )
        return self._allow()

    @staticmethod
    def _package_ask(command_name: str) -> SandboxPolicyDecision:
        return SandboxPolicyDecision(
            action="ask",
            category="dependency_install",
            reason=f"{command_name} can install or modify executable dependencies",
            next_step="Confirm the package names and source before installing dependencies.",
        )

    @staticmethod
    def _allow() -> SandboxPolicyDecision:
        return SandboxPolicyDecision(
            action="allow", category="rule_allow", reason="rule did not match"
        )


__all__ = [
    "ApprovalMode",
    "CommandPolicyConfig",
    "CommandPolicyRule",
    "PolicyAction",
    "SandboxPolicyDecision",
    "SandboxPolicyGateway",
    "approval_mode_from_env",
    "normalize_command_policy",
    "normalize_approval_mode",
]
