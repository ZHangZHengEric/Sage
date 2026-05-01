use std::time::Instant;

use ratatui::text::Line;

use crate::app::{ActiveToolRecord, App, MessageKind};
use crate::app_render::{format_message, format_message_continuation, welcome_lines};
use crate::app::runtime_support::{
    backend_phase_timing_summary,
    backend_tool_step_summary,
    duration_from_seconds,
    flush_completed_live_lines,
    format_duration,
    normalize_phase_label,
    request_timing_summary,
};

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
        let normalized = normalize_phase_label(&phase);
        if normalized.is_empty() {
            return;
        }
        self.active_phase = Some(normalized.clone());
    }

    pub fn complete_request(&mut self) {
        self.busy = false;
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
        );
        self.request_started_at = None;
        self.first_output_latency = None;
        self.active_phase = None;
        self.active_tools.clear();
        self.flush_live_message();
        if let Some(stats) = backend_stats.as_ref() {
            if let Some(tool_summary) = backend_tool_step_summary(&stats.tool_steps) {
                self.queue_message(MessageKind::Tool, tool_summary);
            }
            if let Some(phase_summary) = backend_phase_timing_summary(&stats.phase_timings) {
                self.queue_message(MessageKind::Process, phase_summary);
            }
        }
        if let Some(summary) = completion_summary {
            self.queue_message(MessageKind::Process, format!("completed  {summary}"));
        }
        self.status = format!("ready  {}", self.session_id);
    }

    pub fn fail_request(&mut self, message: impl Into<String>) {
        self.busy = false;
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
        );
        self.request_started_at = None;
        self.first_output_latency = None;
        self.active_phase = None;
        self.active_tools.clear();
        self.flush_live_message();
        if let Some(stats) = backend_stats.as_ref() {
            if let Some(tool_summary) = backend_tool_step_summary(&stats.tool_steps) {
                self.queue_message(MessageKind::Tool, tool_summary);
            }
            if let Some(phase_summary) = backend_phase_timing_summary(&stats.phase_timings) {
                self.queue_message(MessageKind::Process, phase_summary);
            }
        }
        if let Some(summary) = completion_summary {
            self.queue_message(MessageKind::Process, format!("failed  {summary}"));
        }
        self.queue_message(MessageKind::System, message.into());
        self.status = format!("error  {}", self.session_id);
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

    pub fn rendered_idle_lines(&self, width: u16) -> Vec<Line<'static>> {
        if !self.pending_welcome_banner
            || self.help_overlay_visible
            || self.session_picker.is_some()
        {
            return Vec::new();
        }

        welcome_lines(
            width,
            &self.session_id,
            self.selected_agent_id.as_deref(),
            &self.agent_mode,
            self.max_loop_count,
            &self.workspace_label,
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
        let (name, record) = self.active_tools.iter().next()?;
        let elapsed = format_duration(record.started_at.elapsed());
        if self.active_tools.len() == 1 {
            Some(format!("#{} {name}  {elapsed}", record.step))
        } else {
            Some(format!(
                "#{} {name} +{}  {elapsed}",
                record.step,
                self.active_tools.len().saturating_sub(1)
            ))
        }
    }

    pub fn active_phase_label(&self) -> Option<&str> {
        self.active_phase.as_deref()
    }

    pub fn start_tool(&mut self, name: String) {
        self.tool_step_seq = self.tool_step_seq.saturating_add(1);
        let step = self.tool_step_seq;
        let started_at = Instant::now();
        self.active_tools.insert(
            name.clone(),
            ActiveToolRecord {
                step,
                started_at,
            },
        );
        let since_request = self
            .request_started_at
            .map(|started| format!(" • +{}", format_duration(started.elapsed())))
            .unwrap_or_default();
        self.queue_message(
            MessageKind::Tool,
            format!("step {step}  running {name}{since_request}"),
        );
    }

    pub fn finish_tool(&mut self, name: String) {
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
        self.queue_message(MessageKind::Tool, detail);
    }

    pub(crate) fn materialize_pending_ui(&mut self, width: u16) {
        if !self.pending_welcome_banner || self.pending_history_lines.is_empty() {
            return;
        }

        let mut lines = welcome_lines(
            width,
            &self.session_id,
            self.selected_agent_id.as_deref(),
            &self.agent_mode,
            self.max_loop_count,
            &self.workspace_label,
        );
        lines.append(&mut self.pending_history_lines);
        self.pending_history_lines = lines;
        self.pending_welcome_banner = false;
    }

    pub(super) fn append_live_chunk(&mut self, kind: MessageKind, chunk: &str) {
        if chunk.is_empty() {
            return;
        }
        self.record_first_output();
        match self.live_message.as_mut() {
            Some((current_kind, text)) if *current_kind == kind => {
                text.push_str(chunk);
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
