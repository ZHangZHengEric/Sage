use anyhow::{anyhow, Result};
use serde_json::Value;
use std::path::Path;

use crate::backend::ProviderMutation;
use crate::backend_support::run_cli_json_owned;

pub(crate) enum CliJsonCommand<'a> {
    ConfigShow,
    ConfigInit {
        path: Option<&'a str>,
        force: bool,
    },
    Doctor {
        probe_provider: bool,
    },
    SessionsList {
        user_id: &'a str,
        limit: usize,
    },
    SessionInspect {
        session_id: &'a str,
        user_id: &'a str,
    },
    SkillsList {
        user_id: &'a str,
        workspace: Option<&'a Path>,
    },
    ProvidersList {
        user_id: &'a str,
    },
    ProviderInspect {
        user_id: &'a str,
        provider_id: &'a str,
    },
    ProviderVerify {
        mutation: &'a ProviderMutation,
    },
    ProviderSetDefault {
        user_id: &'a str,
        provider_id: &'a str,
    },
    ProviderCreate {
        user_id: &'a str,
        mutation: &'a ProviderMutation,
    },
    ProviderUpdate {
        user_id: &'a str,
        provider_id: &'a str,
        mutation: &'a ProviderMutation,
    },
    ProviderDelete {
        user_id: &'a str,
        provider_id: &'a str,
    },
}

impl CliJsonCommand<'_> {
    fn label(&self) -> &'static str {
        match self {
            Self::ConfigShow => "config.show",
            Self::ConfigInit { .. } => "config.init",
            Self::Doctor { .. } => "doctor",
            Self::SessionsList { .. } => "sessions.list",
            Self::SessionInspect { .. } => "sessions.inspect",
            Self::SkillsList { .. } => "skills.list",
            Self::ProvidersList { .. } => "provider.list",
            Self::ProviderInspect { .. } => "provider.inspect",
            Self::ProviderVerify { .. } => "provider.verify",
            Self::ProviderSetDefault { .. } => "provider.set_default",
            Self::ProviderCreate { .. } => "provider.create",
            Self::ProviderUpdate { .. } => "provider.update",
            Self::ProviderDelete { .. } => "provider.delete",
        }
    }

    pub(crate) fn args(&self) -> Vec<String> {
        match self {
            Self::ConfigShow => vec!["config".into(), "show".into(), "--json".into()],
            Self::ConfigInit { path, force } => {
                let mut args = vec!["config".into(), "init".into(), "--json".into()];
                if let Some(path) = path {
                    args.push("--path".into());
                    args.push((*path).into());
                }
                if *force {
                    args.push("--force".into());
                }
                args
            }
            Self::Doctor { probe_provider } => {
                let mut args = vec!["doctor".into(), "--json".into()];
                if *probe_provider {
                    args.push("--probe-provider".into());
                }
                args
            }
            Self::SessionsList { user_id, limit } => vec![
                "sessions".into(),
                "--json".into(),
                "--user-id".into(),
                (*user_id).into(),
                "--limit".into(),
                (*limit).max(1).to_string(),
            ],
            Self::SessionInspect {
                session_id,
                user_id,
            } => vec![
                "sessions".into(),
                "inspect".into(),
                (*session_id).into(),
                "--json".into(),
                "--user-id".into(),
                (*user_id).into(),
            ],
            Self::SkillsList { user_id, workspace } => {
                let mut args = vec![
                    "skills".into(),
                    "--json".into(),
                    "--user-id".into(),
                    (*user_id).into(),
                ];
                if let Some(path) = workspace {
                    args.push("--workspace".into());
                    args.push(path.display().to_string());
                }
                args
            }
            Self::ProvidersList { user_id } => vec![
                "provider".into(),
                "list".into(),
                "--json".into(),
                "--user-id".into(),
                (*user_id).into(),
            ],
            Self::ProviderInspect {
                user_id,
                provider_id,
            } => vec![
                "provider".into(),
                "inspect".into(),
                (*provider_id).into(),
                "--json".into(),
                "--user-id".into(),
                (*user_id).into(),
            ],
            Self::ProviderVerify { mutation } => {
                build_provider_mutation_args("verify", "", None, mutation)
            }
            Self::ProviderSetDefault {
                user_id,
                provider_id,
            } => vec![
                "provider".into(),
                "update".into(),
                (*provider_id).into(),
                "--json".into(),
                "--user-id".into(),
                (*user_id).into(),
                "--set-default".into(),
            ],
            Self::ProviderCreate { user_id, mutation } => {
                build_provider_mutation_args("create", user_id, None, mutation)
            }
            Self::ProviderUpdate {
                user_id,
                provider_id,
                mutation,
            } => build_provider_mutation_args("update", user_id, Some(provider_id), mutation),
            Self::ProviderDelete {
                user_id,
                provider_id,
            } => vec![
                "provider".into(),
                "delete".into(),
                (*provider_id).into(),
                "--json".into(),
                "--user-id".into(),
                (*user_id).into(),
            ],
        }
    }
}

