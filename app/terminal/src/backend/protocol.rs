use std::sync::mpsc;

use crate::app::MessageKind;
use crate::backend::contract::parse_stream_event;
use crate::backend::protocol_support::{
    backend_stats_from_event, collect_tool_names, live_message_kind, summarize_tool_event, truncate,
};
use crate::display_policy::{is_visible_tool, DisplayMode};

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
    let event = match parse_stream_event(line) {
        Some(event) => event,
        None => return events,
    };

    let event_type = event.event_type.as_str();
    let role = event.role.as_str();
    let tool_names = collect_tool_names(&event);
    let content = event.content.clone();

    if event_type == "cli_stats" {
        events.push(BackendEvent::Stats(backend_stats_from_event(event)));
        events.push(BackendEvent::Finished);
    } else if event_type == "cli_phase" {
        if let Some(phase) = event.phase.filter(|value| !value.trim().is_empty()) {
            events.push(BackendEvent::PhaseChanged(phase));
        }
    } else if event_type == "cli_tool" {
        let tool_name = collect_tool_names(&event).into_iter().next();
        if let Some(tool_name) = tool_name {
            match event.action.as_deref() {
                Some("started") => events.push(BackendEvent::ToolStarted(tool_name)),
                Some("finished") => events.push(BackendEvent::ToolFinished(tool_name)),
                _ => {}
            }
        }
    } else if let Some(kind) = live_message_kind(event_type, role, &content) {
        events.push(BackendEvent::LiveChunk(kind, content));
    } else if !content.is_empty() {
        match event_type {
            "tool_call" => {
                if let Some(summary) = summarize_tool_event(&tool_names, &content) {
                    events.push(BackendEvent::Message(
                        MessageKind::Tool,
                        format!("running {summary}"),
                    ));
                }
            }
            "tool_result" => {
                if let Some(summary) = summarize_tool_event(&tool_names, &content) {
                    events.push(BackendEvent::Message(
                        MessageKind::Tool,
                        format!("completed {summary}"),
                    ));
                }
            }
            "error" | "cli_error" => events.push(BackendEvent::Error(content)),
            "cli_stats" | "cli_phase" | "cli_tool" | "token_usage" | "start" | "done" => {}
            _ => events.push(BackendEvent::Message(
                MessageKind::Process,
                truncate(
                    &content.split_whitespace().collect::<Vec<_>>().join(" "),
                    180,
                ),
            )),
        }
    }

    for name in tool_names {
        if is_visible_tool(DisplayMode::Compact, &name) {
            events.push(BackendEvent::Status(format!("tool  {}", name)));
        }
    }

    events
}
