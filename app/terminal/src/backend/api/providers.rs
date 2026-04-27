use anyhow::{anyhow, Result};
use serde_json::Value;

use crate::backend::contract::{
    expect_array_field, expect_object_field, optional_bool_field, optional_str_field,
    run_cli_command, CliJsonCommand,
};
use crate::backend::{ProviderInfo, ProviderMutation, ProviderVerifyInfo};

pub(crate) fn list_providers(user_id: &str) -> Result<Vec<ProviderInfo>> {
    let value = run_cli_command(CliJsonCommand::ProvidersList { user_id })?;
    let items = expect_array_field(&value, "list", "provider.list")?;

    Ok(items.iter().map(parse_provider).collect())
}

pub(crate) fn inspect_provider(user_id: &str, provider_id: &str) -> Result<ProviderInfo> {
    let value = run_cli_command(CliJsonCommand::ProviderInspect {
        user_id,
        provider_id,
    })?;
    let provider = expect_object_field(&value, "provider", "provider.inspect")?;
    Ok(parse_provider(provider))
}

pub(crate) fn verify_provider(mutation: &ProviderMutation) -> Result<ProviderVerifyInfo> {
    let value = run_cli_command(CliJsonCommand::ProviderVerify { mutation })?;
    let provider = expect_object_field(&value, "provider", "provider.verify")?;
    let sources = value
        .get("sources")
        .and_then(Value::as_object)
        .map(|map| {
            map.iter()
                .filter_map(|(key, value)| {
                    value.as_str().map(|value| (key.clone(), value.to_string()))
                })
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();

    Ok(ProviderVerifyInfo {
        status: optional_str_field(&value, "status").unwrap_or_default(),
        message: optional_str_field(&value, "message").unwrap_or_default(),
        provider: parse_provider(provider),
        sources,
    })
}

pub(crate) fn set_default_provider(user_id: &str, provider_id: &str) -> Result<ProviderInfo> {
    let value = run_cli_command(CliJsonCommand::ProviderSetDefault {
        user_id,
        provider_id,
    })?;
    let provider = expect_object_field(&value, "provider", "provider.set_default")?;
    Ok(parse_provider(provider))
}

pub(crate) fn create_provider(user_id: &str, mutation: &ProviderMutation) -> Result<ProviderInfo> {
    let value = run_cli_command(CliJsonCommand::ProviderCreate { user_id, mutation })?;
    let provider = expect_object_field(&value, "provider", "provider.create")?;
    Ok(parse_provider(provider))
}

pub(crate) fn update_provider(
    user_id: &str,
    provider_id: &str,
    mutation: &ProviderMutation,
) -> Result<ProviderInfo> {
    let value = run_cli_command(CliJsonCommand::ProviderUpdate {
        user_id,
        provider_id,
        mutation,
    })?;
    let provider = expect_object_field(&value, "provider", "provider.update")?;
    Ok(parse_provider(provider))
}

pub(crate) fn delete_provider(user_id: &str, provider_id: &str) -> Result<()> {
    let value = run_cli_command(CliJsonCommand::ProviderDelete {
        user_id,
        provider_id,
    })?;
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
        id: optional_str_field(value, "id").unwrap_or_default(),
        name: optional_str_field(value, "name").unwrap_or_default(),
        model: optional_str_field(value, "model").unwrap_or_default(),
        base_url: optional_str_field(value, "base_url").unwrap_or_default(),
        is_default: optional_bool_field(value, "is_default"),
        api_key_preview: optional_str_field(value, "api_key_preview").unwrap_or_default(),
    }
}
