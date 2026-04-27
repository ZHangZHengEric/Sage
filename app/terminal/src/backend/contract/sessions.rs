pub(super) fn sessions_list_args(user_id: &str, limit: usize) -> Vec<String> {
    vec![
        "sessions".into(),
        "--json".into(),
        "--user-id".into(),
        user_id.into(),
        "--limit".into(),
        limit.max(1).to_string(),
    ]
}

pub(super) fn session_inspect_args(session_id: &str, user_id: &str) -> Vec<String> {
    vec![
        "sessions".into(),
        "inspect".into(),
        session_id.into(),
        "--json".into(),
        "--user-id".into(),
        user_id.into(),
    ]
}
