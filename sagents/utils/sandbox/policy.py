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
from typing import Literal, Optional


PolicyAction = Literal["allow", "ask", "deny"]
ApprovalMode = Literal["untrusted", "on-request", "never"]

DEFAULT_APPROVAL_MODE: ApprovalMode = "on-request"
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
    _SEGMENT_SPLIT_RE = re.compile(r"[|;&]+")

    def __init__(self, approval_mode: Optional[str] = None):
        self.approval_mode = (
            normalize_approval_mode(approval_mode) or approval_mode_from_env()
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
        for segment in segments:
            decision = self._evaluate_segment(segment, sandbox_mode=sandbox_mode)
            if decision.action != "allow":
                return self._apply_approval_mode(decision)

        if self._STDOUT_REDIRECT_RE.search(command):
            return self._apply_approval_mode(
                SandboxPolicyDecision(
                    action="ask",
                    category="shell_redirection",
                    reason="stdout redirection may write or replace files",
                    next_step="Confirm the target path, or use the file editing tool for workspace files.",
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
    "PolicyAction",
    "SandboxPolicyDecision",
    "SandboxPolicyGateway",
    "approval_mode_from_env",
    "normalize_approval_mode",
]
