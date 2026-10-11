pub(super) fn doctor_args(probe_provider: bool) -> Vec<String> {
    let mut args = vec!["doctor".into(), "--json".into()];
    if probe_provider {
        args.push("--probe-provider".into());
    }
    args
}
