use crate::app::MessageKind;
use crate::backend::contract::CliStreamEvent;
use crate::backend::{BackendPhaseTiming, BackendStats, BackendToolStep};


pub(super) fn backend_stats_from_event(event: CliStreamEvent) -> BackendStats {
    BackendStats {
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
    }
}

pub(super) fn live_message_kind(event_type: &str, role: &str, content: &str) -> Option<MessageKind> {
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

pub(super) fn summarize_tool_event(names: &[String], content: &str) -> String {
    if !names.is_empty() {
        return names.join(", ");
    }

    truncate(&clean_single_line(content), 140)
}

pub(super) fn collect_tool_names(event: &CliStreamEvent) -> Vec<String> {
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

pub(super) fn truncate(text: &str, max_len: usize) -> String {
    if text.chars().count() <= max_len {
        return text.to_string();
    }
    text.chars()
        .take(max_len.saturating_sub(3))
        .collect::<String>()
        + "..."
}

fn clean_single_line(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

