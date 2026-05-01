use std::time::Duration;

use ratatui::text::Line;

use crate::app::MessageKind;
use crate::app_render::{format_message, format_message_continuation};
use crate::backend::{BackendPhaseTiming, BackendStats, BackendToolStep};


pub(super) fn format_duration(duration: Duration) -> String {
    let secs = duration.as_secs();
    let millis = duration.subsec_millis();
    if secs >= 3600 {
        format!("{}h {:02}m", secs / 3600, (secs % 3600) / 60)
    } else if secs >= 60 {
        format!("{}m {:02}s", secs / 60, secs % 60)
    } else if secs >= 1 {
        format!("{secs}.{:<01}s", millis / 100)
    } else {
        format!("{}ms", duration.as_millis())
    }
}

pub(super) fn request_timing_summary(
    total: Option<Duration>,
    ttft: Option<Duration>,
    backend_stats: Option<&BackendStats>,
) -> Option<String> {
    let mut parts = Vec::new();
    if let Some(total) = total {
        parts.push(format!("total {}", format_duration(total)));
    }
    if let Some(ttft) = ttft {
        parts.push(format!("ttft {}", format_duration(ttft)));
    }
    if let Some(total_tokens) = backend_stats.and_then(|stats| stats.total_tokens) {
        parts.push(format!("tokens {total_tokens}"));
    }
    if parts.is_empty() {
        None
    } else {
        Some(parts.join(" • "))
    }
}

pub(super) fn duration_from_seconds(value: Option<f64>) -> Option<Duration> {
    value
        .filter(|seconds| seconds.is_finite() && *seconds >= 0.0)
        .map(Duration::from_secs_f64)
}

pub(super) fn flush_completed_live_lines(
    history: &mut Vec<Line<'static>>,
    kind: MessageKind,
    text: &mut String,
    continuation: bool,
) -> bool {
    let split_at = text.rfind('\n');
    let Some(split_at) = split_at else {
        return false;
    };

    let completed = text[..split_at].trim_end_matches('\n').to_string();
    let remainder = text[split_at + 1..].to_string();

    if !completed.trim().is_empty() {
        if continuation {
            history.extend(format_message_continuation(kind, &completed, false));
        } else {
            history.extend(format_message(kind, &completed, false));
        }
    }

    *text = remainder;
    !completed.trim().is_empty()
}

pub(super) fn backend_tool_step_summary(tool_steps: &[BackendToolStep]) -> Option<String> {
    if tool_steps.is_empty() {
        return None;
    }

    let mut lines = Vec::with_capacity(tool_steps.len() + 1);
    lines.push("tool steps".to_string());
    for step in tool_steps {
        let mut detail = format!(
            "step {}  {} {}",
            step.step,
            normalize_tool_status(&step.status),
            step.tool_name
        );
        if let Some(duration_ms) = duration_from_millis(step.duration_ms) {
            detail.push_str(&format!(" • {}", format_duration(duration_ms)));
        }
        lines.push(detail);
    }
    Some(lines.join("\n"))
}

pub(super) fn backend_phase_timing_summary(phase_timings: &[BackendPhaseTiming]) -> Option<String> {
    if phase_timings.is_empty() {
        return None;
    }

    let mut lines = Vec::with_capacity(phase_timings.len() + 1);
    lines.push("phase timings".to_string());
    for phase in phase_timings {
        let mut detail = phase.phase.replace('_', " ");
        if let Some(duration_ms) = duration_from_millis(phase.duration_ms) {
            detail.push_str(&format!(" • {}", format_duration(duration_ms)));
        }
        if phase.segment_count > 1 {
            detail.push_str(&format!(" • {} segments", phase.segment_count));
        }
        lines.push(detail);
    }
    Some(lines.join("\n"))
}

pub(super) fn normalize_phase_label(phase: &str) -> String {
    phase.trim().replace('_', " ")
}

fn normalize_tool_status(status: &str) -> &str {
    match status {
        "completed" => "completed",
        "running" => "running",
        "failed" => "failed",
        other if other.trim().is_empty() => "completed",
        other => other,
    }
}

fn duration_from_millis(value: Option<f64>) -> Option<Duration> {
    value
        .filter(|millis| millis.is_finite() && *millis >= 0.0)
        .map(|millis| Duration::from_secs_f64(millis / 1000.0))
}

