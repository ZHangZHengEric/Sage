pub(super) fn sessions_list_args(user_id: &str, agent_id: Option<&str>, limit: usize) -> Vec<String> {
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
