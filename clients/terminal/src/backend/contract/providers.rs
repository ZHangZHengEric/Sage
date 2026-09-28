use crate::backend::ProviderMutation;

pub(super) fn providers_list_args(user_id: &str) -> Vec<String> {
    vec![
        "provider".into(),
        "list".into(),
        "--json".into(),
        "--user-id".into(),
        user_id.into(),
    ]
}

pub(super) fn provider_inspect_args(user_id: &str, provider_id: &str) -> Vec<String> {
    vec![
        "provider".into(),
        "inspect".into(),
        provider_id.into(),
        "--json".into(),
        "--user-id".into(),
        user_id.into(),
    ]
}

pub(super) fn provider_set_default_args(user_id: &str, provider_id: &str) -> Vec<String> {
    vec![
        "provider".into(),
        "update".into(),
        provider_id.into(),
        "--json".into(),
        "--user-id".into(),
        user_id.into(),
        "--set-default".into(),
    ]
}

pub(super) fn provider_delete_args(user_id: &str, provider_id: &str) -> Vec<String> {
    vec![
        "provider".into(),
        "delete".into(),
        provider_id.into(),
        "--json".into(),
        "--user-id".into(),
        user_id.into(),
    ]
}

pub(super) fn provider_verify_args(mutation: &ProviderMutation) -> Vec<String> {
    build_provider_mutation_args("verify", "", None, mutation)
}

pub(super) fn provider_create_args(user_id: &str, mutation: &ProviderMutation) -> Vec<String> {
    build_provider_mutation_args("create", user_id, None, mutation)
}

pub(super) fn provider_update_args(
    user_id: &str,
    provider_id: &str,
    mutation: &ProviderMutation,
) -> Vec<String> {
    build_provider_mutation_args("update", user_id, Some(provider_id), mutation)
}

fn build_provider_mutation_args(
    command: &str,
    user_id: &str,
    provider_id: Option<&str>,
    mutation: &ProviderMutation,
) -> Vec<String> {
    let mut args = vec!["provider".to_string(), command.to_string()];
    if let Some(provider_id) = provider_id {
        args.push(provider_id.to_string());
    }
    args.push("--json".to_string());
    if !user_id.is_empty() {
        args.push("--user-id".to_string());
        args.push(user_id.to_string());
    }

    if let Some(name) = &mutation.name {
        args.push("--name".to_string());
        args.push(name.clone());
    }
    if let Some(base_url) = &mutation.base_url {
        args.push("--base-url".to_string());
        args.push(base_url.clone());
    }
    if let Some(api_key) = &mutation.api_key {
        args.push("--api-key".to_string());
        args.push(api_key.clone());
    }
    if let Some(model) = &mutation.model {
        args.push("--model".to_string());
        args.push(model.clone());
    }
    if let Some(is_default) = mutation.is_default {
        args.push(if is_default {
            "--set-default".to_string()
        } else {
            "--unset-default".to_string()
        });
    }

    args
}
