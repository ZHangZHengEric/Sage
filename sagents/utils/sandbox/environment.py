"""Environment boundary for agent-controlled processes.

The Sage server process owns credentials and deployment configuration. Agent
commands and code must not inherit that process environment wholesale.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Optional


# Keep this list intentionally small. In particular, do not add deployment,
# cloud, database, authentication, proxy, or provider variables here.
AGENT_PARENT_ENV_ALLOWLIST = frozenset(
    {
        "COLORTERM",
        "COMSPEC",
        "FORCE_COLOR",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "NO_COLOR",
        "NUMBER_OF_PROCESSORS",
        "OS",
        "PATH",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
        "PYTHONIOENCODING",
        "PYTHONPATH",
        "PYTHONUNBUFFERED",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "SYSTEMROOT",
        "TERM",
        "TMP",
        "TMPDIR",
        "TZ",
        "WINDIR",
    }
)

DESKTOP_PROCESS_MARKER = "SAGE_INTERNAL_DESKTOP_PROCESS"
SERVER_PROCESS_MARKER = "SAGE_INTERNAL_SERVER_PROCESS"


def is_desktop_process(
    environment: Optional[Mapping[str, str]] = None,
) -> bool:
    source = os.environ if environment is None else environment
    return source.get(DESKTOP_PROCESS_MARKER) == "1"


def is_server_process(
    environment: Optional[Mapping[str, str]] = None,
) -> bool:
    source = os.environ if environment is None else environment
    return source.get(SERVER_PROCESS_MARKER) == "1"


def build_agent_environment(
    extra_env: Optional[Mapping[str, object]] = None,
    *,
    home_dir: Optional[str] = None,
    parent_env: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """Build a minimal environment for an agent-controlled child process.

    ``parent_env`` is injectable for tests. Production callers should omit it
    so the current process environment is used only as the source for the
    explicit allowlist above.
    """

    source = os.environ if parent_env is None else parent_env
    # Server always wins if a deployment accidentally supplies both markers.
    desktop_process = is_desktop_process(source) and not is_server_process(source)
    if desktop_process:
        # Desktop is an explicit single-user local trust boundary. Preserve its
        # existing tool/runtime behavior; server and CLI processes stay strict.
        env = {str(name): str(value) for name, value in source.items()}
    else:
        env = {
            name: str(source[name])
            for name in AGENT_PARENT_ENV_ALLOWLIST
            if source.get(name) is not None
        }
        env.setdefault("PATH", os.defpath)

    if home_dir and not desktop_process:
        isolated_home = os.path.abspath(home_dir)
        env["HOME"] = isolated_home
        if os.name == "nt":
            env["USERPROFILE"] = isolated_home

    if extra_env:
        env.update({str(name): str(value) for name, value in extra_env.items()})

    return env
