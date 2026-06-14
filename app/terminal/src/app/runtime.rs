use std::time::Instant;

use ratatui::text::Line;

use crate::app::runtime_support::{
    backend_phase_timing_summary, backend_tool_step_summary, duration_from_seconds,
    flush_completed_live_lines, format_duration, normalize_phase_label, request_timing_summary,
};
use crate::app::{ActiveToolRecord, App, MessageKind};
use crate::app_render::{format_message, format_message_continuation, welcome_lines};
use crate::display_policy::{is_visible_tool, DisplayMode};

impl App {
    pub fn append_assistant_chunk(&mut self, chunk: &str) {
        self.append_live_chunk(MessageKind::Assistant, chunk);
    }

    pub fn append_process_chunk(&mut self, chunk: &str) {
        self.append_live_chunk(MessageKind::Process, chunk);
    }

    pub fn push_message(&mut self, kind: MessageKind, text: impl Into<String>) {
        self.flush_live_message();
        self.queue_message(kind, text.into());
    }

    pub fn set_status(&mut self, status: impl Into<String>) {
        self.status = status.into();
    }

    pub fn set_active_phase(&mut self, phase: impl Into<String>) {
        let phase = phase.into();
        let normalized = normalize_phase_label(self.display_mode, &phase);
        if normalized.is_empty() {
            return;
        }
        self.active_phase = Some(normalized.clone());
    }

    pub fn complete_request(&mut self) {
        let had_active_request = self.busy
            || self.current_task.is_some()
            || self.request_started_at.is_some()
            || self.live_message.is_some()
            || self.pending_backend_stats.is_some();
        if !had_active_request {
            return;
        }

        self.busy = false;
        self.current_task = None;
        let backend_stats = self.pending_backend_stats.take();
        self.last_request_duration = backend_stats
            .as_ref()
            .and_then(|stats| duration_from_seconds(stats.elapsed_seconds))
            .or_else(|| self.request_started_at.map(|started| started.elapsed()));
        self.last_first_output_latency = backend_stats
            .as_ref()
            .and_then(|stats| duration_from_seconds(stats.first_output_seconds))
            .or(self.first_output_latency);
        let completion_summary = request_timing_summary(
            self.last_request_duration,
            self.last_first_output_latency,
            backend_stats.as_ref(),
            self.display_mode,
        );
        self.request_started_at = None;
        self.first_output_latency = None;
        self.active_phase = None;
        self.active_tools.clear();
        self.flush_live_message();
        self.reset_assistant_live_filter();
        let mut completion_lines = Vec::new();
        if matches!(self.display_mode, DisplayMode::Verbose) {
            if let Some(stats) = backend_stats.as_ref() {
                if let Some(tool_summary) =
                    backend_tool_step_summary(&stats.tool_steps, self.display_mode)
                {
                    completion_lines.push(tool_summary);
                }
                if let Some(phase_summary) =
                    backend_phase_timing_summary(&stats.phase_timings, self.display_mode)
                {
                    completion_lines.push(phase_summary);
                }
            }
        }
        if let Some(summary) = completion_summary {
            completion_lines.push(format!("completed • {summary}"));
        }
        if !completion_lines.is_empty() {
            self.queue_message(MessageKind::Process, completion_lines.join("\n"));
        }
        self.status = format!("ready  {}", self.session_id);
    }

