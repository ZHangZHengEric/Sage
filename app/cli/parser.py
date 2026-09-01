import argparse


def _add_goal_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--goal",
        dest="goal_objective",
        help="Set or replace the current session goal objective",
    )
    parser.add_argument(
        "--goal-status",
        dest="goal_status",
        choices=["active", "paused", "completed"],
        help="Override the goal status for this request",
    )
    parser.add_argument(
        "--clear-goal",
        dest="clear_goal",
        action="store_true",
        help="Clear the current session goal",
    )


def _add_provider_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--name", help="Provider display name")
    parser.add_argument("--base-url", dest="base_url", help="Provider base URL")
    parser.add_argument("--api-key", dest="api_key", help="Provider API key")
    parser.add_argument("--model", help="Provider model name")
    parser.add_argument("--max-tokens", dest="max_tokens", type=int)
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--top-p", dest="top_p", type=float)
    parser.add_argument("--presence-penalty", dest="presence_penalty", type=float)
    parser.add_argument("--max-model-len", dest="max_model_len", type=int)

    multimodal_group = parser.add_mutually_exclusive_group()
    multimodal_group.add_argument(
        "--supports-multimodal",
        dest="supports_multimodal",
        action="store_true",
        help="Mark the provider as multimodal-capable",
    )
    multimodal_group.add_argument(
        "--no-supports-multimodal",
        dest="supports_multimodal",
        action="store_false",
        help="Mark the provider as not multimodal-capable",
    )

    structured_group = parser.add_mutually_exclusive_group()
    structured_group.add_argument(
        "--supports-structured-output",
        dest="supports_structured_output",
        action="store_true",
        help="Mark the provider as supporting structured output",
    )
    structured_group.add_argument(
        "--no-supports-structured-output",
        dest="supports_structured_output",
        action="store_false",
        help="Mark the provider as not supporting structured output",
    )

    default_group = parser.add_mutually_exclusive_group()
    default_group.add_argument(
        "--set-default",
        dest="is_default",
        action="store_true",
        help="Mark the provider as default",
    )
    default_group.add_argument(
        "--unset-default",
        dest="is_default",
        action="store_false",
        help="Mark the provider as non-default",
    )
    parser.set_defaults(
        supports_multimodal=None,
        supports_structured_output=None,
        is_default=None,
    )


def _add_session_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--sandbox-type",
        dest="sandbox_type",
        choices=["local", "remote", "passthrough"],
        default=None,
        help="Sandbox mode for this CLI session (overrides SAGE_SANDBOX_MODE)",
    )
    parser.add_argument(
        "--sandbox-approval-mode",
        dest="sandbox_approval_mode",
        default=None,
        help="Command approval policy for this run/session: untrusted, on-request, or never",
    )


