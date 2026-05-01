import argparse
import json

from app.cli.formatting import (
    _print_message_preview,
    _print_provider_summary,
    _print_session_summary,
    _truncate,
)


async def doctor_command(args: argparse.Namespace) -> int:
    from app.cli.service import collect_doctor_info, probe_default_provider

    info = collect_doctor_info()
    if args.probe_provider:
        info["provider_probe"] = await probe_default_provider()
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    for key, value in info.items():
        if isinstance(value, dict):
            print(f"{key}:")
            for sub_key, sub_value in value.items():
                print(f"  {sub_key}: {sub_value}")
            continue
        if isinstance(value, list):
            print(f"{key}:")
            if not value:
                print("  (none)")
                continue
            for item in value:
                print(f"  - {item}")
            continue
        print(f"{key}: {value}")
    return 0


async def sessions_command(args: argparse.Namespace) -> int:
    from app.cli.service import cli_db_runtime, inspect_session, list_sessions

    if args.sessions_command == "inspect":
        async with cli_db_runtime(verbose=args.verbose):
            result = await inspect_session(
                session_id=args.session_id,
                user_id=args.user_id,
                agent_id=args.agent_id,
                message_limit=args.message_limit,
            )

        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        print("session:")
        _print_session_summary(result, prefix="session")
        print(f"user_id: {result.get('user_id')}")
        print(f"agent_id: {result.get('agent_id')}")
        print(f"created_at: {result.get('created_at')}")
        print(f"user_count: {result.get('user_count')}")
        print(f"agent_count: {result.get('agent_count')}")
        _print_message_preview(result.get("last_user_message"), label="last_user_message")
        _print_message_preview(result.get("last_assistant_message"), label="last_assistant_message")
        messages = result.get("recent_messages") or []
        print(f"recent_messages: {len(messages)}")
        if not messages:
            print("  (none)")
            return 0

        for item in messages:
            role = item.get("role") or "unknown"
            index = item.get("index")
            content = _truncate(item.get("content") or "", 120)
            print(f"  - #{index} [{role}] {content}")
        return 0

    async with cli_db_runtime(verbose=args.verbose):
        result = await list_sessions(
            user_id=args.user_id,
            limit=args.limit,
            search=args.search,
            agent_id=args.agent_id,
        )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"user_id: {result['user_id']}")
    print(f"total: {result['total']}")
    print(f"limit: {result['limit']}")
    sessions = result.get("list") or []
    if not sessions:
        print("sessions:\n  (none)")
        return 0

    print("sessions:")
    for item in sessions:
        session_id = item.get("session_id")
        title = _truncate(item.get("title") or "(untitled)", 56)
        updated_at = item.get("updated_at")
        agent_name = item.get("agent_name")
        message_count = item.get("message_count")
        print(
            f"  - {session_id} | {title} | "
            f"{agent_name} | updated={updated_at} | messages={message_count}"
        )
        last_message = item.get("last_message")
        if last_message:
            preview = _truncate(last_message.get("content") or "", 100)
            role = last_message.get("role") or "unknown"
            print(f"    last_message: [{role}] {preview}")
    return 0


async def skills_command(args: argparse.Namespace) -> int:
    from app.cli.service import cli_db_runtime, list_available_skills

    if args.agent_id:
        async with cli_db_runtime(verbose=False):
            result = await list_available_skills(
                user_id=args.user_id,
                agent_id=args.agent_id,
                workspace=args.workspace,
            )
    else:
        result = await list_available_skills(
            user_id=args.user_id,
            agent_id=None,
            workspace=args.workspace,
        )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"user_id: {result['user_id']}")
    if result.get("agent_id"):
        print(f"agent_id: {result['agent_id']}")
    if result.get("workspace"):
        print(f"workspace: {result['workspace']}")
    print(f"total: {result.get('total', 0)}")
    sources = result.get("sources") or []
    print("sources:")
    if not sources:
        print("  (none)")
    else:
        source_counts = result.get("source_counts") or {}
        for source in sources:
            source_name = source["source"]
            count = source_counts.get(source_name, 0)
            print(f"  - {source_name}: {source['path']} ({count})")

    skills = result.get("list") or []
    print("skills:")
    if not skills:
        print("  (none)")
    else:
        for item in skills:
            print(f"  - {item['name']} [{item['source']}]")
            print(f"    description: {_truncate(item.get('description') or '', 120)}")

    errors = result.get("errors") or []
    if errors:
        print("errors:")
        for item in errors:
            print(f"  - {item['source']}: {item['description']}")
    return 0


