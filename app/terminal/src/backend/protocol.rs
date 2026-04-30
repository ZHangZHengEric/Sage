use std::sync::mpsc;

use crate::app::MessageKind;
use crate::backend::contract::{parse_stream_event, CliStreamEvent};
use crate::backend::{BackendPhaseTiming, BackendStats, BackendToolStep};

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
        events.push(BackendEvent::Stats(BackendStats {
            elapsed_seconds: event.elapsed_seconds,
            first_output_seconds: event.first_output_seconds,
            prompt_tokens: event.prompt_tokens,
            completion_tokens: event.completion_tokens,
            total_tokens: event.total_tokens,
            tool_steps: event
                .tool_steps
                .into_iter()
                .map(|step| BackendToolStep {
                    step: step.step,
                    tool_name: step.tool_name,
                    tool_call_id: step.tool_call_id,
                    status: step.status,
                    started_at: step.started_at,
                    finished_at: step.finished_at,
                    duration_ms: step.duration_ms,
                })
                .collect(),
            phase_timings: event
                .phase_timings
                .into_iter()
                .map(|phase| BackendPhaseTiming {
                    phase: phase.phase,
                    started_at: phase.started_at,
                    finished_at: phase.finished_at,
                    duration_ms: phase.duration_ms,
                    segment_count: phase.segment_count,
                })
                .collect(),
        }));
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
            "tool_call" => events.push(BackendEvent::Message(
                MessageKind::Tool,
                format!("running {}", summarize_tool_event(&tool_names, &content)),
            )),
            "tool_result" => events.push(BackendEvent::Message(
                MessageKind::Tool,
                format!("completed {}", summarize_tool_event(&tool_names, &content)),
            )),
            "error" | "cli_error" => events.push(BackendEvent::Error(content)),
            "cli_stats" | "cli_phase" | "cli_tool" | "token_usage" | "start" | "done" => {}
            _ => events.push(BackendEvent::Message(
                MessageKind::Process,
                truncate(&clean_single_line(&content), 180),
            )),
        }
    }

    for name in tool_names {
        events.push(BackendEvent::Status(format!("tool  {}", name)));
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
            | "cli_phase"
            | "cli_tool"
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

fn collect_tool_names(event: &CliStreamEvent) -> Vec<String> {
    let mut names = Vec::new();
    for tool_call in &event.tool_calls {
        if !tool_call.function.name.is_empty() {
            names.push(tool_call.function.name.clone());
        }
    }

    if let Some(metadata_name) = event
        .metadata
        .as_ref()
        .and_then(|metadata| metadata.tool_name.as_ref())
    {
        names.push(metadata_name.to_string());
    }

    if let Some(event_name) = event.tool_name.as_ref() {
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
