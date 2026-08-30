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


def validate_read_only_shell_command(command: str) -> None:
    """Allow common inspection pipelines and reject everything else.

    This intentionally accepts a small grammar. A Plan can inspect source and
    Git state through Shell without granting a general-purpose host process.
    """

    value = command.strip()
    if not value:
        raise PermissionError("read-only shell command must not be empty")
    if "||" in value or any(token in value for token in _FORBIDDEN_SHELL_SYNTAX):
        raise PermissionError(
            "shell control or redirection is unavailable in read-only mode"
        )

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
        arguments = argv[1:]
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


__all__ = ["validate_read_only_shell_command"]