pub(crate) fn run_cli_command(command: CliJsonCommand<'_>) -> Result<Value> {
    let label = command.label();
    let args = command.args();
    run_cli_json_owned(&args).map_err(|err| anyhow!("{} failed: {err}", label))
}

pub(crate) fn expect_array_field<'a>(
    value: &'a Value,
    key: &str,
    context: &str,
) -> Result<&'a [Value]> {
    value
        .get(key)
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .ok_or_else(|| anyhow!("{context} contract error: expected `{key}` array"))
}

pub(crate) fn expect_object_field<'a>(
    value: &'a Value,
    key: &str,
    context: &str,
) -> Result<&'a Value> {
    value
        .get(key)
        .and_then(Value::as_object)
        .map(|_| value.get(key).expect("field exists"))
        .ok_or_else(|| anyhow!("{context} contract error: expected `{key}` object"))
}

pub(crate) fn required_str_field<'a>(
    value: &'a Value,
    key: &str,
    context: &str,
) -> Result<&'a str> {
    value
        .get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| anyhow!("{context} contract error: expected `{key}` string"))
}

pub(crate) fn optional_str_field(value: &Value, key: &str) -> Option<String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .map(ToString::to_string)
}

pub(crate) fn optional_u64_field(value: &Value, key: &str) -> u64 {
    value.get(key).and_then(Value::as_u64).unwrap_or(0)
}

pub(crate) fn optional_bool_field(value: &Value, key: &str) -> bool {
    value.get(key).and_then(Value::as_bool).unwrap_or(false)
}

pub(crate) struct CliStreamEvent {
    pub(crate) event_type: String,
    pub(crate) role: String,
    pub(crate) content: String,
    pub(crate) tool_calls: Vec<CliToolCall>,
    pub(crate) metadata: Option<CliEventMetadata>,
    pub(crate) tool_name: Option<String>,
}

pub(crate) struct CliToolCall {
    pub(crate) function: CliToolFunction,
}

#[derive(Debug, Default)]
pub(crate) struct CliToolFunction {
    pub(crate) name: String,
}

#[derive(Debug)]
pub(crate) struct CliEventMetadata {
    pub(crate) tool_name: Option<String>,
}

pub(crate) fn parse_stream_event(line: &str) -> Option<CliStreamEvent> {
    let value = serde_json::from_str::<Value>(line).ok()?;
    let object = value.as_object()?;
    let tool_calls = object
        .get("tool_calls")
        .and_then(Value::as_array)
        .map(|calls| {
            calls
                .iter()
                .map(|call| CliToolCall {
                    function: CliToolFunction {
                        name: call
                            .get("function")
                            .and_then(Value::as_object)
                            .and_then(|function| function.get("name"))
                            .and_then(Value::as_str)
                            .unwrap_or_default()
                            .to_string(),
                    },
                })
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let metadata = object
        .get("metadata")
        .and_then(Value::as_object)
        .map(|metadata| CliEventMetadata {
            tool_name: metadata
                .get("tool_name")
                .and_then(Value::as_str)
                .map(ToString::to_string),
        });

    Some(CliStreamEvent {
        event_type: object
            .get("type")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        role: object
            .get("role")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        content: object
            .get("content")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        tool_calls,
        metadata,
        tool_name: object
            .get("tool_name")
            .and_then(Value::as_str)
            .map(ToString::to_string),
    })
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
