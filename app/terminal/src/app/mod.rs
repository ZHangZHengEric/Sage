use std::collections::BTreeMap;
use std::time::{Duration, Instant};

use ratatui::text::Line;

mod commands;
mod input;
mod runtime;
mod surfaces;
#[cfg(test)]
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
    ShowDoctor {
        probe_provider: bool,
    },
    ShowConfig,
    InitConfig {
        path: Option<String>,
        force: bool,
    },
    ListProviders,
    ShowProvider(String),
    VerifyProvider(Vec<String>),
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

pub(crate) struct FilteredSessionPicker<'a> {
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
}

fn current_workspace_label() -> String {
    let cwd = std::env::current_dir().ok();
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