    pub fn fail_request(&mut self, message: impl Into<String>) {
        self.busy = false;
        self.current_task = None;
        let backend_stats = self.pending_backend_stats.take();
        self.last_request_duration = backend_stats
            .as_ref()
            .and_then(|stats| duration_from_seconds(stats.elapsed_seconds))
            .or_else(|| self.request_started_at.map(|started| started.elapsed()));
        self.last_first_output_latency = backend_stats
            .as_ref()
            .and_then(|stats| duration_from_seconds(stats.first_output_seconds))
            .or(self.first_output_latency);
        let completion_summary = request_timing_summary(
            self.last_request_duration,
            self.last_first_output_latency,
            backend_stats.as_ref(),
            self.display_mode,
        );
        self.request_started_at = None;
        self.first_output_latency = None;
        self.active_phase = None;
        self.active_tools.clear();
        self.flush_live_message();
        self.reset_assistant_live_filter();
        let mut completion_lines = Vec::new();
        if matches!(self.display_mode, DisplayMode::Verbose) {
            if let Some(stats) = backend_stats.as_ref() {
                if let Some(tool_summary) =
                    backend_tool_step_summary(&stats.tool_steps, self.display_mode)
                {
                    completion_lines.push(tool_summary);
                }
                if let Some(phase_summary) =
                    backend_phase_timing_summary(&stats.phase_timings, self.display_mode)
                {
                    completion_lines.push(phase_summary);
                }
            }
        }
        if let Some(summary) = completion_summary {
            completion_lines.push(format!("failed • {summary}"));
        }
        if !completion_lines.is_empty() {
            self.queue_message(MessageKind::Process, completion_lines.join("\n"));
        }
        self.queue_message(MessageKind::System, message.into());
        self.status = format!("error  {}", self.session_id);
    }

    pub fn interrupt_request(&mut self) {
        if !self.busy {
            return;
        }

        let had_partial_output = self
            .live_message
            .as_ref()
            .map(|(_, text)| !text.trim().is_empty())
            .unwrap_or(false);
        let had_visible_output = had_partial_output
            || self.live_message_had_history
            || self.first_output_latency.is_some();
        let backend_stats = self.pending_backend_stats.take();
        self.last_request_duration = backend_stats
            .as_ref()
            .and_then(|stats| duration_from_seconds(stats.elapsed_seconds))
            .or_else(|| self.request_started_at.map(|started| started.elapsed()));
        self.last_first_output_latency = backend_stats
            .as_ref()
            .and_then(|stats| duration_from_seconds(stats.first_output_seconds))
            .or(self.first_output_latency);
        let completion_summary = request_timing_summary(
            self.last_request_duration,
            self.last_first_output_latency,
            backend_stats.as_ref(),
            self.display_mode,
        );
        self.busy = false;
        self.current_task = None;
        self.request_started_at = None;
        self.first_output_latency = None;
        self.active_phase = None;
        self.active_tools.clear();
        self.flush_live_message();
        self.reset_assistant_live_filter();

        let mut lines = Vec::new();
        if let Some(summary) = completion_summary {
            lines.push(format!("interrupted • {summary}"));
        } else {
            lines.push("interrupted".to_string());
        }
        if had_visible_output {
            lines.push("partial output preserved • /retry available".to_string());
        } else {
            lines.push("/retry available".to_string());
        }
        self.queue_message(MessageKind::Process, lines.join("\n"));
        self.status = format!("interrupted  {}", self.session_id);
    }

    pub fn rendered_live_lines(&self) -> Vec<Line<'static>> {
        if !self.busy {
            return Vec::new();
        }

