use std::path::Path;

pub(super) fn skills_list_args(user_id: &str, workspace: Option<&Path>) -> Vec<String> {
    let mut args = vec![
        "skills".into(),
        "--json".into(),
        "--user-id".into(),
        user_id.into(),
    ];
    if let Some(path) = workspace {
        args.push("--workspace".into());
        args.push(path.display().to_string());
    }
    args
}