def build_argument_parser() -> argparse.ArgumentParser:
    from app.cli.service import get_default_cli_max_loop_count, get_default_cli_user_id

    parser = argparse.ArgumentParser(prog="sage", description="Sage CLI MVP")
    subparsers = parser.add_subparsers(dest="command", required=True)
    default_user_id = get_default_cli_user_id()
    default_max_loop_count = get_default_cli_max_loop_count()

    v2_parser = subparsers.add_parser("v2", help="Manage SAgents v2 runtime data")
    v2_subparsers = v2_parser.add_subparsers(dest="v2_command", required=True)
    v2_migrate = v2_subparsers.add_parser(
        "migrate", help="Explicitly migrate a v3 SessionStore to v4"
    )
    v2_migrate.add_argument("--runtime-root", required=True)
    v2_migrate.add_argument("--dry-run", action="store_true")
    v2_migrate.add_argument(
        "--manifest",
        default=None,
        help="Also generate sage.v2.yaml from this sage/v1 manifest",
    )
    v2_migrate.add_argument("--verbose", action="store_true")

    run_parser = subparsers.add_parser("run", help="Run a single Sage task")
    run_parser.add_argument("task", help="Task prompt to execute")
    run_parser.add_argument("--session-id", dest="session_id")
    run_parser.add_argument("--user-id", dest="user_id", default=default_user_id)
    run_parser.add_argument("--agent-id", dest="agent_id")
    run_parser.add_argument(
        "--agent-config",
        dest="agent_config",
        help="Load an agent config JSON path or preset name, e.g. coding",
    )
    run_parser.add_argument(
        "--workspace", dest="workspace", help="Use a specific local workspace directory"
    )
    _add_session_runtime_args(run_parser)
    run_parser.add_argument(
        "--skill",
        dest="skills",
        action="append",
        default=[],
        help="Enable a skill by name (repeatable)",
    )
    run_parser.add_argument(
        "--agent-mode",
        dest="agent_mode",
        choices=["simple", "fibre", "team"],
        default=None,
    )
    run_parser.add_argument(
        "--max-loop-count",
        dest="max_loop_count",
        type=int,
        default=None,
        help=f"Maximum agent loop count (default: {default_max_loop_count}; agent config can override)",
    )
    run_parser.add_argument("--json", action="store_true", help="Print raw JSON events")
    run_parser.add_argument("--verbose", action="store_true", help="Show runtime logs")
    run_parser.add_argument(
        "--stats", action="store_true", help="Print execution summary after completion"
    )
    _add_goal_args(run_parser)

    chat_parser = subparsers.add_parser(
        "chat", help="Start an interactive Sage chat session"
    )
    chat_parser.add_argument("--session-id", dest="session_id")
    chat_parser.add_argument("--user-id", dest="user_id", default=default_user_id)
    chat_parser.add_argument("--agent-id", dest="agent_id")
    chat_parser.add_argument(
        "--agent-config",
        dest="agent_config",
        help="Load an agent config JSON path or preset name, e.g. coding",
    )
    chat_parser.add_argument(
        "--workspace", dest="workspace", help="Use a specific local workspace directory"
    )
    _add_session_runtime_args(chat_parser)
    chat_parser.add_argument(
        "--skill",
        dest="skills",
        action="append",
        default=[],
        help="Enable a skill by name (repeatable)",
    )
    chat_parser.add_argument(
        "--agent-mode",
        dest="agent_mode",
        choices=["simple", "fibre", "team"],
        default=None,
    )
    chat_parser.add_argument(
        "--max-loop-count",
        dest="max_loop_count",
        type=int,
        default=None,
        help=f"Maximum agent loop count per turn (default: {default_max_loop_count}; agent config can override)",
    )
    chat_parser.add_argument(
        "--json", action="store_true", help="Print raw JSON events"
    )
    chat_parser.add_argument("--verbose", action="store_true", help="Show runtime logs")
    chat_parser.add_argument(
        "--stats", action="store_true", help="Print execution summary for each turn"
    )
    _add_goal_args(chat_parser)

    resume_parser = subparsers.add_parser(
        "resume", help="Resume an existing Sage chat session"
    )
    resume_parser.add_argument("session_id", help="Session id to resume")
    resume_parser.add_argument("--user-id", dest="user_id", default=default_user_id)
    resume_parser.add_argument("--agent-id", dest="agent_id")
    resume_parser.add_argument(
        "--agent-config",
        dest="agent_config",
        help="Load an agent config JSON path or preset name, e.g. coding",
    )
    resume_parser.add_argument(
        "--workspace", dest="workspace", help="Use a specific local workspace directory"
    )
    _add_session_runtime_args(resume_parser)
    resume_parser.add_argument(
        "--skill",
        dest="skills",
        action="append",
        default=[],
        help="Enable a skill by name (repeatable)",
    )
    resume_parser.add_argument(
        "--agent-mode",
        dest="agent_mode",
        choices=["simple", "fibre", "team"],
        default=None,
    )
    resume_parser.add_argument(
        "--max-loop-count",
        dest="max_loop_count",
        type=int,
        default=None,
        help=f"Maximum agent loop count per turn (default: {default_max_loop_count}; agent config can override)",
    )
    resume_parser.add_argument(
        "--json", action="store_true", help="Print raw JSON events"
    )
    resume_parser.add_argument(
        "--verbose", action="store_true", help="Show runtime logs"
    )
    resume_parser.add_argument(
        "--stats", action="store_true", help="Print execution summary for each turn"
    )
    _add_goal_args(resume_parser)

    doctor_parser = subparsers.add_parser(
        "doctor", help="Show local CLI/runtime configuration"
    )
    doctor_parser.add_argument(
        "--probe-provider",
        action="store_true",
        help="Run a lightweight connection probe against the default provider",
    )
    doctor_parser.add_argument(
        "--json", action="store_true", help="Print doctor information as JSON"
    )
    doctor_parser.add_argument(
        "--verbose", action="store_true", help="Show runtime logs"
    )

    sessions_parser = subparsers.add_parser("sessions", help="List recent CLI sessions")
    sessions_parser.add_argument("--user-id", dest="user_id", default=default_user_id)
    sessions_parser.add_argument(
        "--limit", type=int, default=20, help="Maximum number of sessions to show"
    )
    sessions_parser.add_argument("--search", help="Filter sessions by title")
    sessions_parser.add_argument("--agent-id", dest="agent_id")
    sessions_parser.add_argument(
        "--json", action="store_true", help="Print sessions as JSON"
    )
    sessions_parser.add_argument(
        "--verbose", action="store_true", help="Show runtime logs"
    )
    sessions_subparsers = sessions_parser.add_subparsers(dest="sessions_command")
    sessions_inspect_parser = sessions_subparsers.add_parser(
        "inspect", help="Inspect a specific CLI session"
    )
    sessions_inspect_parser.add_argument(
        "session_id", help="Session id to inspect, or `latest`"
    )
    sessions_inspect_parser.add_argument(
        "--user-id", dest="user_id", default=default_user_id
    )
    sessions_inspect_parser.add_argument("--agent-id", dest="agent_id")
    sessions_inspect_parser.add_argument(
        "--messages",
        dest="message_limit",
        type=int,
        default=5,
        help="Number of recent messages to preview",
    )
    sessions_inspect_parser.add_argument(
        "--json", action="store_true", help="Print session details as JSON"
    )
    sessions_inspect_parser.add_argument(
        "--verbose", action="store_true", help="Show runtime logs"
    )

    agents_parser = subparsers.add_parser("agents", help="List visible CLI agents")
    agents_parser.add_argument("--user-id", dest="user_id", default=default_user_id)
    agents_parser.add_argument(
        "--json", action="store_true", help="Print agents as JSON"
    )
    agents_parser.add_argument(
        "--verbose", action="store_true", help="Show runtime logs"
    )

    skills_parser = subparsers.add_parser("skills", help="List available CLI skills")
    skills_parser.add_argument("--user-id", dest="user_id", default=default_user_id)
    skills_parser.add_argument(
        "--agent-id",
        dest="agent_id",
        help="Show the skills currently available to a specific agent",
    )
    skills_parser.add_argument(
        "--workspace",
        dest="workspace",
        help="Include skills from a specific workspace directory",
    )
    skills_parser.add_argument(
        "--json", action="store_true", help="Print skills as JSON"
    )

    tui_parser = subparsers.add_parser("tui", help="Start the Sage Terminal TUI")
    tui_parser.add_argument(
        "terminal_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to the terminal TUI, e.g. --workspace /path/to/repo",
    )

    config_parser = subparsers.add_parser("config", help="Inspect CLI configuration")
    config_subparsers = config_parser.add_subparsers(
        dest="config_command", required=True
    )
    config_show_parser = config_subparsers.add_parser(
        "show", help="Show effective CLI config"
    )
    config_show_parser.add_argument(
        "--json", action="store_true", help="Print config as JSON"
    )
    config_init_parser = config_subparsers.add_parser(
        "init", help="Create a minimal local CLI config"
    )
    config_init_parser.add_argument(
        "--path",
        default=None,
        help="Path to write the config file (defaults to ~/.sage/.sage_env)",
    )
    config_init_parser.add_argument(
        "--force", action="store_true", help="Overwrite an existing config file"
    )
    config_init_parser.add_argument(
        "--json", action="store_true", help="Print init result as JSON"
    )

    provider_parser = subparsers.add_parser(
        "provider", help="Manage local LLM providers"
    )
    provider_subparsers = provider_parser.add_subparsers(
        dest="provider_command", required=True
    )

    provider_list_parser = provider_subparsers.add_parser(
        "list", help="List providers visible to a CLI user"
    )
    provider_list_parser.add_argument(
        "--user-id", dest="user_id", default=default_user_id
    )
    provider_list_parser.add_argument(
        "--default-only",
        action="store_true",
        help="Show only default providers for the selected user",
    )
    provider_list_parser.add_argument("--model", help="Filter by exact model name")
    provider_list_parser.add_argument(
        "--name-contains",
        dest="name_contains",
        help="Filter by provider name substring",
    )
    provider_list_parser.add_argument(
        "--json", action="store_true", help="Print providers as JSON"
    )
    provider_list_parser.add_argument(
        "--verbose", action="store_true", help="Show runtime logs"
    )

    provider_inspect_parser = provider_subparsers.add_parser(
        "inspect", help="Inspect a specific provider"
    )
    provider_inspect_parser.add_argument("provider_id", help="Provider id to inspect")
    provider_inspect_parser.add_argument(
        "--user-id", dest="user_id", default=default_user_id
    )
    provider_inspect_parser.add_argument(
        "--json", action="store_true", help="Print provider details as JSON"
    )
    provider_inspect_parser.add_argument(
        "--verbose", action="store_true", help="Show runtime logs"
    )

    provider_verify_parser = provider_subparsers.add_parser(
        "verify",
        help="Probe a provider configuration without saving it",
    )
    _add_provider_config_args(provider_verify_parser)
    provider_verify_parser.add_argument(
        "--json", action="store_true", help="Print verification result as JSON"
    )
    provider_verify_parser.add_argument(
        "--verbose", action="store_true", help="Show runtime logs"
    )

    provider_create_parser = provider_subparsers.add_parser(
        "create",
        help="Create a provider; omitted API settings fall back to current default CLI env",
    )
    provider_create_parser.add_argument(
        "--user-id", dest="user_id", default=default_user_id
    )
    _add_provider_config_args(provider_create_parser)
    provider_create_parser.add_argument(
        "--json", action="store_true", help="Print saved provider as JSON"
    )
    provider_create_parser.add_argument(
        "--verbose", action="store_true", help="Show runtime logs"
    )

    provider_update_parser = provider_subparsers.add_parser(
        "update",
        help="Update an existing provider; only supplied fields are changed",
    )
    provider_update_parser.add_argument("provider_id", help="Provider id to update")
    provider_update_parser.add_argument(
        "--user-id", dest="user_id", default=default_user_id
    )
    _add_provider_config_args(provider_update_parser)
    provider_update_parser.add_argument(
        "--json", action="store_true", help="Print updated provider as JSON"
    )
    provider_update_parser.add_argument(
        "--verbose", action="store_true", help="Show runtime logs"
    )

    provider_delete_parser = provider_subparsers.add_parser(
        "delete", help="Delete an existing provider"
    )
    provider_delete_parser.add_argument("provider_id", help="Provider id to delete")
    provider_delete_parser.add_argument(
        "--user-id", dest="user_id", default=default_user_id
    )
    provider_delete_parser.add_argument(
        "--json", action="store_true", help="Print deletion result as JSON"
    )
    provider_delete_parser.add_argument(
        "--verbose", action="store_true", help="Show runtime logs"
    )

    _add_v2_parser(v2_subparsers, default_user_id=default_user_id)
    return parser


