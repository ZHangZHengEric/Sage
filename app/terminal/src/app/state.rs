use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use ratatui::text::Line;

use crate::backend::BackendStats;
use crate::display_policy::DisplayMode;

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
    ListAgents,
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
pub(crate) struct SessionPickerState {
    pub(crate) mode: SessionPickerMode,
    pub(crate) items: Vec<SessionPickerEntry>,
    pub(crate) filter_query: String,
    pub(crate) selected: usize,
}

pub(crate) struct FilteredSessionPicker<'a> {
    pub(crate) items: Vec<(usize, &'a SessionPickerEntry)>,
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
pub(crate) struct TranscriptOverlayState {
    pub(crate) scroll: u16,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct ProviderCandidate {
    pub(crate) id: String,
    pub(crate) name: String,
    pub(crate) model: String,
    pub(crate) base_url: String,
    pub(crate) is_default: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum AgentPopupMode {
    Set,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct AgentCandidate {
    pub(crate) id: String,
    pub(crate) name: String,
    pub(crate) agent_mode: String,
    pub(crate) is_default: bool,
    pub(crate) updated_at: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum ProviderPopupMode {
    Inspect,
    Default,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct SkillCandidate {
    pub(crate) name: String,
    pub(crate) description: String,
    pub(crate) source: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum SkillPopupMode {
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
    pub selected_agent_id: Option<String>,
    pub agent_mode: String,
    pub max_loop_count: u32,
    pub workspace_label: String,
    pub(crate) workspace_override: Option<PathBuf>,
    pub status: String,
    pub busy: bool,
    pub should_quit: bool,
    pub selected_skills: Vec<String>,
    pub selected_model: Option<String>,
    pub display_mode: DisplayMode,
    pub pending_history_lines: Vec<Line<'static>>,
    pub(crate) committed_history_lines: Vec<Line<'static>>,
    pub live_message: Option<(MessageKind, String)>,
    pub(crate) live_message_had_history: bool,
    pub(crate) request_started_at: Option<Instant>,
    pub(crate) first_output_latency: Option<Duration>,
    pub(crate) last_request_duration: Option<Duration>,
    pub(crate) last_first_output_latency: Option<Duration>,
    pub(crate) pending_backend_stats: Option<BackendStats>,
    pub(crate) active_phase: Option<String>,
    pub(crate) active_tools: BTreeMap<String, ActiveToolRecord>,
    pub(crate) tool_step_seq: u32,
    pub(crate) pending_welcome_banner: bool,
    pub(crate) clear_requested: bool,
    pub(crate) backend_restart_requested: bool,
    pub(crate) slash_popup_selected: usize,
    pub(crate) help_overlay_visible: bool,
    pub(crate) help_overlay_topic: Option<String>,
    pub(crate) session_picker: Option<SessionPickerState>,
    pub(crate) transcript_overlay: Option<TranscriptOverlayState>,
    pub(crate) agent_catalog: Option<Vec<AgentCandidate>>,
    pub(crate) provider_catalog: Option<Vec<ProviderCandidate>>,
    pub(crate) skill_catalog: Option<Vec<SkillCandidate>>,
}

#[derive(Clone, Debug)]
pub(crate) struct ActiveToolRecord {
    pub(crate) step: u32,
    pub(crate) started_at: Instant,
}

impl App {
    pub fn new() -> Self {
        let mut app = Self {
            input: String::new(),
            input_cursor: 0,
            session_seq: 1,
            session_id: String::new(),
            user_id: "default_user".to_string(),
            selected_agent_id: None,
            agent_mode: "simple".to_string(),
            max_loop_count: 50,
            workspace_label: default_workspace_label(),
            workspace_override: None,
            status: String::new(),
            busy: false,
            should_quit: false,
            selected_skills: Vec::new(),
            selected_model: None,
            display_mode: DisplayMode::Compact,
            pending_history_lines: Vec::new(),
            committed_history_lines: Vec::new(),
            live_message: None,
            live_message_had_history: false,
            request_started_at: None,
            first_output_latency: None,
            last_request_duration: None,
            last_first_output_latency: None,
            pending_backend_stats: None,
            active_phase: None,
            active_tools: BTreeMap::new(),
            tool_step_seq: 0,
            pending_welcome_banner: false,
            clear_requested: false,
            backend_restart_requested: false,
            slash_popup_selected: 0,
            help_overlay_visible: false,
            help_overlay_topic: None,
            session_picker: None,
            transcript_overlay: None,
            agent_catalog: None,
            provider_catalog: None,
            skill_catalog: None,
        };
        app.reset_session();
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
        self.pending_backend_stats = None;
        self.active_phase = None;
        self.active_tools.clear();
        self.tool_step_seq = 0;
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
        self.agent_catalog = None;
        self.provider_catalog = None;
        self.skill_catalog = None;
        self.status = format!("ready  {}", self.session_id);
        self.queue_welcome_banner();
    }

    pub fn set_workspace_override(&mut self, workspace: Option<PathBuf>) {
        self.workspace_override = workspace.map(normalize_workspace_path);
        self.workspace_label = self
            .workspace_override
            .as_deref()
            .map(format_workspace_label)
            .unwrap_or_else(default_workspace_label);
    }

    pub fn workspace_override_path(&self) -> Option<&Path> {
        self.workspace_override.as_deref()
    }
}

fn normalize_workspace_path(path: PathBuf) -> PathBuf {
    if path.is_absolute() {
        path
    } else {
        std::env::current_dir()
            .unwrap_or_else(|_| PathBuf::from("."))
            .join(path)
    }
}

fn default_workspace_label() -> String {
    "~/.sage".to_string()
}

fn format_workspace_label(path: &Path) -> String {
    let display = path.display().to_string();
    let home = std::env::var("HOME").ok();

    match home {
        Some(home) => display
            .strip_prefix(&home)
            .map(|stripped| format!("~{}", stripped))
            .unwrap_or(display),
        None => display,
    }
}
