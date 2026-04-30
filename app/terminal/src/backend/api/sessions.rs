use anyhow::Result;
use serde_json::Value;

use crate::backend::contract::{
    expect_array_field, optional_str_field, optional_u64_field, required_str_field,
    run_cli_command, CliJsonCommand,
};
use crate::backend::{SessionDetail, SessionMessage, SessionSummary};

pub(crate) fn list_sessions(
    user_id: &str,
    agent_id: Option<&str>,
    limit: usize,
) -> Result<Vec<SessionSummary>> {
    let value = run_cli_command(CliJsonCommand::SessionsList {
        user_id,
        agent_id,
        limit,
    })?;
    let items = expect_array_field(&value, "list", "sessions.list")?;
    Ok(items.iter().map(parse_session_summary).collect::<Vec<_>>())
}

pub(crate) fn inspect_latest_session(
    user_id: &str,
    agent_id: Option<&str>,
) -> Result<Option<SessionDetail>> {
    inspect_session_impl("latest", user_id, agent_id)
}

pub(crate) fn inspect_session(
    session_id: &str,
    user_id: &str,
    agent_id: Option<&str>,
) -> Result<Option<SessionDetail>> {
    inspect_session_impl(session_id, user_id, agent_id)
}

fn inspect_session_impl(
    session_id: &str,
    user_id: &str,
    agent_id: Option<&str>,
) -> Result<Option<SessionDetail>> {
    let value = run_cli_command(CliJsonCommand::SessionInspect {
        session_id,
        user_id,
        agent_id,
    })?;

    if value.is_null() {
        return Ok(None);
    }

    Ok(Some(parse_session_detail(&value)))
}

fn parse_session_summary(value: &Value) -> SessionSummary {
    SessionSummary {
        session_id: required_str_field(value, "session_id", "sessions.list")
            .unwrap_or_default()
            .to_string(),
        title: optional_str_field(value, "title").unwrap_or_else(|| "(untitled)".to_string()),
        message_count: optional_u64_field(value, "message_count"),
        updated_at: optional_str_field(value, "updated_at").unwrap_or_default(),
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
        session_id: required_str_field(value, "session_id", "sessions.inspect")
            .unwrap_or_default()
            .to_string(),
        title: optional_str_field(value, "title").unwrap_or_else(|| "(untitled)".to_string()),
        message_count: optional_u64_field(value, "message_count"),
        updated_at: optional_str_field(value, "updated_at").unwrap_or_default(),
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
