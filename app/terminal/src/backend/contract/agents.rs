pub(super) fn agents_list_args(user_id: &str) -> Vec<String> {
    vec![
        "agents".into(),
        "--json".into(),
        "--user-id".into(),
        user_id.into(),
    ]
}