        match &self.live_message {
            Some((kind, text)) if !text.trim().is_empty() => format_message(*kind, text, false),
            _ => format_message(MessageKind::Process, "working...", false),
        }
    }

    pub fn rendered_main_lines(&self, width: u16) -> Vec<Line<'static>> {
        if self.busy {
            return self.rendered_live_lines();
        }

        self.rendered_idle_lines(width)
    }

    pub fn rendered_idle_lines(&self, width: u16) -> Vec<Line<'static>> {
        if !self.pending_welcome_banner
            || self.help_overlay_visible
            || self.session_picker.is_some()
        {
            return Vec::new();
        }

        let agent_label = self.active_agent_label();
        welcome_lines(
            width,
            &self.session_id,
            &agent_label,
            &self.agent_mode_status_label(),
            self.display_mode,
            &self.max_loop_count_status_label(),
            &self.workspace_label,
            &self.sandbox_type_status_label(),
        )
    }

    pub fn take_pending_history_lines(&mut self) -> Vec<Line<'static>> {
        let lines = std::mem::take(&mut self.pending_history_lines);
        if !lines.is_empty() {
            self.committed_history_lines.extend(lines.clone());
        }
        lines
    }

    pub fn take_clear_request(&mut self) -> bool {
        let requested = self.clear_requested;
        self.clear_requested = false;
        requested
    }

    pub fn take_backend_restart_request(&mut self) -> bool {
        let requested = self.backend_restart_requested;
        self.backend_restart_requested = false;
        requested
    }

    pub fn live_elapsed_seconds(&self) -> Option<u64> {
        self.request_started_at
            .map(|started| started.elapsed().as_secs())
    }

    pub fn footer_status(&self) -> String {
        let mut parts = vec![self.status.clone()];
        if self.busy {
            if let Some(started) = self.request_started_at {
                parts.push(format!("total {}", format_duration(started.elapsed())));
            }
            if let Some(ttft) = self.first_output_latency {
                parts.push(format!("ttft {}", format_duration(ttft)));
            }
        } else {
            if let Some(duration) = self.last_request_duration {
                parts.push(format!("total {}", format_duration(duration)));
            }
            if let Some(ttft) = self.last_first_output_latency {
                parts.push(format!("ttft {}", format_duration(ttft)));
            }
        }
        parts.join("  •  ")
    }

    pub fn active_tool_status(&self) -> Option<String> {
        let visible_tools = self
            .active_tools
            .iter()
            .filter(|(name, _)| is_visible_tool(self.display_mode, name))
            .collect::<Vec<_>>();
        let (name, record) = visible_tools.first().copied()?;
        let elapsed = format_duration(record.started_at.elapsed());
        if visible_tools.len() == 1 {
            if matches!(self.display_mode, DisplayMode::Verbose) {
                Some(format!("#{} {name}  {elapsed}", record.step))
            } else {
                Some(format!("{name}  {elapsed}"))
            }
        } else {
            if matches!(self.display_mode, DisplayMode::Verbose) {
                Some(format!(
                    "#{} {name} +{}  {elapsed}",
                    record.step,
                    visible_tools.len().saturating_sub(1)
                ))
            } else {
                Some(format!(
                    "{name} +{}  {elapsed}",
                    visible_tools.len().saturating_sub(1)
                ))
            }
        }
    }

    pub fn active_phase_label(&self) -> Option<&str> {
        self.active_phase.as_deref()
    }

    pub fn start_tool(&mut self, name: String) {
        let show_detail = is_visible_tool(self.display_mode, &name);
        self.tool_step_seq = self.tool_step_seq.saturating_add(1);
        let step = self.tool_step_seq;
        let started_at = Instant::now();
        self.active_tools
            .insert(name.clone(), ActiveToolRecord { step, started_at });
        if !show_detail || matches!(self.display_mode, DisplayMode::Compact) {
            return;
        }
        let since_request = self
            .request_started_at
            .map(|started| format!(" • +{}", format_duration(started.elapsed())))
            .unwrap_or_default();
        let detail = format!("step {}  running {name}{since_request}", self.tool_step_seq);
        self.queue_message(MessageKind::Tool, detail);
    }

    pub fn finish_tool(&mut self, name: String) {
        let show_detail = is_visible_tool(self.display_mode, &name);
        let detail = self
            .active_tools
            .remove(&name)
            .map(|record| {
                format!(
                    "step {}  completed {} • {}",
                    record.step,
                    name,
                    format_duration(record.started_at.elapsed())
                )
            })
            .unwrap_or_else(|| format!("completed {name}"));
        if !show_detail || matches!(self.display_mode, DisplayMode::Compact) {
            return;
        }
        self.queue_message(MessageKind::Tool, detail);
    }

    pub(crate) fn materialize_pending_ui(&mut self, _width: u16) {
        if !self.pending_welcome_banner
            || !self.committed_history_lines.is_empty()
            || self.pending_history_lines.is_empty()
        {
            return;
        }

        self.clear_requested = true;
    }

    pub(crate) fn has_transcript_lines(&self) -> bool {
        !self.committed_history_lines.is_empty() || !self.pending_history_lines.is_empty()
    }

    pub(super) fn append_live_chunk(&mut self, kind: MessageKind, chunk: &str) {
        if chunk.is_empty() {
            return;
        }
        self.record_first_output();
        match self.live_message.as_mut() {
            Some((current_kind, text)) if *current_kind == kind => {
                text.push_str(chunk);
                if kind == MessageKind::Assistant {
                    clean_assistant_live_text(text);
                    filter_completed_duplicate_assistant_lines(
                        text,
                        &mut self.assistant_live_seen_lines,
                        &mut self.assistant_live_in_code_block,
                    );
                }
                self.live_message_had_history |= flush_completed_live_lines(
                    &mut self.pending_history_lines,
                    *current_kind,
                    text,
                    self.live_message_had_history,
                );
            }
            Some(_) => {
                self.flush_live_message();
                let mut text = chunk.to_string();
                if kind == MessageKind::Assistant {
                    clean_assistant_live_text(&mut text);
                    filter_completed_duplicate_assistant_lines(
                        &mut text,
                        &mut self.assistant_live_seen_lines,
                        &mut self.assistant_live_in_code_block,
                    );
                }
                self.live_message_had_history = flush_completed_live_lines(
                    &mut self.pending_history_lines,
                    kind,
                    &mut text,
                    false,
                );
                self.live_message = Some((kind, text));
            }
            None => {
                let mut text = chunk.to_string();
                if kind == MessageKind::Assistant {
                    clean_assistant_live_text(&mut text);
                    filter_completed_duplicate_assistant_lines(
                        &mut text,
                        &mut self.assistant_live_seen_lines,
                        &mut self.assistant_live_in_code_block,
                    );
                }
                self.live_message_had_history = flush_completed_live_lines(
                    &mut self.pending_history_lines,
                    kind,
                    &mut text,
                    false,
                );
                self.live_message = Some((kind, text));
            }
        }
    }

    pub(super) fn flush_live_message(&mut self) {
        if let Some((kind, text)) = self.live_message.take() {
            if !text.trim().is_empty() {
                let mut text = text;
                if kind == MessageKind::Assistant {
                    filter_final_duplicate_assistant_text(
                        &mut text,
                        &mut self.assistant_live_seen_lines,
                        &mut self.assistant_live_in_code_block,
                    );
                }
                if text.trim().is_empty() {
                    self.live_message_had_history = false;
                    return;
                }
                if self.live_message_had_history {
                    self.pending_history_lines
                        .extend(format_message_continuation(kind, &text, true));
                } else {
                    self.queue_message(kind, text);
                }
            }
        }
        self.live_message_had_history = false;
    }

    pub(crate) fn clear_live_response_state(&mut self) {
        self.live_message = None;
        self.live_message_had_history = false;
        self.reset_assistant_live_filter();
    }

    fn reset_assistant_live_filter(&mut self) {
        self.assistant_live_seen_lines.clear();
        self.assistant_live_in_code_block = false;
    }

    pub(super) fn queue_message(&mut self, kind: MessageKind, text: impl Into<String>) {
        if kind != MessageKind::User {
            self.record_first_output();
        }
        self.pending_history_lines
            .extend(format_message(kind, &text.into(), true));
    }

    pub(super) fn record_first_output(&mut self) {
        if self.first_output_latency.is_some() {
            return;
        }
        if let Some(started) = self.request_started_at {
            self.first_output_latency = Some(started.elapsed());
        }
    }

    pub fn apply_backend_stats(&mut self, stats: crate::backend::BackendStats) {
        self.pending_backend_stats = Some(stats);
    }
}

