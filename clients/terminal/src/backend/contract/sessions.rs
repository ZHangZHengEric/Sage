pub(super) fn sessions_list_args(
    user_id: &str,
    agent_id: Option<&str>,
    limit: usize,
) -> Vec<String> {
    let mut args = vec![
        "sessions".into(),
        "--json".into(),
        "--user-id".into(),
        user_id.into(),
        "--limit".into(),
        limit.max(1).to_string(),
    ];
    if let Some(agent_id) = agent_id {
        args.push("--agent-id".into());
        args.push(agent_id.into());
    }
    args
}

/// v2 会话列表：`sage v2 sessions --json`（会话存储按 session_root 划分，与用户无关）。
pub(super) fn v2_sessions_list_args(limit: usize) -> Vec<String> {
    vec![
        "v2".into(),
        "sessions".into(),
        "--json".into(),
        "--limit".into(),
        limit.max(1).to_string(),
    ]
}

pub(super) fn v2_session_inspect_args(session_id: &str) -> Vec<String> {
    vec![
        "v2".into(),
        "sessions".into(),
        "inspect".into(),
        session_id.into(),
        "--json".into(),
    ]
}

pub(super) fn session_inspect_args(
    session_id: &str,
    user_id: &str,
    agent_id: Option<&str>,
) -> Vec<String> {
    let mut args = vec![
        "sessions".into(),
        "inspect".into(),
        session_id.into(),
        "--json".into(),
        "--user-id".into(),
        user_id.into(),
    ];
    if let Some(agent_id) = agent_id {
        args.push("--agent-id".into());
        args.push(agent_id.into());
    }
    args
}
