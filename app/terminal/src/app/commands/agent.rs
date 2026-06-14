use crate::app::{App, MessageKind};
use crate::display_policy::DisplayMode;
use crate::preferences::persist_app_preferences_notice;
use std::path::PathBuf;

const VALID_AGENT_MODES: &[&str] = &["simple", "multi", "fibre"];

impl App {
    pub fn apply_startup_options(
        &mut self,
        agent_id: Option<String>,
        agent_config: Option<PathBuf>,
        agent_mode: Option<String>,
        display_mode: Option<DisplayMode>,
        workspace: Option<PathBuf>,
        sandbox_type: Option<String>,
    ) {
        self.agent_config_path = agent_config;
        self.selected_agent_id = if self.agent_config_path.is_some() {
            None
        } else {
            agent_id.filter(|value| !value.trim().is_empty())
        };
        if let Some(mode) = agent_mode {
            self.agent_mode = mode;
            self.agent_mode_override = true;
        }
        if let Some(display_mode) = display_mode {
            self.display_mode = display_mode;
        }
        self.set_workspace_override(workspace);
        self.sandbox_type = sandbox_type;
        if self
            .agent_config_path
            .as_ref()
            .map(|path| is_bundled_coding_agent_config(&path.display().to_string()))
            .unwrap_or(false)
            && self.workspace_override_path().is_none()
        {
            self.queue_message(
                MessageKind::System,
                "coding agent config requires a repo workspace; start with --workspace /path/to/repo or use /workspace set /path/to/repo",
            );
        }
    }

    pub fn set_selected_agent_id(&mut self, agent_id: String) {
        let normalized = agent_id.trim().to_string();
        if normalized.is_empty() {
            self.queue_message(MessageKind::System, "Usage: /agent set <agent_id>");
            self.status = format!("invalid command  {}", self.session_id);
            return;
        }
        self.selected_agent_id = Some(normalized.clone());
        self.agent_config_path = None;
        self.clear_agent_catalog();
        self.skill_catalog = None;
        self.backend_restart_requested = true;
        persist_app_preferences_notice(self);
        self.queue_message(MessageKind::System, format!("agent set: {normalized}"));
        self.status = format!("agent  {}", self.session_id);
    }

    pub fn clear_selected_agent_id(&mut self) {
        let selected_agent_id = self.selected_agent_id.take();
        let agent_config_path = self.agent_config_path.take();
        match (selected_agent_id, agent_config_path) {
            (Some(agent_id), None) => {
                self.clear_agent_catalog();
                self.skill_catalog = None;
                self.backend_restart_requested = true;
                persist_app_preferences_notice(self);
                self.queue_message(MessageKind::System, format!("cleared agent: {agent_id}"));
            }
            (None, Some(agent_config)) => {
                self.clear_agent_catalog();
                self.skill_catalog = None;
                self.backend_restart_requested = true;
                self.queue_message(
                    MessageKind::System,
                    format!("cleared agent config: {}", agent_config.display()),
                );
            }
            (Some(agent_id), Some(agent_config)) => {
                self.clear_agent_catalog();
                self.skill_catalog = None;
                self.backend_restart_requested = true;
                persist_app_preferences_notice(self);
                self.queue_message(
                    MessageKind::System,
                    format!(
                        "cleared agent: {agent_id}\ncleared agent config: {}",
                        agent_config.display()
                    ),
                );
            }
            (None, None) => {
                self.queue_message(MessageKind::System, "no agent override is active");
            }
        }
        self.status = format!("agent  {}", self.session_id);
    }

    pub fn set_agent_config_path(&mut self, path: String) {
        let normalized = normalize_agent_config_value(&path);
        if normalized.is_empty() {
            self.queue_message(MessageKind::System, "Usage: /agent config <path|coding>");
            self.status = format!("invalid command  {}", self.session_id);
            return;
        }
        self.selected_agent_id = None;
        self.agent_config_path = Some(PathBuf::from(normalized.as_str()));
        self.agent_mode_override = false;
        self.clear_agent_catalog();
        self.skill_catalog = None;
        self.backend_restart_requested = true;
        self.queue_message(
            MessageKind::System,
            format!("agent config set: {normalized}"),
        );
        if is_bundled_coding_agent_config(&normalized) && self.workspace_override_path().is_none() {
            self.queue_message(
                MessageKind::System,
                "coding agent config requires a repo workspace; use /workspace set /path/to/repo before sending coding tasks",
            );
        }
        self.status = format!("agent  {}", self.session_id);
    }

    pub fn set_agent_mode_selection(&mut self, mode: String) {
        self.agent_mode = mode.clone();
        self.agent_mode_override = true;
        self.backend_restart_requested = true;
        persist_app_preferences_notice(self);
        self.queue_message(MessageKind::System, format!("agent mode set: {mode}"));
        self.status = format!("mode  {}", self.session_id);
    }

    pub fn queue_agent_status(&mut self) {
        let message = if let Some(agent_config) = self.agent_config_path.as_ref() {
            format!(
                "agent_config: {}\nagent_mode: {}\nworkspace: {}",
                agent_config.display(),
                self.agent_mode_status_label(),
                self.workspace_label
            )
        } else {
            format!(
                "agent_id: {}\nagent_mode: {}\nworkspace: {}",
                self.agent_id_status_label(),
                self.agent_mode_status_label(),
                self.workspace_label
            )
        };
        self.queue_message(MessageKind::System, message);
        self.status = format!("agent  {}", self.session_id);
    }

    pub(crate) fn agent_id_status_label(&self) -> String {
        self.selected_agent_id
            .clone()
            .unwrap_or_else(|| "(default)".to_string())
    }

    pub(crate) fn agent_mode_status_label(&self) -> String {
        if self.agent_config_path.is_some() && !self.agent_mode_override {
            "config default".to_string()
        } else {
            self.agent_mode.clone()
        }
    }

    pub(crate) fn max_loop_count_status_label(&self) -> String {
        if self.agent_config_path.is_some() {
            "config default".to_string()
        } else {
            self.max_loop_count.to_string()
        }
    }

    pub(crate) fn active_agent_label(&self) -> String {
        self.agent_config_path
            .as_ref()
            .map(|path| format!("config {}", path.display()))
            .or_else(|| {
                self.selected_agent_id
                    .as_ref()
                    .map(|id| format!("agent {id}"))
            })
            .unwrap_or_else(|| "default agent".to_string())
    }
}

pub(crate) fn normalize_agent_config_value(value: &str) -> String {
    let trimmed = value.trim();
    trimmed
        .strip_prefix('"')
        .and_then(|value| value.strip_suffix('"'))
        .or_else(|| {
            trimmed
                .strip_prefix('\'')
                .and_then(|value| value.strip_suffix('\''))
        })
        .unwrap_or(trimmed)
        .trim()
        .to_string()
}

fn is_bundled_coding_agent_config(value: &str) -> bool {
    value == "coding"
        || value == "examples/coding_agent_config.json"
        || value.ends_with("/examples/coding_agent_config.json")
}

pub(crate) fn normalize_agent_mode(value: &str) -> Option<String> {
    let normalized = value.trim().to_lowercase();
    VALID_AGENT_MODES
        .contains(&normalized.as_str())
        .then_some(normalized)
}