fn clean_assistant_live_text(text: &mut String) {
    strip_loop_diagnostics(text);
    dedupe_repeated_assistant_lines(text);
    collapse_adjacent_repeated_phrases(text);
}

fn strip_loop_diagnostics(text: &mut String) {
    strip_from_marker(
        text,
        "Self-check: Repeating execution loop detected",
        "clarification question.",
    );
    strip_from_marker(text, "检测到任务进入重复循环", "继续。");
}

fn strip_from_marker(text: &mut String, start_marker: &str, end_marker: &str) {
    while let Some(start) = text.find(start_marker) {
        let tail = &text[start..];
        let end = tail
            .find(end_marker)
            .map(|index| start + index + end_marker.len())
            .unwrap_or_else(|| text.len());
        text.replace_range(start..end, "");
    }
}

fn dedupe_repeated_assistant_lines(text: &mut String) {
    if !text.contains('\n') {
        return;
    }

    let had_trailing_newline = text.ends_with('\n');
    let mut deduped = Vec::new();
    let mut seen_non_empty = std::collections::BTreeSet::new();
    let mut changed = false;
    let mut in_code_block = false;

    for line in text.lines() {
        let normalized = line.trim();
        if normalized.starts_with("```") {
            in_code_block = !in_code_block;
            deduped.push(line);
            continue;
        }
        if !in_code_block
            && !normalized.is_empty()
            && !seen_non_empty.insert(normalized.to_string())
        {
            changed = true;
            continue;
        }
        deduped.push(line);
    }

    if !changed {
        return;
    }

    *text = deduped.join("\n");
    if had_trailing_newline {
        text.push('\n');
    }
}