def _add_v2_common_args(parser: argparse.ArgumentParser, *, default_user_id: str) -> None:
    from app.cli.v2.package import DEFAULT_PRESET, available_presets

    parser.add_argument(
        "--preset",
        dest="preset",
        choices=list(available_presets()),
        default=DEFAULT_PRESET,
        help=f"Built-in agent preset used when no --package is given (default: {DEFAULT_PRESET})",
    )
    parser.add_argument(
        "--package",
        dest="package",
        help="Path to a sage.yaml agent package (overrides --preset and model env config)",
    )
    parser.add_argument(
        "--workspace",
        dest="workspace",
        help="Workspace directory exposed to the sandbox (default: current directory)",
    )
    parser.add_argument(
        "--session-root",
        dest="session_root",
        help="Directory for the v2 session store (default: ~/.sage/v2/runtime)",
    )
    parser.add_argument("--user-id", dest="user_id", default=default_user_id)
    parser.add_argument(
        "--approval-mode",
        dest="approval_mode",
        choices=["ask", "approve-all", "deny-all"],
        default=None,
        help="How tool approvals are answered (default: ask on a TTY, deny-all otherwise)",
    )
    parser.add_argument(
        "--read-only",
        dest="read_only",
        action="store_true",
        help="Restrict the sandbox to read/list operations and read-only shell commands",
    )
    parser.add_argument(
        "--mode",
        dest="mode",
        choices=["normal", "plan", "goal"],
        default="normal",
        help=(
            "v2 invocation mode: plan = inspect only (read-only sandbox) and submit a "
            "plan for approval; goal = must explicitly report completion"
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print native v2 events as NDJSON and read approval decisions from stdin",
    )
    parser.add_argument("--verbose", action="store_true", help="Show runtime logs")


def _add_v2_parser(v2_subparsers, *, default_user_id: str) -> None:
    """在已有的 ``sage v2`` 子命令组上挂载进程内运行相关的子命令。"""

    run_parser = v2_subparsers.add_parser(
        "run", help="Run a single task in-process on the v2 runtime"
    )
    run_parser.add_argument("task", help="Task prompt to execute")
    run_parser.add_argument(
        "--session-id",
        dest="session_id",
        help="Continue an existing v2 session instead of creating a new one",
    )
    _add_v2_common_args(run_parser, default_user_id=default_user_id)

    chat_parser = v2_subparsers.add_parser(
        "chat", help="Start an interactive multi-turn session on the v2 runtime"
    )
    chat_parser.add_argument(
        "--session-id",
        dest="session_id",
        help="Continue an existing v2 session instead of creating a new one",
    )
    _add_v2_common_args(chat_parser, default_user_id=default_user_id)

    resume_parser = v2_subparsers.add_parser(
        "resume", help="Resume an existing v2 session interactively"
    )
    resume_parser.add_argument("session_id", help="v2 session id to resume")
    _add_v2_common_args(resume_parser, default_user_id=default_user_id)

    sessions_parser = v2_subparsers.add_parser(
        "sessions", help="List v2 sessions under a session root"
    )
    sessions_parser.add_argument(
        "--limit", type=int, default=20, help="Maximum number of sessions to show"
    )
    sessions_parser.add_argument(
        "--session-root",
        dest="session_root",
        help="Directory of the v2 session store (default: ~/.sage/v2/runtime)",
    )
    sessions_parser.add_argument(
        "--json", action="store_true", help="Print sessions as JSON"
    )
    sessions_parser.add_argument(
        "--verbose", action="store_true", help="Show runtime logs"
    )
    sessions_subparsers = sessions_parser.add_subparsers(dest="sessions_command")
    inspect_parser = sessions_subparsers.add_parser(
        "inspect", help="Replay the user/assistant transcript of one v2 session"
    )
    inspect_parser.add_argument("session_id", help="v2 session id to inspect")
    inspect_parser.add_argument(
        "--session-root",
        dest="session_root",
        help="Directory of the v2 session store (default: ~/.sage/v2/runtime)",
    )
    inspect_parser.add_argument(
        "--json", action="store_true", help="Print the transcript as JSON"
    )
    inspect_parser.add_argument(
        "--verbose", action="store_true", help="Show runtime logs"
    )
