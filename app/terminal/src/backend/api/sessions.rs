use anyhow::Result;
use serde_json::Value;

use crate::backend::{SessionDetail, SessionMessage, SessionSummary};
use crate::backend_support::run_cli_json;

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