fn filter_completed_duplicate_assistant_lines(
    text: &mut String,
    seen: &mut std::collections::BTreeSet<String>,
    in_code_block: &mut bool,
) {
    let Some(split_at) = text.rfind('\n') else {
        return;
    };

    let completed = text[..split_at].to_string();
    let remainder = text[split_at + 1..].to_string();
    let mut kept = Vec::new();
    let mut changed = false;

    for line in completed.lines() {
        let normalized = line.trim();
        if normalized.starts_with("```") {
            *in_code_block = !*in_code_block;
            kept.push(line);
            continue;
        }
        if !*in_code_block && !normalized.is_empty() && !seen.insert(normalized.to_string()) {
            changed = true;
            continue;
        }
        kept.push(line);
    }

    if !changed {
        return;
    }

    let mut filtered = kept.join("\n");
    if !filtered.is_empty() {
        filtered.push('\n');
    }
    filtered.push_str(&remainder);
    *text = filtered;
}

fn filter_final_duplicate_assistant_text(
    text: &mut String,
    seen: &mut std::collections::BTreeSet<String>,
    in_code_block: &mut bool,
) {
    if text.contains('\n') {
        filter_completed_duplicate_assistant_lines(text, seen, in_code_block);
    }

    let normalized = text.trim();
    if normalized.is_empty()
        || normalized.starts_with("```")
        || *in_code_block
        || seen.insert(normalized.to_string())
    {
        return;
    }

    text.clear();
}

fn collapse_adjacent_repeated_phrases(text: &mut String) {
    if text.contains("```") || text.chars().count() > 4_000 {
        return;
    }

    let had_trailing_newline = text.ends_with('\n');
    let mut collapsed = text
        .lines()
        .map(collapse_line_repeats)
        .collect::<Vec<_>>()
        .join("\n");
    if had_trailing_newline {
        collapsed.push('\n');
    }
    if collapsed != *text {
        *text = collapsed;
    }
}

fn collapse_line_repeats(line: &str) -> String {
    let chars = line.chars().collect::<Vec<_>>();
    if chars.len() < 16 {
        return line.to_string();
    }

    let mut output = Vec::with_capacity(chars.len());
    let mut index = 0;
    while index < chars.len() {
        let remaining = chars.len() - index;
        let max_len = (remaining / 2).min(160);
        let mut collapsed = false;
        for len in (8..=max_len).rev() {
            let left = &chars[index..index + len];
            let right = &chars[index + len..index + (len * 2)];
            if left == right && repeated_phrase_is_user_text(left) {
                output.extend_from_slice(left);
                index += len * 2;
                collapsed = true;
                break;
            }
        }
        if !collapsed {
            output.push(chars[index]);
            index += 1;
        }
    }

    output.into_iter().collect()
}

fn repeated_phrase_is_user_text(chars: &[char]) -> bool {
    let text = chars.iter().collect::<String>();
    text.contains('。')
        || text.contains('！')
        || text.contains('？')
        || text.contains("Hello")
        || text.contains("hello")
}
