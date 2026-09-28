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

/// v2 会话列表（`sage v2 sessions --json`）：条目按 `task` / `run_count` / `last_state` 投影到
/// 现有的选择器字段上，picker 与 /resume 不需要知道运行时差异。
pub(crate) fn list_v2_sessions(limit: usize) -> Result<Vec<SessionSummary>> {
    let value = run_cli_command(CliJsonCommand::V2SessionsList { limit })?;
    let items = expect_array_field(&value, "list", "v2.sessions.list")?;
    Ok(items
        .iter()
        .map(parse_v2_session_summary)
        .collect::<Vec<_>>())
}

pub(crate) fn inspect_latest_v2_session() -> Result<Option<SessionDetail>> {
    let Some(latest) = list_v2_sessions(1)?.into_iter().next() else {
        return Ok(None);
    };
    inspect_v2_session(&latest.session_id)
}

/// v2 会话回放（`sage v2 sessions inspect <id> --json`）：把各 Run 的 transcript 条目摊平成
/// 最近消息；未知会话由 CLI 以非零退出报告，这里作为错误抛出。
pub(crate) fn inspect_v2_session(session_id: &str) -> Result<Option<SessionDetail>> {
    let value = run_cli_command(CliJsonCommand::V2SessionInspect { session_id })?;
    if value.is_null() {
        return Ok(None);
    }
    Ok(Some(parse_v2_session_detail(&value)))
}

const V2_RECENT_MESSAGE_LIMIT: usize = 20;

pub(crate) fn parse_v2_session_summary(value: &Value) -> SessionSummary {
    let task = optional_str_field(value, "task")
        .map(|task| compact_preview(&task))
        .filter(|task| !task.is_empty());
    let last_preview = match (
        optional_str_field(value, "last_state"),
        optional_str_field(value, "workspace"),
    ) {
        (Some(state), Some(workspace)) => Some(format!("{state}  •  {workspace}")),
        (Some(state), None) => Some(state),
        (None, Some(workspace)) => Some(workspace),
        (None, None) => None,
    };
    SessionSummary {
        session_id: required_str_field(value, "session_id", "v2.sessions.list")
            .unwrap_or_default()
            .to_string(),
        title: task.unwrap_or_else(|| "(untitled)".to_string()),
        message_count: optional_u64_field(value, "run_count"),
        updated_at: optional_str_field(value, "updated_at").unwrap_or_default(),
        last_preview,
    }
}

pub(crate) fn parse_v2_session_detail(value: &Value) -> SessionDetail {
    let empty = Value::Null;
    let session = value.get("session").unwrap_or(&empty);
    let summary = parse_v2_session_summary(session);
    let messages = value
        .get("runs")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|run| run.get("entries").and_then(Value::as_array))
        .flatten()
        .filter_map(|entry| {
            let role = entry.get("kind").and_then(Value::as_str)?.to_string();
            let content = entry
                .get("text")
                .and_then(Value::as_str)?
                .trim()
                .to_string();
            (!content.is_empty()).then_some(SessionMessage { role, content })
        })
        .collect::<Vec<_>>();
    let message_count = messages.len() as u64;
    let skip = messages.len().saturating_sub(V2_RECENT_MESSAGE_LIMIT);
    SessionDetail {
        session_id: summary.session_id,
        title: summary.title,
        message_count,
        updated_at: summary.updated_at,
        recent_messages: messages.into_iter().skip(skip).collect(),
    }
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

#[cfg(test)]
mod v2_tests {
    use serde_json::json;

    use super::{parse_v2_session_detail, parse_v2_session_summary};

    #[test]
    fn v2_session_summary_projects_task_runs_and_state() {
        let summary = parse_v2_session_summary(&json!({
            "session_id": "session_a",
            "created_at": "2026-09-04T01:00:00+00:00",
            "updated_at": "2026-09-04T02:00:00+00:00",
            "run_count": 3,
            "last_run_id": "run_3",
            "last_state": "completed",
            "agent_id": "coder",
            "task": "  create   hello.txt\nplease ",
            "workspace": "/tmp/ws",
            "package_id": "sage.presets.coder"
        }));

        assert_eq!(summary.session_id, "session_a");
        assert_eq!(summary.title, "create hello.txt please");
        assert_eq!(summary.message_count, 3);
        assert_eq!(summary.updated_at, "2026-09-04T02:00:00+00:00");
        assert_eq!(
            summary.last_preview.as_deref(),
            Some("completed  •  /tmp/ws")
        );

        let bare = parse_v2_session_summary(&json!({"session_id": "session_b", "task": ""}));
        assert_eq!(bare.title, "(untitled)");
        assert_eq!(bare.message_count, 0);
        assert!(bare.last_preview.is_none());
    }

    #[test]
    fn v2_session_detail_flattens_run_transcripts_into_recent_messages() {
        let detail = parse_v2_session_detail(&json!({
            "session": {"session_id": "session_a", "task": "create hello.txt", "run_count": 2,
                         "updated_at": "2026-09-04T02:00:00+00:00", "last_state": "completed"},
            "runs": [
                {"run_id": "run_1", "state": "completed", "entries": [
                    {"kind": "user", "text": "create hello.txt"},
                    {"kind": "tool", "text": "file_write hello.txt", "detail": "succeeded"},
                    {"kind": "assistant", "text": "Done."}
                ]},
                {"run_id": "run_2", "state": "completed", "entries": [
                    {"kind": "user", "text": "thanks"},
                    {"kind": "interaction", "text": "   "},
                    {"kind": "assistant", "text": "You're welcome."}
                ]}
            ]
        }));

        assert_eq!(detail.session_id, "session_a");
        assert_eq!(detail.title, "create hello.txt");
        assert_eq!(detail.message_count, 5);
        let roles = detail
            .recent_messages
            .iter()
            .map(|message| (message.role.as_str(), message.content.as_str()))
            .collect::<Vec<_>>();
        assert_eq!(
            roles,
            vec![
                ("user", "create hello.txt"),
                ("tool", "file_write hello.txt"),
                ("assistant", "Done."),
                ("user", "thanks"),
                ("assistant", "You're welcome."),
            ]
        );
    }

    #[test]
    fn v2_session_detail_keeps_only_the_most_recent_messages() {
        let entries = (0..30)
            .map(|index| json!({"kind": "user", "text": format!("message {index}")}))
            .collect::<Vec<_>>();
        let detail = parse_v2_session_detail(&json!({
            "session": {"session_id": "session_a"},
            "runs": [{"run_id": "run_1", "state": "completed", "entries": entries}]
        }));

        assert_eq!(detail.message_count, 30);
        assert_eq!(detail.recent_messages.len(), 20);
        assert_eq!(detail.recent_messages[0].content, "message 10");
        assert_eq!(detail.recent_messages[19].content, "message 29");
    }
}