async def agents_command(args: argparse.Namespace) -> int:
    from app.cli.service import cli_db_runtime, list_cli_agents

    async with cli_db_runtime(verbose=args.verbose):
        result = await list_cli_agents(user_id=args.user_id)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"user_id: {result['user_id']}")
    print(f"total: {result['total']}")
    agents = result.get("list") or []
    if not agents:
        print("agents:\n  (none)")
        return 0

    print("agents:")
    for item in agents:
        print(
            f"  - {item.get('agent_id')} | {item.get('name')} | "
            f"mode={item.get('agent_mode')} | default={item.get('is_default')}"
        )
        updated_at = item.get("updated_at")
        if updated_at:
            print(f"    updated_at: {updated_at}")
    return 0


def config_show_command(args: argparse.Namespace) -> int:
    from app.cli.service import collect_config_info

    info = collect_config_info()
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0

    for key, value in info.items():
        if isinstance(value, dict):
            print(f"{key}:")
            for sub_key, sub_value in value.items():
                print(f"  {sub_key}: {sub_value}")
            continue
        print(f"{key}: {value}")
    return 0


def config_init_command(args: argparse.Namespace) -> int:
    from app.cli.service import write_cli_config_file

    result = write_cli_config_file(path=args.path, force=args.force)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(f"config_file: {result['path']}")
    print(f"template: {result['template']}")
    print(f"overwritten: {result['overwritten']}")
    print("next_steps:")
    for item in result["next_steps"]:
        print(f"  - {item}")
    return 0


async def provider_command(args: argparse.Namespace) -> int:
    from app.cli.service import (
        cli_db_runtime,
        create_cli_provider,
        delete_cli_provider,
        inspect_cli_provider,
        query_cli_providers,
        update_cli_provider,
        verify_cli_provider,
    )

    if args.provider_command == "list":
        async with cli_db_runtime(verbose=args.verbose):
            result = await query_cli_providers(
                user_id=args.user_id,
                default_only=args.default_only,
                model=args.model,
                name_contains=args.name_contains,
            )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        print(f"user_id: {result['user_id']}")
        print(f"total: {result['total']}")
        filters = result.get("filters") or {}
        active_filters = [
            f"default_only={filters.get('default_only')}" if filters.get("default_only") else None,
            f"model={filters.get('model')}" if filters.get("model") else None,
            f"name_contains={filters.get('name_contains')}" if filters.get("name_contains") else None,
        ]
        active_filters = [item for item in active_filters if item]
        if active_filters:
            print(f"filters: {', '.join(active_filters)}")
        providers = result.get("list") or []
        if not providers:
            print("providers:\n  (none)")
            return 0
        print("providers:")
        for item in providers:
            print(
                f"  - {item.get('id')} | {item.get('name')} | "
                f"{item.get('model')} | default={item.get('is_default')} | {item.get('base_url')}"
            )
            print(f"    api_key: {item.get('api_key_preview') or '(hidden)'}")
        return 0

    if args.provider_command == "inspect":
        async with cli_db_runtime(verbose=args.verbose):
            result = await inspect_cli_provider(provider_id=args.provider_id, user_id=args.user_id)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        print(f"user_id: {result['user_id']}")
        print(f"provider_id: {result['provider_id']}")
        _print_provider_summary(result.get("provider"))
        return 0

    common_kwargs = {
        "name": getattr(args, "name", None),
        "base_url": getattr(args, "base_url", None),
        "api_key": getattr(args, "api_key", None),
        "model": getattr(args, "model", None),
        "max_tokens": getattr(args, "max_tokens", None),
        "temperature": getattr(args, "temperature", None),
        "top_p": getattr(args, "top_p", None),
        "presence_penalty": getattr(args, "presence_penalty", None),
        "max_model_len": getattr(args, "max_model_len", None),
        "supports_multimodal": getattr(args, "supports_multimodal", None),
        "supports_structured_output": getattr(args, "supports_structured_output", None),
        "is_default": getattr(args, "is_default", None),
    }

    if args.provider_command == "verify":
        result = await verify_cli_provider(**common_kwargs)
    elif args.provider_command == "create":
        async with cli_db_runtime(verbose=args.verbose):
            result = await create_cli_provider(user_id=args.user_id, **common_kwargs)
    elif args.provider_command == "update":
        async with cli_db_runtime(verbose=args.verbose):
            result = await update_cli_provider(
                provider_id=args.provider_id,
                user_id=args.user_id,
                **common_kwargs,
            )
    elif args.provider_command == "delete":
        async with cli_db_runtime(verbose=args.verbose):
            result = await delete_cli_provider(provider_id=args.provider_id, user_id=args.user_id)
    else:
        raise ValueError(f"Unsupported provider command: {args.provider_command}")

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"status: {result.get('status')}")
    print(f"message: {result.get('message')}")
    if result.get("user_id"):
        print(f"user_id: {result.get('user_id')}")
    if result.get("provider_id"):
        print(f"provider_id: {result.get('provider_id')}")
    if result.get("deleted"):
        print("deleted: true")
        return 0
    sources = result.get("sources") or {}
    if sources:
        print("sources:")
        for key, value in sources.items():
            print(f"  {key}: {value}")
    _print_provider_summary(result.get("provider"))
    return 0
