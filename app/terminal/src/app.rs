use std::collections::BTreeMap;
use std::time::{Duration, Instant};

use ratatui::text::Line;

use crate::app_preview::provider_help_text;
use crate::app_render::{format_message, format_message_continuation, welcome_lines};
use crate::slash_command;

#[path = "app/surfaces.rs"]
mod surfaces;
#[cfg(test)]
#[path = "app/tests.rs"]
mod tests;

#[derive(Debug)]
pub enum SubmitAction {
    Noop,
    Handled,
    RunTask(String),
    OpenSessionPicker {
        mode: SessionPickerMode,
        limit: usize,
    },
    ResumeLatest,
    ResumeSession(String),
    ShowSession(String),
    ListSkills,
    EnableSkill(String),
    DisableSkill(String),
    ClearSkills,
    ShowConfig,
    ListProviders,
    ShowProvider(String),
    SetDefaultProvider(String),
    CreateProvider(Vec<String>),
    UpdateProvider {
        provider_id: String,
        fields: Vec<String>,
    },
    DeleteProvider(String),
    ShowModel,
    SetModel(String),
    ClearModel,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SessionPickerEntry {
    pub session_id: String,
    pub title: String,
    pub message_count: u64,
    pub updated_at: String,
    pub preview: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct SessionPickerState {
    mode: SessionPickerMode,
    items: Vec<SessionPickerEntry>,
    filter_query: String,
    selected: usize,
}

struct FilteredSessionPicker<'a> {
    items: Vec<(usize, &'a SessionPickerEntry)>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SessionPickerMode {
    Resume,
    Browse,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ActiveSurfaceKind {
    Help,
    SessionPicker,
    Transcript,
    Popup,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct TranscriptOverlayState {
    scroll: u16,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct ProviderCandidate {
    id: String,
    name: String,
    model: String,
    base_url: String,
    is_default: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ProviderPopupMode {
    Inspect,
    Default,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct SkillCandidate {
    name: String,
    description: String,
    source: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum SkillPopupMode {
    Add,
    Remove,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MessageKind {
    User,
    Assistant,
    Process,
    System,
    Tool,
}

pub struct App {
    pub input: String,
    pub input_cursor: usize,
    pub session_seq: u32,
    pub session_id: String,
    pub user_id: String,
    pub agent_mode: String,
    pub max_loop_count: u32,
    pub workspace_label: String,
    pub status: String,
    pub busy: bool,
    pub should_quit: bool,
    pub selected_skills: Vec<String>,
    pub selected_model: Option<String>,
    pub pending_history_lines: Vec<Line<'static>>,
    committed_history_lines: Vec<Line<'static>>,
    pub live_message: Option<(MessageKind, String)>,
    live_message_had_history: bool,
    request_started_at: Option<Instant>,
    first_output_latency: Option<Duration>,
    last_request_duration: Option<Duration>,
    last_first_output_latency: Option<Duration>,
    active_tools: BTreeMap<String, Instant>,
    pending_welcome_banner: bool,
    clear_requested: bool,
    backend_restart_requested: bool,
    slash_popup_selected: usize,
    help_overlay_visible: bool,
    help_overlay_topic: Option<String>,
    session_picker: Option<SessionPickerState>,
    transcript_overlay: Option<TranscriptOverlayState>,
    provider_catalog: Option<Vec<ProviderCandidate>>,
    skill_catalog: Option<Vec<SkillCandidate>>,
}

impl App {
    pub fn new() -> Self {
        let mut app = Self {
            input: String::new(),
            input_cursor: 0,
            session_seq: 1,
            session_id: String::new(),
            user_id: "default_user".to_string(),
            agent_mode: "simple".to_string(),
            max_loop_count: 50,
            workspace_label: current_workspace_label(),
            status: String::new(),
            busy: false,
            should_quit: false,
            selected_skills: Vec::new(),
            selected_model: None,
            pending_history_lines: Vec::new(),
            committed_history_lines: Vec::new(),
            live_message: None,
            live_message_had_history: false,
            request_started_at: None,
            first_output_latency: None,
            last_request_duration: None,
            last_first_output_latency: None,
            active_tools: BTreeMap::new(),
            pending_welcome_banner: false,
            clear_requested: false,
            backend_restart_requested: false,
            slash_popup_selected: 0,
            help_overlay_visible: false,
            help_overlay_topic: None,
            session_picker: None,
            transcript_overlay: None,
            provider_catalog: None,
            skill_catalog: None,
        };
        app.reset_session();
        // First launch should preserve the existing terminal scrollback.
        app.clear_requested = false;
        app
    }

    pub fn reset_session(&mut self) {
        self.session_id = format!("local-{:#06}", self.session_seq).replace("0x", "");
        self.session_seq += 1;
        self.clear_input();
        self.busy = false;
        self.live_message = None;
        self.live_message_had_history = false;
        self.request_started_at = None;
        self.first_output_latency = None;
        self.last_request_duration = None;
        self.last_first_output_latency = None;
        self.active_tools.clear();
        self.pending_history_lines.clear();
        self.committed_history_lines.clear();
        self.pending_welcome_banner = false;
        self.clear_requested = true;
        self.backend_restart_requested = true;
        self.slash_popup_selected = 0;
        self.help_overlay_visible = false;
        self.help_overlay_topic = None;
        self.session_picker = None;
        self.transcript_overlay = None;
        self.provider_catalog = None;
        self.skill_catalog = None;
        self.status = format!("ready  {}", self.session_id);
        self.queue_welcome_banner();
    }

    pub fn submit_input(&mut self) -> SubmitAction {
        let text = self.input.trim().to_string();
        if text.is_empty() {
            return SubmitAction::Noop;
        }

        self.clear_input();

        if text.starts_with('/') {
            return self.handle_command(&text);
        }

        self.queue_message(MessageKind::User, text.clone());
        self.busy = true;
        self.live_message = None;
        self.live_message_had_history = false;
        self.request_started_at = Some(Instant::now());
        self.first_output_latency = None;
        self.last_request_duration = None;
        self.active_tools.clear();
        self.status = format!("running  {}", self.session_id);
        SubmitAction::RunTask(text)
    }

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

    pub fn insert_char(&mut self, ch: char) {
        if self.busy {
            return;
        }
        self.input.insert(self.input_cursor, ch);
        self.input_cursor += ch.len_utf8();
        self.sync_slash_popup_selection();
    }

    pub fn insert_text(&mut self, text: &str) {
        if self.busy || text.is_empty() {
            return;
        }
        self.input.insert_str(self.input_cursor, text);
        self.input_cursor += text.len();
        self.sync_slash_popup_selection();
    }

    pub fn backspace(&mut self) {
        if self.busy || self.input_cursor == 0 {
            return;
        }
        let prev = previous_boundary(&self.input, self.input_cursor);
        self.input.drain(prev..self.input_cursor);
        self.input_cursor = prev;
        self.sync_slash_popup_selection();
    }

    pub fn delete(&mut self) {
        if self.busy || self.input_cursor >= self.input.len() {
            return;
        }
        let next = next_boundary(&self.input, self.input_cursor);
        self.input.drain(self.input_cursor..next);
        self.sync_slash_popup_selection();
    }

    pub fn move_cursor_left(&mut self) {
        self.input_cursor = previous_boundary(&self.input, self.input_cursor);
    }

    pub fn move_cursor_right(&mut self) {
        self.input_cursor = next_boundary(&self.input, self.input_cursor);
    }

    pub fn move_cursor_home(&mut self) {
        self.input_cursor = 0;
    }

    pub fn move_cursor_end(&mut self) {
        self.input_cursor = self.input.len();
    }

    pub fn clear_input(&mut self) {
        self.input.clear();
        self.input_cursor = 0;
        self.slash_popup_selected = 0;
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

    pub fn handle_command(&mut self, command: &str) -> SubmitAction {
        let mut parts = command.split_whitespace();
        let Some(head) = parts.next() else {
            return SubmitAction::Noop;
        };

        match head {
            "/help" => match (parts.next(), parts.next()) {
                (None, None) => {
                    self.help_overlay_visible = true;
                    self.help_overlay_topic = None;
                    self.transcript_overlay = None;
                    self.status = format!("help  {}", self.session_id);
                    SubmitAction::Handled
                }
                (Some(topic), None) => {
                    let Some(command) = slash_command::find(topic) else {
                        self.queue_message(
                            MessageKind::System,
                            format!("unknown help topic: {topic}\nTry /help to list commands."),
                        );
                        self.status = format!("invalid command  {}", self.session_id);
                        return SubmitAction::Handled;
                    };
                    self.help_overlay_visible = true;
                    self.help_overlay_topic = Some(command.command.to_string());
                    self.transcript_overlay = None;
                    self.status = format!("help  {}", self.session_id);
                    SubmitAction::Handled
                }
                _ => {
                    self.queue_message(MessageKind::System, "Usage: /help [command]");
                    self.status = format!("invalid command  {}", self.session_id);
                    SubmitAction::Handled
                }
            },
            "/new" => {
                self.reset_session();
                SubmitAction::Handled
            }
            "/clear" => {
                self.pending_history_lines.clear();
                self.committed_history_lines.clear();
                self.live_message = None;
                self.live_message_had_history = false;
                self.clear_requested = true;
                self.status = format!("cleared  {}", self.session_id);
                self.queue_welcome_banner();
                SubmitAction::Handled
            }
            "/sessions" => {
                let limit = match parts.next() {
                    Some(value) => match value.parse::<usize>() {
                        Ok(limit) if limit > 0 => limit,
                        _ => {
                            self.queue_message(
                                MessageKind::System,
                                "Usage: /sessions [positive_limit]",
                            );
                            self.status = format!("invalid command  {}", self.session_id);
                            return SubmitAction::Handled;
                        }
                    },
                    None => 10,
                };
                if parts.next().is_some() {
                    self.queue_message(MessageKind::System, "Usage: /sessions [positive_limit]");
                    self.status = format!("invalid command  {}", self.session_id);
                    return SubmitAction::Handled;
                }
                SubmitAction::OpenSessionPicker {
                    mode: SessionPickerMode::Browse,
                    limit,
                }
            }
            "/resume" => match (parts.next(), parts.next()) {
                (None, None) => SubmitAction::OpenSessionPicker {
                    mode: SessionPickerMode::Resume,
                    limit: 10,
                },
                (Some("latest"), None) => SubmitAction::ResumeLatest,
                (Some(session_id), None) => SubmitAction::ResumeSession(session_id.to_string()),
                _ => {
                    self.queue_message(MessageKind::System, "Usage: /resume [latest|session_id]");
                    self.status = format!("invalid command  {}", self.session_id);
                    SubmitAction::Handled
                }
            },
            "/skills" => {
                if parts.next().is_some() {
                    self.queue_message(MessageKind::System, "Usage: /skills");
                    self.status = format!("invalid command  {}", self.session_id);
                    return SubmitAction::Handled;
                }
                SubmitAction::ListSkills
            }
            "/config" => {
                if parts.next().is_some() {
                    self.queue_message(MessageKind::System, "Usage: /config");
                    self.status = format!("invalid command  {}", self.session_id);
                    return SubmitAction::Handled;
                }
                SubmitAction::ShowConfig
            }
            "/providers" => {
                if parts.next().is_some() {
                    self.queue_message(MessageKind::System, "Usage: /providers");
                    self.status = format!("invalid command  {}", self.session_id);
                    return SubmitAction::Handled;
                }
                SubmitAction::ListProviders
            }
            "/provider" => match (parts.next(), parts.next(), parts.next()) {
                (None, None, None) | (Some("help"), None, None) => {
                    self.queue_message(MessageKind::Tool, provider_help_text());
                    self.status = format!("provider help  {}", self.session_id);
                    SubmitAction::Handled
                }
                (Some("inspect"), Some(provider_id), None) => {
                    SubmitAction::ShowProvider(provider_id.to_string())
                }
                (Some("default"), Some(provider_id), None) => {
                    SubmitAction::SetDefaultProvider(provider_id.to_string())
                }
                (Some("delete"), Some(provider_id), None) => {
                    SubmitAction::DeleteProvider(provider_id.to_string())
                }
                (Some("create"), _, _) => {
                    let fields = parts.map(ToString::to_string).collect::<Vec<_>>();
                    SubmitAction::CreateProvider(fields)
                }
                (Some("update"), Some(provider_id), _) => {
                    let fields = parts.map(ToString::to_string).collect::<Vec<_>>();
                    SubmitAction::UpdateProvider {
                        provider_id: provider_id.to_string(),
                        fields,
                    }
                }
                _ => {
                    self.queue_message(MessageKind::System, provider_help_text());
                    self.status = format!("invalid command  {}", self.session_id);
                    SubmitAction::Handled
                }
            },
            "/skill" => match (parts.next(), parts.next(), parts.next()) {
                (Some("add"), Some(name), None) => SubmitAction::EnableSkill(name.to_string()),
                (Some("remove"), Some(name), None) => SubmitAction::DisableSkill(name.to_string()),
                (Some("clear"), None, None) => SubmitAction::ClearSkills,
                _ => {
                    self.queue_message(
                        MessageKind::System,
                        "Usage: /skill add <name> | /skill remove <name> | /skill clear",
                    );
                    self.status = format!("invalid command  {}", self.session_id);
                    SubmitAction::Handled
                }
            },
            "/model" => match (parts.next(), parts.next(), parts.next()) {
                (None, None, None) => SubmitAction::ShowModel,
                (Some("show"), None, None) => SubmitAction::ShowModel,
                (Some("set"), Some(name), None) => SubmitAction::SetModel(name.to_string()),
                (Some("clear"), None, None) => SubmitAction::ClearModel,
                _ => {
                    self.queue_message(
                        MessageKind::System,
                        "Usage: /model | /model show | /model set <name> | /model clear",
                    );
                    self.status = format!("invalid command  {}", self.session_id);
                    SubmitAction::Handled
                }
            },
            "/status" => {
                self.queue_message(
                    MessageKind::System,
                    format!(
                        "session: {}\nbusy: {}\nagent_mode: {}\nmax_loop_count: {}\nskills: {}\nmodel_override: {}\ninput: {} chars",
                        self.session_id,
                        self.busy,
                        self.agent_mode,
                        self.max_loop_count,
                        if self.selected_skills.is_empty() {
                            "(none)".to_string()
                        } else {
                            self.selected_skills.join(", ")
                        },
                        self.selected_model
                            .clone()
                            .unwrap_or_else(|| "(none)".to_string()),
                        self.input.chars().count(),
                    ),
                );
                self.status = format!("status  {}", self.session_id);
                SubmitAction::Handled
            }
            "/transcript" => {
                self.open_transcript_overlay();
                SubmitAction::Handled
            }
            "/welcome" => {
                self.queue_welcome_banner();
                self.status = format!("welcome  {}", self.session_id);
                SubmitAction::Handled
            }
            "/exit" => {
                self.should_quit = true;
                SubmitAction::Handled
            }
            other => {
                self.queue_message(MessageKind::System, format!("Unknown command: {other}"));
                self.status = format!("unknown command  {}", self.session_id);
                SubmitAction::Handled
            }
        }
    }

    pub fn load_resumed_session(
        &mut self,
        session_id: String,
        recent_messages: Vec<(MessageKind, String)>,
    ) {
        self.sync_session_sequence(&session_id);
        self.session_id = session_id;
        self.clear_input();
        self.busy = false;
        self.live_message = None;
        self.live_message_had_history = false;
        self.request_started_at = None;
        self.first_output_latency = None;
        self.last_request_duration = None;
        self.last_first_output_latency = None;
        self.active_tools.clear();
        self.pending_history_lines.clear();
        self.committed_history_lines.clear();
        self.pending_welcome_banner = false;
        self.clear_requested = true;
        self.backend_restart_requested = true;
        self.help_overlay_visible = false;
        self.help_overlay_topic = None;
        self.session_picker = None;
        self.transcript_overlay = None;
        self.provider_catalog = None;
        for (kind, message) in recent_messages {
            self.queue_message(kind, message);
        }
        self.status = format!("resumed  {}", self.session_id);
    }

    pub fn enable_skill(&mut self, skill: String) {
        if self.selected_skills.iter().any(|item| item == &skill) {
            self.queue_message(
                MessageKind::System,
                format!("skill already active: {skill}"),
            );
            self.status = format!("skill active  {}", self.session_id);
            return;
        }
        self.selected_skills.push(skill.clone());
        self.selected_skills.sort();
        self.backend_restart_requested = true;
        self.queue_message(MessageKind::Tool, format!("skill enabled: {skill}"));
        self.status = format!("skills  {}", self.session_id);
    }

    pub fn disable_skill(&mut self, skill: &str) {
        let previous_len = self.selected_skills.len();
        self.selected_skills.retain(|item| item != skill);
        if self.selected_skills.len() == previous_len {
            self.queue_message(MessageKind::System, format!("skill not active: {skill}"));
            self.status = format!("skills  {}", self.session_id);
            return;
        }
        self.backend_restart_requested = true;
        self.queue_message(MessageKind::Tool, format!("skill removed: {skill}"));
        self.status = format!("skills  {}", self.session_id);
    }

    pub fn clear_skills(&mut self) {
        let cleared = self.selected_skills.len();
        self.selected_skills.clear();
        self.backend_restart_requested = true;
        self.queue_message(
            MessageKind::Tool,
            format!("cleared {} active skill(s)", cleared),
        );
        self.status = format!("skills  {}", self.session_id);
    }

    pub fn set_model_override(&mut self, model: String) {
        self.selected_model = Some(model.clone());
        self.backend_restart_requested = true;
        self.queue_message(MessageKind::Tool, format!("model override set: {model}"));
        self.status = format!("model  {}", self.session_id);
    }

    pub fn clear_model_override(&mut self) {
        match self.selected_model.take() {
            Some(model) => {
                self.backend_restart_requested = true;
                self.queue_message(
                    MessageKind::Tool,
                    format!("cleared model override: {model}"),
                );
            }
            None => {
                self.queue_message(MessageKind::System, "no model override is active");
            }
        }
        self.status = format!("model  {}", self.session_id);
    }

    fn sync_slash_popup_selection(&mut self) {
        if self.help_overlay_visible || self.session_picker.is_some() {
            self.slash_popup_selected = 0;
            return;
        }
        let len = self.popup_matches().len();
        if len == 0 {
            self.slash_popup_selected = 0;
        } else {
            self.slash_popup_selected = self.slash_popup_selected.min(len.saturating_sub(1));
        }
    }

    fn sync_session_picker_selection(&mut self) {
        let len = self
            .filtered_session_picker_items()
            .map(|items| items.items.len())
            .unwrap_or(0);
        let Some(picker) = self.session_picker.as_mut() else {
            return;
        };
        if len == 0 {
            picker.selected = 0;
        } else {
            picker.selected = picker.selected.min(len.saturating_sub(1));
        }
    }

    fn queue_welcome_banner(&mut self) {
        self.pending_welcome_banner = true;
    }

    fn sync_session_sequence(&mut self, session_id: &str) {
        let Some(raw_number) = session_id.strip_prefix("local-") else {
            return;
        };
        let Ok(number) = raw_number.parse::<u32>() else {
            return;
        };
        self.session_seq = self.session_seq.max(number.saturating_add(1));
    }

    fn append_live_chunk(&mut self, kind: MessageKind, chunk: &str) {
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

    fn flush_live_message(&mut self) {
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

    fn queue_message(&mut self, kind: MessageKind, text: impl Into<String>) {
        if kind != MessageKind::User {
            self.record_first_output();
        }
        self.pending_history_lines
            .extend(format_message(kind, &text.into(), true));
    }

    pub fn materialize_pending_ui(&mut self, width: u16) {
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

    fn record_first_output(&mut self) {
        if self.first_output_latency.is_some() {
            return;
        }
        if let Some(started) = self.request_started_at {
            self.first_output_latency = Some(started.elapsed());
        }
    }
}

fn previous_boundary(text: &str, index: usize) -> usize {
    if index == 0 {
        return 0;
    }
    text[..index]
        .char_indices()
        .last()
        .map(|(idx, _)| idx)
        .unwrap_or(0)
}

fn next_boundary(text: &str, index: usize) -> usize {
    if index >= text.len() {
        return text.len();
    }
    let mut iter = text[index..].char_indices();
    let _ = iter.next();
    index
        + iter
            .next()
            .map(|(offset, _)| offset)
            .unwrap_or(text[index..].len())
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

fn current_workspace_label() -> String {
    let repo_root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|path| path.parent())
        .map(std::path::Path::to_path_buf);
    let cwd = repo_root.or_else(|| std::env::current_dir().ok());
    let home = std::env::var("HOME").ok();

    match (cwd, home) {
        (Some(cwd), Some(home)) => {
            let cwd = cwd.display().to_string();
            if let Some(stripped) = cwd.strip_prefix(&home) {
                format!("~{}", stripped)
            } else {
                cwd
            }
        }
        (Some(cwd), None) => cwd.display().to_string(),
        _ => ".".to_string(),
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
