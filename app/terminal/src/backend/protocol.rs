use std::sync::mpsc;

use crate::app::MessageKind;
use crate::backend::contract::parse_stream_event;
use crate::backend::protocol_support::{
    backend_session_meta_from_event, backend_stats_from_event, collect_tool_names,
    is_internal_reasoning_event, live_message_kind, sandbox_approval_from_event,
    sandbox_approval_resolved_message, summarize_tool_event, truncate,
};
use crate::display_policy::{is_visible_tool, DisplayMode};

use super::BackendEvent;

#[derive(Default)]
pub(crate) struct BackendProtocolState {
    live_messages: Vec<LiveMessageState>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct LiveMessageState {
    kind: MessageKind,
    message_id: Option<String>,
    emitted: String,
}

impl BackendProtocolState {
    pub(crate) fn parse_line(&mut self, line: &str) -> Vec<BackendEvent> {
        parse_backend_line_with_state(line, Some(self))
    }

    fn live_delta(
        &mut self,
        kind: MessageKind,
        message_id: Option<String>,
        content: String,
    ) -> Option<String> {
        if content.is_empty() {
            return None;
        }

        let Some(state) = self.live_messages.iter_mut().find(|state| {
            state.kind == kind
                && match (&state.message_id, &message_id) {
                    (Some(left), Some(right)) => left == right,
                    (None, None) => true,
                    _ => false,
                }
        }) else {
            if let Some(prior) = self
                .live_messages
                .iter()
                .filter(|state| state.kind == kind && !state.emitted.is_empty())
                .max_by_key(|state| state.emitted.len())
            {
                if content == prior.emitted {
                    self.live_messages.push(LiveMessageState {
                        kind,
                        message_id,
                        emitted: content,
                    });
                    return None;
                }
                if prior.emitted.len() >= 3 {
                    if let Some(delta) = content.strip_prefix(&prior.emitted) {
                        let delta = delta.to_string();
                        self.live_messages.push(LiveMessageState {
                            kind,
                            message_id,
                            emitted: content,
                        });
                        return if delta.is_empty() { None } else { Some(delta) };
                    }
                    if let Some(delta) = overlap_delta(&prior.emitted, &content) {
                        let emitted = format!("{}{}", prior.emitted, delta);
                        self.live_messages.push(LiveMessageState {
                            kind,
                            message_id,
                            emitted,
                        });
                        return Some(delta);
                    }
                }
            }
            self.live_messages.push(LiveMessageState {
                kind,
                message_id,
                emitted: content.clone(),
            });
            return Some(content);
        };

        if content == state.emitted {
            return None;
        }
        if let Some(delta) = content.strip_prefix(&state.emitted) {
            let delta = delta.to_string();
            state.emitted = content;
            if delta.is_empty() {
                None
            } else {
                Some(delta)
            }
        } else if let Some(delta) = overlap_delta(&state.emitted, &content) {
            state.emitted.push_str(&delta);
            Some(delta)
        } else {
            state.emitted.push_str(&content);
            Some(content)
        }
    }

    fn reset_live_messages(&mut self) {
        self.live_messages.clear();
    }
}

fn overlap_delta(emitted: &str, content: &str) -> Option<String> {
    let overlap = longest_suffix_prefix_overlap(emitted, content);
    if overlap == 0 || overlap >= content.len() {
        return None;
    }
    Some(content[overlap..].to_string())
}

fn longest_suffix_prefix_overlap(left: &str, right: &str) -> usize {
    let mut best = 0;
    let mut best_chars = 0;
    for (index, ch) in right.char_indices() {
        let end = index + ch.len_utf8();
        if end > left.len() {
            break;
        }
        if left.ends_with(&right[..end]) {
            best = end;
            best_chars = right[..end].chars().count();
        }
    }

    if best_chars >= 3 {
        best
    } else {
        0
    }
}

pub(super) fn flush_complete_lines(
    pending: &mut Vec<u8>,
    sender: &mpsc::Sender<BackendEvent>,
    state: &mut BackendProtocolState,
) -> Result<(), mpsc::SendError<BackendEvent>> {
    while let Some(index) = pending.iter().position(|byte| *byte == b'\n') {
        let line = pending.drain(..=index).collect::<Vec<_>>();
        let line = String::from_utf8_lossy(&line);
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        for event in state.parse_line(line) {
            sender.send(event)?;
        }
    }
    Ok(())
}

#[cfg(test)]
pub(crate) fn parse_backend_line(line: &str) -> Vec<BackendEvent> {
    parse_backend_line_with_state(line, None)
}

fn parse_backend_line_with_state(
    line: &str,
    mut state: Option<&mut BackendProtocolState>,
) -> Vec<BackendEvent> {
    let mut events = Vec::new();
    let event = match parse_stream_event(line) {
        Some(event) => event,
        None => return events,
    };

    let event_type = event.event_type.as_str();
    let role = event.role.as_str();
    let tool_names = collect_tool_names(&event);
    let content = crate::backend::protocol_support::sanitize_assistant_content(&event.content);

    if event_type == "stream_end" {
        if let Some(state) = state.as_mut() {
            state.reset_live_messages();
        }
    }

    if event_type == "cli_session" || event.goal.is_some() {
        if let Some(meta) = backend_session_meta_from_event(&event) {
            events.push(BackendEvent::SessionHydrated(meta));
        }
    }

    if event_type == "cli_session" {
        // already handled above
    } else if event_type == "cli_stats" {
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
    } else if event_type == "cli_notice" {
        if !content.is_empty() {
            events.push(BackendEvent::Message(MessageKind::Process, content));
        }
    } else if event_type == "sandbox_approval_requested" {
        if let Some(request) = sandbox_approval_from_event(&event) {
            events.push(BackendEvent::SandboxApprovalRequested(request));
        }
    } else if event_type == "sandbox_approval_resolved" {
        if let Some(message) = sandbox_approval_resolved_message(&event) {
            events.push(BackendEvent::Message(MessageKind::Tool, message));
        }
    } else if let Some(kind) = live_message_kind(event_type, role, &content) {
        let content = match state.as_mut() {
            Some(state) => state.live_delta(kind, event.message_id.clone(), content),
            None => Some(content),
        };
        if let Some(content) = content {
            events.push(BackendEvent::LiveChunk(kind, content));
        }
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
            event_type if is_internal_reasoning_event(event_type) => {}
            "cli_stats" | "cli_phase" | "cli_tool" | "cli_notice" | "token_usage" | "start"
            | "done" => {}
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

    if events.iter().any(|event| {
        matches!(
            event,
            BackendEvent::Finished | BackendEvent::Error(_) | BackendEvent::Exited
        )
    }) {
        if let Some(state) = state.as_mut() {
            state.reset_live_messages();
        }
    }

    events
}
