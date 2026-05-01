use std::collections::BTreeMap;
use std::time::Duration;

use ratatui::text::Line;

use crate::app::MessageKind;
use crate::app_render::{format_message, format_message_continuation};
use crate::backend::{BackendPhaseTiming, BackendStats, BackendToolStep};
use crate::display_policy::{
    classify_tool_name, display_phase_label, is_visible_tool, DisplayMode, ToolDisplayClass,
};

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

pub(super) fn backend_tool_step_summary(
    tool_steps: &[BackendToolStep],
    mode: DisplayMode,
) -> Option<String> {
    let displayable_steps = tool_steps
        .iter()
        .filter(|step| {
            !matches!(
                classify_tool_name(&step.tool_name),
                ToolDisplayClass::Hidden
            )
        })
        .collect::<Vec<_>>();

    if displayable_steps.is_empty() {
        return None;
    }

    let visible_steps = displayable_steps
        .iter()
        .copied()
        .filter(|step| is_visible_tool(mode, &step.tool_name))
        .collect::<Vec<_>>();
    let internal_count = displayable_steps.len().saturating_sub(visible_steps.len());

    if visible_steps.is_empty() {
        return None;
    }

    if matches!(mode, DisplayMode::Verbose) || (internal_count == 0 && visible_steps.len() <= 4) {
        if matches!(mode, DisplayMode::Compact) {
            let details = visible_steps
                .iter()
                .map(|step| {
                    let mut detail = step.tool_name.clone();
                    if let Some(duration_ms) = duration_from_millis(step.duration_ms) {
                        detail.push(' ');
                        detail.push_str(&format_duration(duration_ms));
                    }
                    detail
                })
                .collect::<Vec<_>>();
            return Some(format!("tools • {}", details.join(" • ")));
        }

        let mut lines = Vec::with_capacity(visible_steps.len() + 1);
        lines.push("tools".to_string());
        for step in visible_steps {
            let mut detail = if matches!(mode, DisplayMode::Verbose) {
                format!(
                    "step {}  {} {}",
                    step.step,
                    normalize_tool_status(&step.status),
                    step.tool_name
                )
            } else {
                format!("{} {}", normalize_tool_status(&step.status), step.tool_name)
            };
            if let Some(duration_ms) = duration_from_millis(step.duration_ms) {
                detail.push_str(&format!(" • {}", format_duration(duration_ms)));
            }
            lines.push(detail);
        }
        return Some(lines.join("\n"));
    }

    let mut counts = BTreeMap::<String, usize>::new();
    for step in &visible_steps {
        *counts.entry(step.tool_name.clone()).or_default() += 1;
    }
    let mut aggregated = counts.into_iter().collect::<Vec<_>>();
    aggregated.sort_by(|(left_name, left_count), (right_name, right_count)| {
        right_count
            .cmp(left_count)
            .then_with(|| left_name.cmp(right_name))
    });

    if visible_steps.len() == 1 {
        let step = visible_steps[0];
        let mut parts = vec!["tools".to_string(), step.tool_name.clone()];
        if let Some(duration_ms) = duration_from_millis(step.duration_ms) {
            parts.push(format_duration(duration_ms));
        }
        if internal_count > 0 {
            parts.push(format!("internal tools ×{internal_count}"));
        }
        return Some(parts.join(" • "));
    }

    let mut summary_parts = aggregated
        .iter()
        .take(3)
        .map(|(name, count)| format!("{name} ×{count}"))
        .collect::<Vec<_>>();
    if internal_count > 0 {
        summary_parts.push(format!("internal tools ×{internal_count}"));
    }
    let remaining = aggregated.len().saturating_sub(3);
    if remaining > 0 {
        summary_parts.push(format!("+{remaining} more"));
    }

    let mut summary = format!("tools • {}", summary_parts.join(" • "));
    if let Some(slowest) = visible_steps
        .iter()
        .filter_map(|step| step.duration_ms.map(|duration_ms| (step, duration_ms)))
        .max_by(|(_, left), (_, right)| left.total_cmp(right))
    {
        let (step, duration_ms) = slowest;
        summary.push_str(&format!(
            " • slowest {} {}",
            step.tool_name,
            format_duration(Duration::from_secs_f64(duration_ms / 1000.0))
        ));
    }

    Some(summary)
}

pub(super) fn backend_phase_timing_summary(
    phase_timings: &[BackendPhaseTiming],
    mode: DisplayMode,
) -> Option<String> {
    if phase_timings.is_empty() {
        return None;
    }

    let details = phase_timings
        .iter()
        .map(|phase| {
            let mut detail = display_phase_label(mode, &phase.phase);
            if let Some(duration_ms) = duration_from_millis(phase.duration_ms) {
                detail.push_str(&format!(" {}", format_duration(duration_ms)));
            }
            if phase.segment_count > 1 {
                detail.push_str(&format!(" • {} segments", phase.segment_count));
            }
            detail
        })
        .collect::<Vec<_>>();

    if details.len() == 1 {
        Some(format!("phase • {}", details[0]))
    } else if details.len() <= 3 {
        Some(format!("phases • {}", details.join(" • ")))
    } else {
        let mut lines = Vec::with_capacity(details.len() + 1);
        lines.push("phases".to_string());
        lines.extend(details);
        Some(lines.join("\n"))
    }
}

pub(super) fn normalize_phase_label(mode: DisplayMode, phase: &str) -> String {
    display_phase_label(mode, phase)
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
