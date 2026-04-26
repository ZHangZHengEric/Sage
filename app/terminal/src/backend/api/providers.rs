use anyhow::{anyhow, Result};
use serde_json::Value;

use crate::backend::{ProviderInfo, ProviderMutation};
use crate::backend_support::{run_cli_json, run_cli_json_owned};

pub(crate) fn list_providers(user_id: &str) -> Result<Vec<ProviderInfo>> {
    let value = run_cli_json(&["provider", "list", "--json", "--user-id", user_id])?;
    let items = value
        .get("list")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();

    Ok(items.into_iter().map(|item| parse_provider(&item)).collect())
}

pub(crate) fn inspect_provider(user_id: &str, provider_id: &str) -> Result<ProviderInfo> {
    let value = run_cli_json(&[
        "provider",
        "inspect",
        provider_id,
        "--json",
        "--user-id",
        user_id,
    ])?;
    let provider = value
        .get("provider")
        .ok_or_else(|| anyhow!("provider payload missing"))?;
    Ok(parse_provider(provider))
}

pub(crate) fn set_default_provider(user_id: &str, provider_id: &str) -> Result<ProviderInfo> {
    let value = run_cli_json(&[
        "provider",
        "update",
        provider_id,
        "--json",
        "--user-id",
        user_id,
        "--set-default",
    ])?;
    let provider = value
        .get("provider")
        .ok_or_else(|| anyhow!("provider payload missing"))?;
    Ok(parse_provider(provider))
}

pub(crate) fn create_provider(user_id: &str, mutation: &ProviderMutation) -> Result<ProviderInfo> {
    let args = build_provider_mutation_args("create", Some(user_id), None, mutation);
    let value = run_cli_json_owned(&args)?;
    let provider = value
        .get("provider")
        .ok_or_else(|| anyhow!("provider payload missing"))?;
    Ok(parse_provider(provider))
}

pub(crate) fn update_provider(
    user_id: &str,
    provider_id: &str,
    mutation: &ProviderMutation,
) -> Result<ProviderInfo> {
    let args = build_provider_mutation_args("update", Some(user_id), Some(provider_id), mutation);
    let value = run_cli_json_owned(&args)?;
    let provider = value
        .get("provider")
        .ok_or_else(|| anyhow!("provider payload missing"))?;
    Ok(parse_provider(provider))
}

pub(crate) fn delete_provider(user_id: &str, provider_id: &str) -> Result<()> {
    let value = run_cli_json(&[
        "provider",
        "delete",
        provider_id,
        "--json",
        "--user-id",
        user_id,
    ])?;
    let deleted = value
        .get("deleted")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    if deleted {
        Ok(())
    } else {
        Err(anyhow!("provider delete did not report success"))
    }
}

fn parse_provider(value: &Value) -> ProviderInfo {
    ProviderInfo {
        id: value
            .get("id")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        name: value
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        model: value
            .get("model")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        base_url: value
            .get("base_url")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        is_default: value
            .get("is_default")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        api_key_preview: value
            .get("api_key_preview")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
    }
}

fn build_provider_mutation_args(
    command: &str,
    user_id: Option<&str>,
    provider_id: Option<&str>,
    mutation: &ProviderMutation,
) -> Vec<String> {
    let mut args = vec!["provider".to_string(), command.to_string()];
    if let Some(provider_id) = provider_id {
        args.push(provider_id.to_string());
    }
    if let Some(user_id) = user_id {
        args.push("--user-id".to_string());
        args.push(user_id.to_string());
    }
    args.push("--json".to_string());

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
