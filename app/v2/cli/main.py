import asyncio
import json
import sys
from app.v2.cli.parser import build_argument_parser
from app.v2.cli.errors import _emit_cli_error, _build_cli_error_payload
from app.v2.cli.commands import (
    v2_run_command as _v2_run_command, v2_chat_command as _v2_chat_command,
    v2_sessions_command as _v2_sessions_command, v2_approvals_command as _v2_approvals_command,
)
from sagents.v2.runtime.session.migration import migrate_manifest_v1, migrate_runtime_root

async def _main_async(args):
    try:
        if args.command == "v2" and args.v2_command == "migrate":
            manifest_output = (
                migrate_manifest_v1(args.manifest, dry_run=True)
                if args.manifest
                else None
            )
            report = await asyncio.to_thread(
                migrate_runtime_root,
                args.runtime_root,
                dry_run=args.dry_run,
            )
            payload = {
                **report.__dict__,
                "source": str(report.source),
                "backup": str(report.backup) if report.backup else None,
            }
            if manifest_output is not None:
                if not args.dry_run:
                    manifest_output = migrate_manifest_v1(args.manifest)
                payload["manifest"] = str(manifest_output)
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "v2" and args.v2_command == "run":
            return await _v2_run_command(args)
        if args.command == "v2" and args.v2_command in {"chat", "resume"}:
            return await _v2_chat_command(args, command_mode=args.v2_command)
        if args.command == "v2" and args.v2_command == "sessions":
            return await _v2_sessions_command(args)
        if args.command == "v2" and args.v2_command == "approvals":
            return await _v2_approvals_command(args)
        raise ValueError(f"Unsupported v2 command: {args.v2_command}")
    except Exception as exc:
        return _emit_cli_error(args, _build_cli_error_payload(exc, verbose=getattr(args, "verbose", False)))

def main(argv=None):
    args = build_argument_parser().parse_args(list(argv) if argv is not None else sys.argv[1:])
    return asyncio.run(_main_async(args))

if __name__ == "__main__":
    raise SystemExit(main())
