"""Read-only replay of Run/Session metadata without execution payload objects."""


def project_metadata_state(state):
    sessions = [
        {
            key: row.get(key)
            for key in (
                "session_id",
                "owner",
                "created_at",
                "parent_session_id",
                "revision",
                "last_sequence",
            )
        }
        for row in state.get("sessions", ())
    ]
    runs = []
    for row in state.get("runs", ()):
        command = row.get("start_command") or {}
        config = command.get("config", {}).get("metadata", {})
        metadata = {
            key: config[key]
            for key in ("task_name", "server_v2.execution")
            if key in config
        }
        composition = config.get("server_v2.composition")
        if isinstance(composition, dict) and isinstance(composition.get("agent"), dict):
            metadata["server_v2.composition"] = {
                "agent": {"id": composition["agent"].get("id")}
            }
        runs.append(
            {key: row[key] for key in ("session_id", "run_id", "created_at", "state")}
            | {
                "request_context": {
                    "actor": (row.get("request_context") or {}).get("actor")
                },
                "start_command": {
                    key: command.get(key)
                    for key in ("agent_id", "invocation_mode", "parent_run_id")
                }
                | {"config": {"metadata": metadata}},
            }
        )
    # Retain only accepted actors for legacy owner derivation. Context actors
    # must keep precedence over this fallback, including after later patches.
    accepted = {
        rid: [
            {
                key: event.get(key)
                for key in ("type", "session_id", "session_sequence", "actor")
            }
            for event in values
            if event.get("type") == "run.accepted"
        ]
        for rid, values in state.get("run_events", {}).items()
    }
    return {"sessions": sessions, "runs": runs, "run_events": accepted}


def apply_metadata_delta(state, delta):
    for collection, key in (("sessions", "session_id"), ("runs", "run_id")):
        current = {row[key]: row for row in state[collection]}
        for row in delta.get("upserts", {}).get(collection, ()):
            value = project_metadata_state({collection: [row]})[collection][0]
            current[row[key]] = value
        for patch in delta.get("patches", {}).get(collection, ()):
            if patch[key] not in current:
                raise ValueError("metadata patch refers to a missing row")
            for field in ("state",) if collection == "runs" else tuple(patch):
                if field in patch:
                    current[patch[key]][field] = patch[field]
        for deleted in delta.get("deletes", {}).get(collection, ()):
            current.pop(deleted[0], None)
        state[collection] = list(current.values())
    for operation in ("replacements", "appends"):
        for rid, values in delta.get(operation, {}).get("run_events", {}).items():
            accepted = [
                {
                    key: event.get(key)
                    for key in ("type", "session_id", "session_sequence", "actor")
                }
                for event in values
                if event.get("type") == "run.accepted"
            ]
            if operation == "replacements":
                state["run_events"][rid] = accepted
            else:
                state["run_events"].setdefault(rid, []).extend(accepted)
    for rid in delta.get("map_deletes", {}).get("run_events", ()):
        state["run_events"].pop(rid, None)
    return state
