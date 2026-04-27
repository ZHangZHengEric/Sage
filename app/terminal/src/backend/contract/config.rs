pub(super) fn config_show_args() -> Vec<String> {
    vec!["config".into(), "show".into(), "--json".into()]
}

pub(super) fn config_init_args(path: Option<&str>, force: bool) -> Vec<String> {
    let mut args = vec!["config".into(), "init".into(), "--json".into()];
    if let Some(path) = path {
        args.push("--path".into());
        args.push(path.into());
    }
    if force {
        args.push("--force".into());
    }
    args
}
