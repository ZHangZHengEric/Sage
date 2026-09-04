"""Fail-closed validation for shell inspection in a read-only sandbox."""

from __future__ import annotations

import shlex
from pathlib import PurePath


_SIMPLE_READ_COMMANDS = {
    "basename",
    "cat",
    "dirname",
    "du",
    "file",
    "grep",
    "head",
    "ls",
    "pwd",
    "realpath",
    "rg",
    "stat",
    "tail",
    "tree",
    "wc",
}
_READ_ONLY_GIT_COMMANDS = {
    "blame",
    "describe",
    "diff",
    "for-each-ref",
    "grep",
    "log",
    "ls-files",
    "ls-tree",
    "name-rev",
    "rev-parse",
    "shortlog",
    "show",
    "status",
}
_FORBIDDEN_SHELL_SYNTAX = (";", "&", ">", "<", "`", "$(", "${", "\n", "\r")
_FIND_SIDE_EFFECTS = {
    "-delete",
    "-exec",
    "-execdir",
    "-fls",
    "-fprint",
    "-fprint0",
    "-fprintf",
    "-ok",
    "-okdir",
}


# Every executable the read-only grammar can start; hosts use it as the
# process allowlist for read-only sandboxes (no shell is part of it).
READ_ONLY_SHELL_EXECUTABLES: frozenset[str] = frozenset(
    {*_SIMPLE_READ_COMMANDS, "find", "git"}
)


def validate_read_only_shell_command(command: str) -> None:
    """Allow common inspection pipelines and reject everything else.

    This intentionally accepts a small grammar. A Plan can inspect source and
    Git state through Shell without granting a general-purpose host process.
    """

    parse_read_only_shell_command(command)


def parse_read_only_shell_command(command: str) -> tuple[tuple[str, ...], ...]:
    """Validate ``command`` and return its pipeline stages as argv tuples.

    Stages are meant to be started directly (no shell in between): the grammar
    has no expansion, redirection or control operators, and every executable
    must be a bare command name resolved through PATH.
    """

    value = command.strip()
    if not value:
        raise PermissionError("read-only shell command must not be empty")
    if "||" in value or any(token in value for token in _FORBIDDEN_SHELL_SYNTAX):
        raise PermissionError(
            "shell control or redirection is unavailable in read-only mode"
        )

    stages: list[tuple[str, ...]] = []
    for segment in value.split("|"):
        try:
            argv = shlex.split(segment)
        except ValueError as exc:
            raise PermissionError(
                "shell command is not valid in read-only mode"
            ) from exc
        if not argv:
            raise PermissionError(
                "empty pipeline stage is unavailable in read-only mode"
            )
        executable = PurePath(argv[0]).name
        if executable != argv[0]:
            raise PermissionError(
                "read-only shell commands must name executables without a path"
            )
        arguments = argv[1:]
        stages.append(tuple(argv))
        if any(_escapes_workspace(argument) for argument in arguments):
            raise PermissionError(
                "read-only shell paths must stay inside the workspace"
            )
        if executable in _SIMPLE_READ_COMMANDS:
            if executable == "rg" and any(
                argument == "--pre" or argument.startswith("--pre=")
                for argument in arguments
            ):
                raise PermissionError("rg --pre is unavailable in read-only mode")
            continue
        if executable == "find":
            if any(argument in _FIND_SIDE_EFFECTS for argument in arguments):
                raise PermissionError(
                    "mutating find actions are unavailable in read-only mode"
                )
            continue
        if executable == "git":
            _validate_git(arguments)
            continue
        raise PermissionError(
            f"executable {executable!r} is unavailable in read-only shell mode"
        )
    return tuple(stages)


def _escapes_workspace(argument: str) -> bool:
    if argument.startswith("-"):
        return False
    path = PurePath(argument)
    return path.is_absolute() or ".." in path.parts


def _validate_git(arguments: list[str]) -> None:
    if not arguments or arguments[0] not in _READ_ONLY_GIT_COMMANDS:
        raise PermissionError("Git operation is unavailable in read-only mode")
    if any(
        argument == "--ext-diff"
        or argument == "--textconv"
        or argument.startswith("--output")
        for argument in arguments[1:]
    ):
        raise PermissionError("Git output hooks are unavailable in read-only mode")


__all__ = [
    "READ_ONLY_SHELL_EXECUTABLES",
    "parse_read_only_shell_command",
    "validate_read_only_shell_command",
]
