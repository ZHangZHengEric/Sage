use std::time::{Duration, Instant};

use ratatui::text::Line;

use crate::app::{App, MessageKind};
use crate::app_render::{format_message, format_message_continuation, welcome_lines};

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

    pub fn complete_request(&mut self) {
        self.busy = false;
        self.last_request_duration = self.request_started_at.map(|started| started.elapsed());
        self.last_first_output_latency = self.first_output_latency;
        self.request_started_at = None;
        self.first_output_latency = None;
        self.active_tools.clear();
        self.flush_live_message();
        self.status = format!("ready  {}", self.session_id);
    }

    pub fn fail_request(&mut self, message: impl Into<String>) {
        self.busy = false;
        self.last_request_duration = self.request_started_at.map(|started| started.elapsed());
        self.last_first_output_latency = self.first_output_latency;
        self.request_started_at = None;
        self.first_output_latency = None;
        self.active_tools.clear();
        self.flush_live_message();
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
        let (name, started) = self.active_tools.iter().next()?;
        let elapsed = format_duration(started.elapsed());
        if self.active_tools.len() == 1 {
            Some(format!("{name}  {elapsed}"))
        } else {
            Some(format!(
                "{name} +{}  {elapsed}",
                self.active_tools.len().saturating_sub(1)
            ))
        }
    }

    pub fn start_tool(&mut self, name: String) {
        self.active_tools.insert(name.clone(), Instant::now());
        self.queue_message(MessageKind::Tool, format!("running {}", name));
    }

    pub fn finish_tool(&mut self, name: String) {
        let elapsed = self
            .active_tools
            .remove(&name)
            .map(|started| format!(" ({})", format_duration(started.elapsed())))
            .unwrap_or_default();
        self.queue_message(MessageKind::Tool, format!("completed {name}{elapsed}"));
    }

    pub(crate) fn materialize_pending_ui(&mut self, width: u16) {
        if !self.pending_welcome_banner || self.pending_history_lines.is_empty() {
            return;
        }

        let mut lines = welcome_lines(
            width,
            &self.session_id,
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
}

fn format_duration(duration: Duration) -> String {
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

fn flush_completed_live_lines(
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
