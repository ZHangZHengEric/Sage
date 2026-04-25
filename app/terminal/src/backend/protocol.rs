use std::sync::mpsc;

use serde_json::Value;

use crate::app::MessageKind;

use super::BackendEvent;

pub(super) fn flush_complete_lines(
    pending: &mut Vec<u8>,
    sender: &mpsc::Sender<BackendEvent>,
) -> Result<(), mpsc::SendError<BackendEvent>> {
    while let Some(index) = pending.iter().position(|byte| *byte == b'\n') {
        let line = pending.drain(..=index).collect::<Vec<_>>();
        let line = String::from_utf8_lossy(&line);
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        for event in parse_backend_line(line) {
            sender.send(event)?;
        }
    }
    Ok(())
}

pub(crate) fn parse_backend_line(line: &str) -> Vec<BackendEvent> {
    let mut events = Vec::new();
    let value = match serde_json::from_str::<Value>(line) {
        Ok(value) => value,
        Err(_) => return events,
    };

    let event_type = value
        .get("type")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let role = value
        .get("role")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let content = value
        .get("content")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let tool_names = collect_tool_names(&value);

    if event_type == "cli_stats" {
        events.push(BackendEvent::Finished);
    } else if let Some(kind) = live_message_kind(event_type, role, &content) {
        events.push(BackendEvent::LiveChunk(kind, content));
    } else if matches!(event_type, "tool_call" | "tool_result") && !tool_names.is_empty() {
        for name in &tool_names {
            events.push(if event_type == "tool_call" {
                BackendEvent::ToolStarted(name.clone())
            } else {
                BackendEvent::ToolFinished(name.clone())
            });
        }
    } else if !content.is_empty() {
        match event_type {
            "tool_call" => events.push(BackendEvent::Message(
                MessageKind::Tool,
                format!("running {}", summarize_tool_event(&tool_names, &content)),
            )),
            "tool_result" => events.push(BackendEvent::Message(
                MessageKind::Tool,
                format!("completed {}", summarize_tool_event(&tool_names, &content)),
            )),
            "error" | "cli_error" => events.push(BackendEvent::Error(content)),
            "cli_stats" | "token_usage" | "start" | "done" => {}
            _ => events.push(BackendEvent::Message(
                MessageKind::Process,
                truncate(&clean_single_line(&content), 180),
            )),
        }
    }

    for name in tool_names {
        events.push(BackendEvent::Status(format!("tool  {}", name)));
    }

    if event_type == "stream_end" {
        events.push(BackendEvent::Finished);
    }

    events
}

fn live_message_kind(event_type: &str, role: &str, content: &str) -> Option<MessageKind> {
    if content.is_empty() {
        return None;
    }

    if matches!(
        event_type,
        "error"
            | "cli_error"
            | "tool_call"
            | "tool_result"
            | "cli_stats"
            | "token_usage"
            | "start"
            | "done"
            | "stream_end"
    ) {
        return None;
    }

    if matches!(
        event_type,
        "thinking" | "reasoning_content" | "task_analysis" | "analysis" | "plan" | "observation"
    ) {
        return Some(MessageKind::Process);
    }

    if matches!(
        event_type,
        "text" | "assistant" | "message" | "do_subtask_result"
    ) || matches!(role, "assistant" | "agent")
    {
        return Some(MessageKind::Assistant);
    }

    None
}

fn summarize_tool_event(names: &[String], content: &str) -> String {
    if !names.is_empty() {
        return names.join(", ");
    }

    truncate(&clean_single_line(content), 140)
}

fn clean_single_line(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn collect_tool_names(value: &Value) -> Vec<String> {
    let mut names = Vec::new();
    if let Some(tool_calls) = value.get("tool_calls").and_then(Value::as_array) {
        for tool_call in tool_calls {
            if let Some(name) = tool_call
                .get("function")
                .and_then(Value::as_object)
                .and_then(|function| function.get("name"))
                .and_then(Value::as_str)
            {
                names.push(name.to_string());
            }
        }
    }

    if let Some(metadata_name) = value
        .get("metadata")
        .and_then(Value::as_object)
        .and_then(|metadata| metadata.get("tool_name"))
        .and_then(Value::as_str)
    {
        names.push(metadata_name.to_string());
    }

    if let Some(event_name) = value.get("tool_name").and_then(Value::as_str) {
        names.push(event_name.to_string());
    }

    names.sort();
    names.dedup();
    names
}

fn truncate(text: &str, max_len: usize) -> String {
    if text.chars().count() <= max_len {
        return text.to_string();
    }
    text.chars()
        .take(max_len.saturating_sub(3))
        .collect::<String>()
        + "..."
}
