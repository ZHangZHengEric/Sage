use std::path::Path;

use anyhow::{anyhow, Result};
use serde_json::Value;

use super::{ConfigInfo, ProviderInfo, ProviderMutation, SessionDetail, SessionMessage, SessionSummary, SkillInfo};
use crate::backend_support::{run_cli_json, run_cli_json_owned};

pub(crate) fn list_sessions(user_id: &str, limit: usize) -> Result<Vec<SessionSummary>> {
    let limit = limit.max(1).to_string();
    let value = run_cli_json(&[
        "sessions",
        "--json",
        "--user-id",
        user_id,
        "--limit",
        &limit,
    ])?;

    let items = value
        .get("list")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();

    Ok(items.iter().map(parse_session_summary).collect::<Vec<_>>())
}

pub(crate) fn inspect_latest_session(user_id: &str) -> Result<Option<SessionDetail>> {
    inspect_session_impl("latest", user_id)
}

pub(crate) fn inspect_session(session_id: &str, user_id: &str) -> Result<Option<SessionDetail>> {
    inspect_session_impl(session_id, user_id)
}

pub(crate) fn list_skills(user_id: &str, workspace: Option<&Path>) -> Result<Vec<SkillInfo>> {
    let mut args = vec!["skills", "--json", "--user-id", user_id];
    let workspace_owned;
    if let Some(path) = workspace {
        workspace_owned = path.display().to_string();
        args.push("--workspace");
        args.push(&workspace_owned);
    }

    let value = run_cli_json(&args)?;
    let items = value
        .get("list")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();

    Ok(items
        .into_iter()
        .map(|item| SkillInfo {
            name: item
                .get("name")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            description: item
                .get("description")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            source: item
                .get("source")
                .and_then(Value::as_str)
                .unwrap_or("unknown")
                .to_string(),
        })
        .collect())
}

pub(crate) fn read_config() -> Result<ConfigInfo> {
    let value = run_cli_json(&["config", "show", "--json"])?;
    Ok(ConfigInfo {
        default_model_name: value
            .get("default_llm_model_name")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        default_api_base_url: value
            .get("default_llm_api_base_url")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        default_user_id: value
            .get("default_cli_user_id")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        env_file: value
            .get("env_file")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
    })
}

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

fn inspect_session_impl(session_id: &str, user_id: &str) -> Result<Option<SessionDetail>> {
    let value = run_cli_json(&[
        "sessions",
        "inspect",
        session_id,
        "--json",
        "--user-id",
        user_id,
    ])?;

    if value.is_null() {
        return Ok(None);
    }

    Ok(Some(parse_session_detail(&value)))
}

fn parse_session_summary(value: &Value) -> SessionSummary {
    SessionSummary {
        session_id: value
            .get("session_id")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        title: value
            .get("title")
            .and_then(Value::as_str)
            .unwrap_or("(untitled)")
            .to_string(),
        message_count: value
            .get("message_count")
            .and_then(Value::as_u64)
            .unwrap_or(0),
        updated_at: value
            .get("updated_at")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        last_preview: value
            .get("last_message")
            .and_then(Value::as_object)
            .and_then(|last| last.get("content"))
            .and_then(Value::as_str)
            .map(compact_preview),
    }
}

fn parse_session_detail(value: &Value) -> SessionDetail {
    let recent_messages = value
        .get("recent_messages")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .filter_map(|item| {
            let role = item.get("role").and_then(Value::as_str)?.to_string();
            let content = item.get("content").and_then(Value::as_str)?.to_string();
            Some(SessionMessage { role, content })
        })
        .collect::<Vec<_>>();

    SessionDetail {
        session_id: value
            .get("session_id")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        title: value
            .get("title")
            .and_then(Value::as_str)
            .unwrap_or("(untitled)")
            .to_string(),
        message_count: value
            .get("message_count")
            .and_then(Value::as_u64)
            .unwrap_or(0),
        updated_at: value
            .get("updated_at")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        recent_messages,
    }
}

fn compact_preview(text: &str) -> String {
    text.split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .chars()
        .take(120)
        .collect::<String>()
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
